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

SOURCE_WEBSITE = 'https://www.villagedrinks.com/'
LOCATION_NOTE = 'Location revealed closer to the day'  # drawer-only fallback
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
        o = offers[0]
        # Village Drinks runs tiered Eventbrite pricing (early bird → student →
        # standard → last chance) that shifts through the month. We always show
        # the top of the AggregateOffer range (highPrice) so the figure on the
        # calendar reflects the dearest active tier; fall back to low/price.
        amount = o.get('highPrice') or o.get('lowPrice') or o.get('price')
        cur = o.get('priceCurrency', 'GBP')
        if amount is not None:
            sym = '£' if cur == 'GBP' else f'{cur} '
            try:
                f = float(amount)
                price = f'{sym}{f:.2f}' if f != int(f) else f'{sym}{int(f)}'
            except Exception:
                price = f'{sym}{amount}'
        avail = (o.get('availability') or '').lower()
        sold_out = 'soldout' in avail or 'outofstock' in avail

    location = None
    place = data.get('location') or {}
    if isinstance(place, dict):
        name = (place.get('name') or '').strip()
        if name and name.lower() not in ('tbd', 'tba', 'tbc'):
            location = name

    return {
        'id': _canonical_id(start),
        'source': SOURCE_ID,
        'title': title or 'Village Drinks',
        'start': start,
        'end': end,
        'location': location,
        'locationNote': None if location else LOCATION_NOTE,
        'price': price,
        'url': url,
        # NOTE: image is intentionally omitted. Banner images are set by hand
        # (the Eventbrite JSON-LD image is often a poor crop), so we don't emit
        # 'image' here — merge_preserving_custom then keeps the on-disk value.
        'status': 'confirmed',
        'recurrence': 'last-thursday-monthly',
        'links': {'tickets': url},
        'description': DESC_CONFIRMED,
        'soldOut': sold_out,
        'categories': ['social'],
        'categoriesOverride': None,
    }


def _canonical_id(start_iso):
    """Stable month-keyed id for the Village Drinks monthly series. Projected
    and confirmed entries in a given month share this id so a confirmed scrape
    overwrites the projection in place — preserving short-codes and share links."""
    return f'village-drinks-{(start_iso or "")[:7]}'


def projection(year, month):
    d = last_thursday_of_month(year, month)
    iso = d.isoformat()
    ym = f'{year:04d}-{month:02d}'
    return {
        'id': f'village-drinks-{ym}',
        'source': SOURCE_ID,
        'title': 'Village Drinks',
        'start': f'{iso}T{PROJECTED_START_TIME}',
        'end': f'{iso}T{PROJECTED_END_TIME}',
        'location': None,
        'locationNote': LOCATION_NOTE,
        'price': None,
        'url': SOURCE_WEBSITE,
        'status': 'projected',
        'recurrence': 'last-thursday-monthly',
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

    # Normalize legacy ids (eventbrite-based confirmed, '-projected' suffix
    # projections) to the canonical month-keyed scheme. Idempotent — keeps
    # existing_by_id lookups working so short-codes / custom fields survive
    # a projection→confirmed swap.
    for e in existing:
        if e.get('source') == SOURCE_ID and e.get('start'):
            e['id'] = _canonical_id(e['start'])

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

    # Persist every previously-stored event. Eventbrite drops events from
    # listings once they happen — sometimes earlier — but we don't want
    # them to vanish from the calendar.
    all_by_id = {e['id']: e for e in existing}
    for e in confirmed:
        all_by_id[e['id']] = e  # fresh scrape wins on canonical-id collision

    # Confirmed months: any month with a confirmed event (stored or fresh).
    # Stops a regenerated projection from downgrading a stored confirmed
    # event whose Eventbrite listing has dropped.
    confirmed_months = {year_month(e['start']) for e in all_by_id.values()
                        if e.get('status') == 'confirmed'}

    projected = []
    for (y, m) in upcoming_months((today.year, today.month), PROJECTION_MONTHS + 1):
        ym = f'{y:04d}-{m:02d}'
        if ym in confirmed_months:
            continue
        if last_thursday_of_month(y, m) < today:
            continue
        projected.append(projection(y, m))

    for e in projected:
        all_by_id[e['id']] = e

    # Idempotent merge: preserve any custom fields the user has added
    # (e.g. category overrides, area tags, notes, short-codes) across re-runs.
    existing_by_id = {e['id']: e for e in existing}
    merged_list = [merge_preserving_custom(e, existing_by_id.get(e['id']))
                   for e in all_by_id.values()]
    out = sorted(merged_list, key=lambda e: e['start'] or '')

    DATA_FILE.write_text(json.dumps(out, indent=2, ensure_ascii=False) + '\n')

    print('', file=sys.stderr)
    print(f"Wrote {len(out)} event(s) -> {DATA_FILE.relative_to(ROOT)}", file=sys.stderr)
    confirmed_count = sum(1 for e in out if e.get('status') == 'confirmed')
    projected_count = sum(1 for e in out if e.get('status') == 'projected')
    print(f"  {confirmed_count} confirmed, {projected_count} projected (incl. previously-stored)", file=sys.stderr)
    for e in out:
        when = e['start'][:10]
        if when < today.isoformat():
            tag = 'past'
        else:
            tag = e['status']
        print(f"  [{tag:<9}] {when}  {e['title']}", file=sys.stderr)


if __name__ == '__main__':
    main()
