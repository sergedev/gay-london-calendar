#!/usr/bin/env python3
"""
Refresh InterBank LGBT+ Network events.

Discovery: scrapes the OutSavvy organiser page for event URLs.
Each event page yields title, start/end, location, price (max active tier),
and banner image via og: meta tags + inline ISO datetimes.

Recurrence: 3rd Thursday of each month at 6pm. Projections cover months in
the projection window that don't have a scraped confirmed event.

OutSavvy doesn't expose attendee counts — known limitation.

Idempotent: scraped events merge with existing records preserving custom
fields. Past confirmed entries are kept as history.

Run: python3 scripts/refresh-interbank.py
"""

import html
import json
import re
import subprocess
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))
from _merge import merge_preserving_custom  # noqa: E402

DATA_FILE = ROOT / 'data' / 'interbank.json'

SOURCE_ID = 'interbank'
ORG_URL = 'https://www.outsavvy.com/organiser/interbank-lgbt-network1'
PROJECTION_MONTHS = 4

UA = ('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')

LONDON = ZoneInfo('Europe/London')

PROJECTED_START_HM = (18, 0)
PROJECTED_END_HM   = (22, 0)
PROJECTED_LOCATION = None  # don't show a location for projected — venue revealed on OutSavvy a few weeks ahead
DESC_PROJECTED = (
    "Projected based on the usual 3rd-Thursday-of-month cadence at 6pm. "
    "Venue varies — InterBank announces it via OutSavvy a few weeks ahead."
)
SOURCE_WEBSITE = 'https://www.outsavvy.com/organiser/interbank-lgbt-network1'


def curl(url):
    r = subprocess.run(['curl', '-sL', url, '-H', f'User-Agent: {UA}'],
                       capture_output=True, text=True, check=True)
    return r.stdout


def discover_event_urls():
    html = curl(ORG_URL)
    urls = re.findall(r'https://www\.outsavvy\.com/event/\d+/[a-zA-Z0-9-]+', html)
    return sorted(set(urls))


def og(page_html, key):
    m = re.search(rf'<meta[^>]+og:{key}"[^>]+content="([^"]*)"', page_html)
    return html.unescape(m.group(1)) if m else ''


_MONTHS_RE = ('January|February|March|April|May|June|July|August|September'
              '|October|November|December')


def _strip_trailing_date(title):
    """Drop a trailing date OutSavvy tacks onto the event name so the recurring
    series reads cleanly. Handles both orders, optional year, and removes a
    leftover ' -'/'–'/':' separator:
        'InterBank Networking - 18 June'                 -> 'InterBank Networking'
        'InterBank Networking - 19 February 2026'        -> 'InterBank Networking'
        '... & LGBT+ History Month event - 19 Feb 2026'  -> '... & LGBT+ History Month event'
    A themed suffix (anything that isn't the date) is preserved.
    """
    pat = (rf'\s*[-–:]?\s*(?:\d{{1,2}}(?:st|nd|rd|th)?\s+(?:{_MONTHS_RE})'
           rf'|(?:{_MONTHS_RE})\s+\d{{1,2}}(?:st|nd|rd|th)?)'
           rf'(?:,?\s+\d{{4}})?\s*$')
    return re.sub(pat, '', title, flags=re.IGNORECASE).strip()


def parse_outsavvy_event(url):
    html = curl(url)
    title_raw = og(html, 'title')
    # Strip " Tickets - <City> - OutSavvy" suffix
    title = re.sub(r'\s+Tickets\s+-\s+[^-]+\s+-\s+OutSavvy\s*$', '', title_raw).strip()
    if not title:
        title = title_raw
    title = _strip_trailing_date(title)

    description = og(html, 'description')
    image = og(html, 'image')

    # London filter (defensive — InterBank only does London but safety check)
    is_london = '- London -' in title_raw

    # Dates: HTML has multiple ISO datetimes; the event start/end is the
    # first pair (the third one is usually a "doors open" 1h prior).
    dates = re.findall(r'(202[6-7]-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[+\-]\d{2}:\d{2})', html)
    start = dates[0] if dates else None
    end   = dates[1] if len(dates) > 1 else None

    # Price: prefer OutSavvy's structured inline metadata (lowPrice/highPrice/
    # price) which represent the canonical event's pricing. A page-wide £-regex
    # is wrong here because OutSavvy embeds related-event marketing cards (e.g.
    # 'BUTCH PRIDE £18.50–£25') in the sidebar — those leak into a naive scan
    # and overwrite our event's real price. Confirmed bug 2026-06-05.
    price_amounts = []
    for m in re.finditer(r'"(?:low|high)Price"\s*:\s*(\d+(?:\.\d+)?)', html):
        price_amounts.append(float(m.group(1)))
    if not price_amounts:
        m = re.search(r'"price"\s*:\s*"?(\d+(?:\.\d+)?)"?', html)
        if m:
            price_amounts.append(float(m.group(1)))
    if not price_amounts:
        price = None
    else:
        top = max(price_amounts)
        price = 'Free' if top == 0 else (f'£{top:.2f}' if top != int(top) else f'£{int(top)}')

    # Venue from og:description (InterBank uses "at the <venue>" phrasing)
    venue = 'London'
    m = re.search(r'at\s+the\s+([^.\n]{3,80}?)(?:\s*\.|\s+at\s|\s+from\s|$)', description, re.IGNORECASE)
    if m:
        venue = m.group(1).strip().rstrip('.,')

    return {
        'is_london': is_london,
        'title': title,
        'start': start,
        'end': end,
        'image': image,
        'price': price,
        'location': venue,
        'description': description,
        'url': url,
    }


def third_thursday(year, month):
    d = date(year, month, 1)
    while d.weekday() != 3:  # Thursday
        d += timedelta(days=1)
    return d + timedelta(days=14)  # +2 weeks = 3rd Thursday


