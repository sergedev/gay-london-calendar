#!/usr/bin/env python3
"""
Refresh Village Drinks events.

Scrapes the Eventbrite organizer page for confirmed listings, reconciles them
with projected placeholders (last Thursday of each month), and writes a fresh
data/village-drinks.json.

Matching is keyed by (source, year-month). A confirmed event in month M
replaces any projected entry for M, regardless of weekday — so a Village Drinks
that drops on a Wed instead of Thu naturally overrides the projection. Months
with no confirmed listing inside the projection window get a fresh placeholder.

Run: python3 scripts/refresh-village-drinks.py
"""

import json
import re
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))
from _merge import merge_preserving_custom  # noqa: E402

DATA_FILE = ROOT / 'data' / 'village-drinks.json'

SOURCE_ID = 'village-drinks'
ORGANIZER_URL = 'https://www.eventbrite.co.uk/o/13957159973'
PROJECTION_MONTHS = 4  # months ahead to project (beyond any confirmed listings)

UA = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'

LINKS_BASE = {
    'website': 'https://www.villagedrinks.com/',
    'instagram': 'https://www.instagram.com/villagedrinksldn/',
}
DEFAULT_LOCATION = 'Location revealed close to the event'
PROJECTED_START_TIME = '18:30:00+01:00'  # matches the historic Village Drinks slot
PROJECTED_END_TIME = '23:30:00+01:00'
DESC_CONFIRMED = 'Meaningful connections. Hundreds of like-minded guys, in one special venue.'
DESC_PROJECTED = (
    "Projected based on the usual last-Thursday-of-month cadence. "
    "Tickets typically released a few days after the prior month's event."
)


def curl(url):
    r = subprocess.run(
        ['curl', '-sL', url, '-H', f'User-Agent: {UA}'],
        capture_output=True, text=True, check=True,
    )
    return r.stdout


def last_thursday_of_month(year, month):
    if month == 12:
        first_next = date(year + 1, 1, 1)
    else:
        first_next = date(year, month + 1, 1)
    d = first_next - timedelta(days=1)
    while d.weekday() != 3:  # Thursday
        d -= timedelta(days=1)
    return d


def year_month(date_str):
    return date_str[:7]


def scrape_event_urls():
    html = curl(ORGANIZER_URL)
    urls = sorted(set(re.findall(r'https://www\.eventbrite\.co\.uk/e/[a-zA-Z0-9-]+', html)))
    return [u for u in urls if re.search(r'-tickets-\d+$', u)]


def parse_event_jsonld(url):
    html = curl(url)
    for block in re.findall(
        r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>',
        html, re.DOTALL,
    ):
        try:
            data = json.loads(block)
        except Exception:
            continue
        if isinstance(data, dict) and data.get('@type') in ('SocialEvent', 'Event'):
            return data
    return None


def _first_image(v):
    """JSON-LD image can be a string, list, or ImageObject. Return a URL or None."""
    if isinstance(v, str):
        return v
    if isinstance(v, list) and v:
        return _first_image(v[0])
    if isinstance(v, dict):
        return v.get('url')
    return None


