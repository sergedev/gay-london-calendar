#!/usr/bin/env python3
"""
Refresh BGO Monthly Mixer events at The Cock Tavern.

Scrapes Nas.com for currently-listed Monthly Mixer events, then fills the
remaining months in the projection window with first-Thursday placeholders.
Touches *only* mixer rows inside big-gay-out.json -- all other BGO events
(hikes, swims, theatre, etc.) are passed through untouched.

Match key is (source='big-gay-out', year-month). A confirmed mixer in month M
replaces the projection for M, even if the date shifts off the first Thursday.

Discovery:
  1. The Nas.com sitemap (xml) is scanned for any '/big-gay-out/events/.*mixer.*' slug.
  2. A set of known historical URLs is added as seeds. (Nas drops past events
     from the sitemap, so this preserves them for calendar history.)

Run: python3 scripts/refresh-bgo-mixer.py
"""

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

DATA_FILE = ROOT / 'data' / 'big-gay-out.json'

SOURCE_ID = 'big-gay-out'
SITEMAP_URL = 'https://nas.com/sitemaps/user-generated-seller-pages-1.xml'
PROJECTION_MONTHS = 4

# Historical mixer URLs that won't appear in the sitemap anymore (past events).
# Add new ones here only if Nas removes them before the script can pick them up.
KNOWN_MIXER_URLS = [
    'https://nas.com/big-gay-out/events/monthly-mixer-at-the-cock-tavern',
    'https://nas.com/big-gay-out/events/monthly-mixer-at-the-cock-tavern--1776872680204',
]

UA = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'

LONDON = ZoneInfo('Europe/London')

VENUE = 'The Cock Tavern, Kennington'
MIXER_BASE_TITLE = 'Monthly Mixer at The Cock Tavern'
PROJECTED_START_HM = (19, 30)  # 7:30 PM London local
PROJECTED_END_HM   = (23, 30)  # 11:30 PM London local

DESC_PROJECTED = (
    "Projected based on the usual first-Thursday-of-month cadence. "
    "Tickets typically released a few weeks ahead."
)


def curl(url):
    r = subprocess.run(
        ['curl', '-sL', url, '-H', f'User-Agent: {UA}'],
        capture_output=True, text=True, check=True,
    )
    return r.stdout


def first_thursday_of_month(year, month):
    d = date(year, month, 1)
    while d.weekday() != 3:  # Thursday
        d += timedelta(days=1)
    return d


def year_month(date_str):
    return date_str[:7]


def is_mixer_event(e):
    title = (e.get('title') or '').lower()
    return e.get('source') == SOURCE_ID and 'mixer' in title and 'cock tavern' in title


def discover_mixer_urls():
    urls = set(KNOWN_MIXER_URLS)
    try:
        xml = curl(SITEMAP_URL)
    except subprocess.CalledProcessError as e:
        print(f'  WARN sitemap fetch failed: {e}', file=sys.stderr)
        return sorted(urls)
    for u in re.findall(r'https://nas\.com/big-gay-out/events/[a-zA-Z0-9-]+', xml):
        if 'mixer' in u.lower():
            urls.add(u)
    return sorted(urls)


def parse_nas_event(url):
    try:
        html = curl(url)
    except subprocess.CalledProcessError:
        return None
    m = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>',
                  html, re.DOTALL)
    if not m:
        return None
    try:
        data = json.loads(m.group(1))
    except Exception:
        return None
    ei = (data.get('props', {})
              .get('pageProps', {})
              .get('pageInfo', {})
              .get('templateData', {})
              .get('eventInfo'))
    return ei


def clean_title(raw):
    # BGO titles often have emoji and month prefixes like "🐓June Mixer at The Cock Tavern 🐓".
    # Strip emoji and collapse whitespace, but keep month prefix so the entry is identifiable.
    t = re.sub(r'[^\w\s,&\'\-]', ' ', raw or '')
    t = re.sub(r'\s+', ' ', t).strip()
    return t or MIXER_BASE_TITLE


