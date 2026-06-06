#!/usr/bin/env python3
"""
Refresh Gaymers iNC. monthly meet-up events.

Gaymers iNC. runs several event types — main monthly meet-up, board games
nights, geek quizzes, RPG Tavern takeovers, etc. We only track the **main
monthly meet-up** here (3rd Wednesday at TOSY / The Old School Yard).
The site uses the WordPress Tribe Events Calendar plugin which exposes a
clean Schema.org Event JSON-LD list.

Filter rule: keep events whose title contains "Meet-Up" or "Meet Up".
Other events (Board Games / Geek Quiz / RPG Tavern) are dropped — they
can be added as separate scrapes later if needed.

Recurrence: 3rd Wednesday of each month, 6pm–11:30pm London local.
Projections fill the window where no confirmed scraped event exists.

Idempotent. No attendee counts (WordPress / Tribe doesn't expose them).

Run: python3 scripts/refresh-gaymers-inc.py
"""

import html as html_mod
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

DATA_FILE = ROOT / 'data' / 'gaymers-inc.json'

SOURCE_ID = 'gaymers-inc'
EVENTS_URL = 'https://gaymersinc.com/events/'
PROJECTION_MONTHS = 6  # project ~half a year ahead

UA = ('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')

LONDON = ZoneInfo('Europe/London')

VENUE_DEFAULT = 'The Old School Yard, 109-111 Long Ln, London'
PROJECTED_START_HM = (18, 0)
PROJECTED_END_HM   = (23, 30)
LINKS_BASE = {
    'website': 'https://gaymersinc.com/events/',
    'instagram': 'https://www.instagram.com/gaymersinc/',
}
DESC_PROJECTED = (
    "Projected based on the usual 3rd-Wednesday-of-month cadence at TOSY "
    "(The Old School Yard). Specific theme/tournament announced closer to "
    "the date on the Gaymers iNC. website."
)


def curl(url):
    r = subprocess.run(['curl', '-sL', url, '-H', f'User-Agent: {UA}'],
                       capture_output=True, text=True, check=True)
    return r.stdout


def third_wednesday(year, month):
    d = date(year, month, 1)
    while d.weekday() != 2:  # Wednesday
        d += timedelta(days=1)
    return d + timedelta(days=14)


def upcoming_months(start_ym, n):
    y, m = start_ym
    for _ in range(n):
        yield (y, m)
        m += 1
        if m > 12:
            m, y = 1, y + 1


def year_month(date_str):
    return (date_str or '')[:7]


def format_price(offer):
    if not isinstance(offer, dict):
        return None
    price_str = (offer.get('price') or '').strip()
    if not price_str or price_str == '0':
        return 'Free'
    # Handle ranges like "15 – 18" → take max
    nums = re.findall(r'\d+(?:\.\d+)?', price_str)
    if not nums:
        return None
    top = max(float(n) for n in nums)
    return 'Free' if top == 0 else (f'£{top:.2f}' if top != int(top) else f'£{int(top)}')


def format_location(loc):
    if not isinstance(loc, dict):
        return None
    name = html_mod.unescape((loc.get('name') or '').strip())
    addr = loc.get('address')
    addr_str = ''
    if isinstance(addr, dict):
        addr_str = addr.get('streetAddress') or ''
        if addr.get('addressLocality'):
            addr_str = f'{addr_str}, {addr["addressLocality"]}'.strip(', ')
    elif isinstance(addr, str):
        addr_str = addr.split('\n')[0].strip()
    if name and addr_str:
        return f'{name}, {addr_str}'
    return name or addr_str


def categorise(title):
    """Default games. Add 'pride' if the title explicitly says so."""
    t = (title or '').lower()
    cats = ['games']
    if 'pride' in t:
        cats.append('pride')
    return cats


def is_main_meetup(name):
    """Filter to only the main monthly meet-up — drops board games, geek
    quizzes, RPG Tavern takeovers, etc."""
    t = (name or '').lower()
    return 'meet-up' in t or 'meet up' in t or 'meetup' in t


def clean_title(s):
    return html_mod.unescape((s or '').strip())


def slug_from_url(url):
    s = url.rstrip('/').split('/')[-1]
    return f'gaymers-inc-{s}' if s else None