def upcoming_months(start_ym, n):
    y, m = start_ym
    for _ in range(n):
        yield (y, m)
        m += 1
        if m > 12:
            m, y = 1, y + 1


def year_month(date_str):
    return (date_str or '')[:7]


def slug_from_url(url):
    m = re.search(r'/event/(\d+)/', url)
    return f'interbank-os-{m.group(1)}' if m else url.rstrip('/').split('/')[-1]


def _canonical_id(start_iso):
    """Stable month-keyed id for the InterBank monthly networking series.
    Projected and confirmed entries in a given month share this id so a
    confirmed scrape overwrites the projection in place — preserving
    short-codes and share links."""
    return f'interbank-{(start_iso or "")[:7]}'


def confirmed_record(parsed):
    return {
        'id': _canonical_id(parsed['start']),
        'source': SOURCE_ID,
        'title': parsed['title'],
        'start': parsed['start'],
        'end': parsed['end'],
        'location': parsed['location'],
        'price': parsed['price'],
        'url': parsed['url'],
        'image': parsed['image'] or None,
        'status': 'confirmed',
        'recurrence': 'third-thursday-monthly',
        'links': {'tickets': parsed['url']},
        'description': parsed['description'],
        'soldOut': False,
        'categories': ['social'],
        'categoriesOverride': None,
    }


def projection(year, month):
    d = third_thursday(year, month)
    sh, sm = PROJECTED_START_HM
    eh, em = PROJECTED_END_HM
    start_dt = datetime(d.year, d.month, d.day, sh, sm, tzinfo=LONDON)
    end_dt   = datetime(d.year, d.month, d.day, eh, em, tzinfo=LONDON)
    ym = f'{year:04d}-{month:02d}'
    return {
        'id': f'interbank-{ym}',
        'source': SOURCE_ID,
        'title': 'InterBank Networking',
        'start': start_dt.isoformat(timespec='seconds'),
        'end':   end_dt.isoformat(timespec='seconds'),
        'location': PROJECTED_LOCATION,
        'price': None,
        'url': SOURCE_WEBSITE,
        'image': None,
        'status': 'projected',
        'recurrence': 'third-thursday-monthly',
        'links': {},
        'description': DESC_PROJECTED,
        'soldOut': False,
        'categories': ['social'],
        'categoriesOverride': None,
    }


def main():
    today = date.today()
    existing = []
    if DATA_FILE.exists():
        existing = json.loads(DATA_FILE.read_text())

    # Normalize legacy ids (outsavvy-based confirmed, '-projected' suffix
    # projections) to the canonical month-keyed scheme. Idempotent — keeps
    # existing_by_id lookups working so short-codes / custom fields survive
    # a projection→confirmed swap.
    for e in existing:
        if e.get('source') == SOURCE_ID and e.get('start'):
            e['id'] = _canonical_id(e['start'])

    existing_by_id = {e['id']: e for e in existing}

    print(f'GET {ORG_URL}', file=sys.stderr)
    urls = discover_event_urls()
    print(f'  -> {len(urls)} event URL(s)', file=sys.stderr)

    confirmed = []
    for url in urls:
        try:
            parsed = parse_outsavvy_event(url)
        except subprocess.CalledProcessError as e:
            print(f'  FAIL {url}: {e}', file=sys.stderr)
            continue
        if not parsed['start']:
            print(f'  SKIP no start date: {url}', file=sys.stderr)
            continue
        if not parsed['is_london']:
            print(f'  SKIP non-London: {url}', file=sys.stderr)
            continue
        rec = confirmed_record(parsed)
        confirmed.append(rec)
        print(f"  OK   {rec['start'][:10]}  {rec['price']!s:<7}  {rec['title'][:55]}",
              file=sys.stderr)

    # Persist every previously-stored event. Outsavvy drops events from
    # listings once they happen — sometimes earlier — but we don't want
    # them to vanish from the calendar.
    all_by_id = {e['id']: e for e in existing}
    for e in confirmed:
        all_by_id[e['id']] = e  # fresh scrape wins on canonical-id collision

    # Confirmed months: any month with a confirmed event (stored or fresh).
    # Stops a regenerated projection from downgrading a stored confirmed
    # event whose Outsavvy listing has dropped.
    confirmed_months = {year_month(e['start']) for e in all_by_id.values()
                        if e.get('status') == 'confirmed'}

    projected = []
    for (y, m) in upcoming_months((today.year, today.month), PROJECTION_MONTHS + 1):
        ym = f'{y:04d}-{m:02d}'
        if ym in confirmed_months:
            continue
        if third_thursday(y, m) < today:
            continue
        projected.append(projection(y, m))

    for e in projected:
        all_by_id[e['id']] = e

    merged_list = [merge_preserving_custom(r, existing_by_id.get(r['id']))
                   for r in all_by_id.values()]
    out = sorted(merged_list, key=lambda e: e.get('start') or '')

    DATA_FILE.write_text(json.dumps(out, indent=2, ensure_ascii=False) + '\n')
    confirmed_count = sum(1 for e in out if e.get('status') == 'confirmed')
    projected_count = sum(1 for e in out if e.get('status') == 'projected')
    print(f'\nWrote {len(out)} event(s) to {DATA_FILE.relative_to(ROOT)}', file=sys.stderr)
    print(f'  {confirmed_count} confirmed, {projected_count} projected (incl. previously-stored)',
          file=sys.stderr)
    for e in out:
        when = (e.get('start') or '')[:10]
        tag = 'past' if when < today.isoformat() else e['status']
        print(f"  [{tag:<9}] {when}  {e['title'][:55]}", file=sys.stderr)


if __name__ == '__main__':
    main()