def _format_gbp(pence):
    g = pence / 100
    return f'£{g:.2f}' if g != int(g) else f'£{int(g)}'


def _extract_price(ei):
    """Public/non-member price. Prefer max active tier; fall back to amount."""
    tp = ei.get('tieredPrices') or {}
    amounts = []
    if tp.get('isActive') and tp.get('prices'):
        for tier in tp['prices']:
            if not tier.get('isActive'):
                continue
            pc = tier.get('pricingConfig') or {}
            a = pc.get('amount')
            if a is not None:
                amounts.append(a)
    if not amounts:
        a = ei.get('amount')
        if a is not None:
            amounts.append(a)
    if not amounts:
        return 'Free'
    top = max(amounts)
    return 'Free' if top == 0 else _format_gbp(top)


def _canonical_mixer_id(start_iso):
    """Stable month-keyed id for the mixer series. Both projected and
    confirmed entries in a given month share this id, so a confirmed scrape
    overwrites the projection in place — preserving any short-codes and
    share links issued against the projection."""
    dt = datetime.fromisoformat(start_iso.replace('Z', '+00:00')).astimezone(LONDON)
    return f'bgo-mixer-{dt.year:04d}-{dt.month:02d}'


def confirmed_from_event_info(ei, url):
    title = clean_title(ei.get('title'))
    start = ei.get('startTime')
    end   = ei.get('endTime')

    price = _extract_price(ei)

    rec = {
        'id': _canonical_mixer_id(start),
        'source': SOURCE_ID,
        'title': title,
        'start': start,
        'end': end,
        'location': VENUE,
        'price': price,
        'url': url,
        'image': ei.get('bannerImg'),
        'status': 'confirmed',
        'recurrence': 'first-thursday-monthly',
        'links': {'tickets': url},
        'description': ei.get('description') or '',
        # nas.com's isSoldOut only flips true on explicit host close. Events
        # that fill organically still report isSoldOut=false, so also flag
        # sold-out when attendance reaches capacity.
        'soldOut': bool(ei.get('isSoldOut')) or _is_capacity_full(ei),
        'categories': ['social'],
        'categoriesOverride': None,
    }
    if not ei.get('hideAttendeesCount'):
        going = ei.get('goingAttendees')
        if going is None:
            going = ei.get('attendees')
        if going is not None:
            rec['attendees'] = int(going)
        if ei.get('isCapacitySet') and ei.get('attendeeLimit'):
            rec['attendeeLimit'] = int(ei['attendeeLimit'])
    return rec


def _is_capacity_full(ei):
    going = ei.get('goingAttendees')
    if going is None:
        going = ei.get('attendees')
    limit = ei.get('attendeeLimit') or 0
    return (
        bool(ei.get('isCapacitySet'))
        and limit > 0
        and going is not None
        and int(going) >= int(limit)
    )


def projection(year, month):
    d = first_thursday_of_month(year, month)
    sh, sm = PROJECTED_START_HM
    eh, em = PROJECTED_END_HM
    start_dt = datetime(d.year, d.month, d.day, sh, sm, tzinfo=LONDON)
    end_dt   = datetime(d.year, d.month, d.day, eh, em, tzinfo=LONDON)
    ym = f'{year:04d}-{month:02d}'
    return {
        'id': f'bgo-mixer-{ym}',
        'source': SOURCE_ID,
        'title': MIXER_BASE_TITLE,
        'start': start_dt.isoformat(timespec='seconds'),
        'end':   end_dt.isoformat(timespec='seconds'),
        'location': VENUE,
        'price': None,
        'url': 'https://biggayout.org/',
        'status': 'projected',
        'recurrence': 'first-thursday-monthly',
        'links': {},
        'description': DESC_PROJECTED,
        'categories': ['social'],
        'categoriesOverride': None,
    }


def upcoming_months(start_ym, n):
    y, m = start_ym
    for _ in range(n):
        yield (y, m)
        m += 1
        if m > 12:
            m, y = 1, y + 1