def confirmed_record(item):
    title = clean_title(item.get('name'))
    url = item.get('url') or ''
    return {
        'id': slug_from_url(url) or f'gaymers-inc-{year_month(item.get("startDate",""))}',
        'source': SOURCE_ID,
        'title': title,
        'start': item.get('startDate'),
        'end': item.get('endDate'),
        'location': format_location(item.get('location')) or VENUE_DEFAULT,
        'price': format_price(item.get('offers')),
        'url': url,
        'image': item.get('image') if isinstance(item.get('image'), str) else None,
        'status': 'confirmed',
        'recurrence': 'third-wednesday-monthly',
        'links': {'tickets': url, **LINKS_BASE},
        'description': html_mod.unescape((item.get('description') or '').strip()),
        'soldOut': (item.get('offers', {}) or {}).get('availability') == 'http://schema.org/SoldOut',
        'categories': categorise(title),
        'categoriesOverride': None,
    }


def projection(year, month):
    d = third_wednesday(year, month)
    sh, sm = PROJECTED_START_HM
    eh, em = PROJECTED_END_HM
    start_dt = datetime(d.year, d.month, d.day, sh, sm, tzinfo=LONDON)
    end_dt   = datetime(d.year, d.month, d.day, eh, em, tzinfo=LONDON)
    ym = f'{year:04d}-{month:02d}'
    return {
        'id': f'gaymers-inc-{ym}-projected',
        'source': SOURCE_ID,
        'title': 'Gaymers iNC. Monthly Meet-Up',
        'start': start_dt.isoformat(timespec='seconds'),
        'end':   end_dt.isoformat(timespec='seconds'),
        'location': VENUE_DEFAULT,
        'price': None,
        'url': LINKS_BASE['website'],
        'image': None,
        'status': 'projected',
        'recurrence': 'third-wednesday-monthly',
        'links': dict(LINKS_BASE),
        'description': DESC_PROJECTED,
        'soldOut': False,
        'categories': ['games'],
        'categoriesOverride': None,
    }


def parse_events(html):
    blocks = re.findall(r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>',
                        html, re.DOTALL)
    items = []
    for b in blocks:
        try:
            d = json.loads(b)
        except Exception:
            continue
        if isinstance(d, list):
            items.extend(d)
        else:
            items.append(d)
    return [i for i in items if isinstance(i, dict) and i.get('@type') in ('Event', 'SocialEvent')]


def main():
    today = date.today()
    existing = []
    if DATA_FILE.exists():
        existing = json.loads(DATA_FILE.read_text())
    existing_by_id = {e['id']: e for e in existing}

    print(f'GET {EVENTS_URL}', file=sys.stderr)
    page = curl(EVENTS_URL)
    items = parse_events(page)
    print(f'  -> {len(items)} event(s) in JSON-LD', file=sys.stderr)

    confirmed = []
    for item in items:
        name = clean_title(item.get('name'))
        if not is_main_meetup(name):
            print(f"  SKIP non-meetup: {name[:55]}", file=sys.stderr)
            continue
        rec = confirmed_record(item)
        if (rec.get('start') or '')[:10] < today.isoformat():
            print(f"  SKIP past: {rec['start'][:10]}  {name[:55]}", file=sys.stderr)
            continue
        confirmed.append(rec)
        print(f"  OK   {rec['start'][:10]}  [{','.join(rec['categories'])}]  {name[:55]}",
              file=sys.stderr)

    confirmed_months = {year_month(e['start']) for e in confirmed}

    projected = []
    for (y, m) in upcoming_months((today.year, today.month), PROJECTION_MONTHS + 1):
        ym = f'{y:04d}-{m:02d}'
        if ym in confirmed_months:
            continue
        if third_wednesday(y, m) < today:
            continue
        projected.append(projection(y, m))

    fresh = confirmed + projected
    merged = [merge_preserving_custom(r, existing_by_id.get(r['id'])) for r in fresh]
    new_ids = {r['id'] for r in merged}
    past = [e for e in existing
            if e['id'] not in new_ids and e.get('start', '')[:10] < today.isoformat()
            and e.get('status') != 'projected']
    out = sorted(merged + past, key=lambda e: e.get('start') or '')

    DATA_FILE.write_text(json.dumps(out, indent=2, ensure_ascii=False) + '\n')
    print(f'\nWrote {len(out)} event(s) to {DATA_FILE.relative_to(ROOT)}', file=sys.stderr)
    for e in out:
        when = (e.get('start') or '')[:10]
        tag = 'past' if when < today.isoformat() else e['status']
        print(f"  [{tag:<9}] {when}  {e['title'][:55]}", file=sys.stderr)


if __name__ == '__main__':
    main()