def confirmed_from_jsonld(data, url):
    title = data.get('name', 'Village Drinks')
    # Strip the long subtitle Village Drinks attaches in Eventbrite titles
    title = re.sub(r':\s*a unique evening.*$', '', title, flags=re.IGNORECASE).strip()

    start = data['startDate']
    end = data.get('endDate', '')

    price = None
    sold_out = False
    offers = data.get('offers')
    if isinstance(offers, list) and offers:
        low = offers[0].get('lowPrice')
        cur = offers[0].get('priceCurrency', 'GBP')
        if low is not None:
            sym = '£' if cur == 'GBP' else f'{cur} '
            try:
                f = float(low)
                price = f'{sym}{f:.2f}' if f != int(f) else f'{sym}{int(f)}'
            except Exception:
                price = f'{sym}{low}'
        elif offers[0].get('price'):
            price = f"£{offers[0]['price']}"
        avail = (offers[0].get('availability') or '').lower()
        sold_out = 'soldout' in avail or 'outofstock' in avail

    location = DEFAULT_LOCATION
    place = data.get('location') or {}
    if isinstance(place, dict):
        name = (place.get('name') or '').strip()
        if name and name.lower() not in ('tbd', 'tba', 'tbc'):
            location = name

    ticket_id_match = re.search(r'-tickets-(\d+)$', url)
    ticket_id = ticket_id_match.group(1) if ticket_id_match else year_month(start).replace('-', '')

    return {
        'id': f'village-drinks-eb-{ticket_id}',
        'source': SOURCE_ID,
        'title': title or 'Village Drinks',
        'start': start,
        'end': end,
        'location': location,
        'price': price,
        'url': url,
        'image': _first_image(data.get('image')),
        'status': 'confirmed',
        'recurrence': 'last-thursday-monthly',
        'links': {'tickets': url, **LINKS_BASE},
        'description': DESC_CONFIRMED,
        'soldOut': sold_out,
        'categories': ['social'],
        'categoriesOverride': None,
    }


def projection(year, month):
    d = last_thursday_of_month(year, month)
    iso = d.isoformat()
    ym = f'{year:04d}-{month:02d}'
    return {
        'id': f'village-drinks-{ym}-projected',
        'source': SOURCE_ID,
        'title': 'Village Drinks',
        'start': f'{iso}T{PROJECTED_START_TIME}',
        'end': f'{iso}T{PROJECTED_END_TIME}',
        'location': DEFAULT_LOCATION,
        'price': None,
        'url': LINKS_BASE['website'],
        'status': 'projected',
        'recurrence': 'last-thursday-monthly',
        'links': dict(LINKS_BASE),
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
    past_existing = [e for e in existing if e.get('start', '')[:10] < today.isoformat()
                     and e.get('status') != 'projected']

    print(f'GET {ORGANIZER_URL}', file=sys.stderr)
    urls = scrape_event_urls()
    print(f'  -> {len(urls)} event URL(s)', file=sys.stderr)

    confirmed = []
    for url in urls:
        data = parse_event_jsonld(url)
        if not data:
            print(f'  SKIP no JSON-LD: {url}', file=sys.stderr)
            continue
        ev = confirmed_from_jsonld(data, url)
        confirmed.append(ev)
        slug = url.split('/e/', 1)[1][:60]
        print(f"  OK   {ev['start'][:10]}  {ev['price']!s:<8}  {slug}", file=sys.stderr)

    confirmed_months = {year_month(e['start']) for e in confirmed}

    projected = []
    for (y, m) in upcoming_months((today.year, today.month), PROJECTION_MONTHS + 1):
        ym = f'{y:04d}-{m:02d}'
        if ym in confirmed_months:
            continue
        if last_thursday_of_month(y, m) < today:
            continue
        projected.append(projection(y, m))

    # Idempotent merge: preserve any custom fields the user has added
    # (e.g. category overrides, area tags, notes) across re-runs.
    existing_by_id = {e['id']: e for e in existing}
    confirmed_merged = [merge_preserving_custom(e, existing_by_id.get(e['id']))
                        for e in confirmed]
    projected_merged = [merge_preserving_custom(e, existing_by_id.get(e['id']))
                        for e in projected]
    merged = {e['id']: e for e in past_existing + confirmed_merged + projected_merged}
    out = sorted(merged.values(), key=lambda e: e['start'])

    DATA_FILE.write_text(json.dumps(out, indent=2, ensure_ascii=False) + '\n')

    print('', file=sys.stderr)
    print(f"Wrote {len(out)} event(s) -> {DATA_FILE.relative_to(ROOT)}", file=sys.stderr)
    print(f"  {len(past_existing)} past, {len(confirmed)} confirmed, {len(projected)} projected", file=sys.stderr)
    for e in out:
        when = e['start'][:10]
        if when < today.isoformat():
            tag = 'past'
        else:
            tag = e['status']
        print(f"  [{tag:<9}] {when}  {e['title']}", file=sys.stderr)


if __name__ == '__main__':
    main()