def main():
    today = date.today()

    existing = []
    if DATA_FILE.exists():
        existing = json.loads(DATA_FILE.read_text())

    # Normalize legacy mixer ids (url-slug confirmed, '-projected' suffix
    # projections) to the canonical month-keyed scheme. Idempotent — keeps
    # existing_by_id lookups working so short-codes / custom fields survive
    # a projection→confirmed swap.
    for e in existing:
        if is_mixer_event(e) and e.get('start'):
            e['id'] = _canonical_mixer_id(e['start'])

    # Split into mixer rows (replace) and everything else (preserve).
    non_mixer = [e for e in existing if not is_mixer_event(e)]
    old_mixer = [e for e in existing if is_mixer_event(e)]
    print(f'Loaded {len(existing)} BGO events ({len(non_mixer)} non-mixer kept, {len(old_mixer)} mixer to refresh)', file=sys.stderr)

    # Discover + parse current mixer listings.
    urls = discover_mixer_urls()
    print(f'Discovered {len(urls)} candidate mixer URL(s)', file=sys.stderr)

    scraped = []
    for url in urls:
        ei = parse_nas_event(url)
        if not ei:
            print(f'  SKIP no eventInfo: {url}', file=sys.stderr)
            continue
        ev = confirmed_from_event_info(ei, url)
        scraped.append(ev)
        print(f"  OK   {ev['start'][:10]}  {ev['price']:<5}  {url.split('/events/')[1][:60]}", file=sys.stderr)

    # Persist every previously-stored mixer (past or future, confirmed or
    # projected). Nas drops events from listings once they happen — sometimes
    # earlier — but we don't want them to vanish from the calendar.
    all_mixers_by_id = {e['id']: e for e in old_mixer}
    for e in scraped:
        all_mixers_by_id[e['id']] = e  # fresh scrape wins on canonical-id collision

    # Confirmed months considered: any month with a confirmed mixer (stored or
    # fresh). Stops a regenerated projection from downgrading a stored
    # confirmed event whose URL fell out of Nas's listing.
    confirmed_months = {year_month(e['start']) for e in all_mixers_by_id.values()
                        if e.get('status') == 'confirmed'}

    # Project upcoming first-Thursdays without a confirmed mixer. Fresh
    # projections overlay any stored projection at the same canonical id.
    projected = []
    for (y, m) in upcoming_months((today.year, today.month), PROJECTION_MONTHS + 1):
        ym = f'{y:04d}-{m:02d}'
        if ym in confirmed_months:
            continue
        if first_thursday_of_month(y, m) < today:
            continue
        projected.append(projection(y, m))

    for e in projected:
        all_mixers_by_id[e['id']] = e

    # Idempotent merge: any custom fields the user has added on these IDs
    # (e.g. category overrides, short-codes) survive a re-run.
    existing_by_id = {e['id']: e for e in existing}
    new_mixer = [merge_preserving_custom(e, existing_by_id.get(e['id']))
                 for e in all_mixers_by_id.values()]
    merged = {e['id']: e for e in non_mixer + new_mixer}
    out = sorted(merged.values(), key=lambda e: e['start'])

    DATA_FILE.write_text(json.dumps(out, indent=2, ensure_ascii=False) + '\n')

    confirmed_count = sum(1 for e in new_mixer if e.get('status') == 'confirmed')
    projected_count = sum(1 for e in new_mixer if e.get('status') == 'projected')
    print('', file=sys.stderr)
    print(f'Wrote {len(out)} event(s) -> {DATA_FILE.relative_to(ROOT)}', file=sys.stderr)
    print(f'  {len(non_mixer)} non-mixer (untouched), {confirmed_count} confirmed mixer, {projected_count} projected mixer', file=sys.stderr)
    for e in new_mixer:
        when = e['start'][:10]
        tag = 'past' if when < today.isoformat() else e['status']
        print(f"  [{tag:<9}] {when}  {e['title']}", file=sys.stderr)


if __name__ == '__main__':
    main()
