#!/usr/bin/env python3
"""
Refresh events for the Young LGBTQ+ Professionals Meetup group.

Discovery: reads the group /events/ page Apollo state for ALL upcoming events
(the rendered HTML only shows the first ~6, but Apollo has the full list of
~26 going out a year-plus).

Recurring event: fortnightly drinks at The Yard Bar, Soho, 7pm Tuesdays.
All events get the `social` category.

Idempotent — re-runs preserve custom fields. Authoritative fields are
always refreshed.

Run: python3 scripts/refresh-young-lgbt-pros.py
"""

import json
import re
import subprocess
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))
from _merge import merge_preserving_custom  # noqa: E402

DATA_FILE = ROOT / 'data' / 'young-lgbt-pros.json'

SOURCE_ID = 'young-lgbt-pros'
GROUP_EVENTS_URL = 'https://www.meetup.com/young-lgbt-professionals/events/'
GROUP_HOME = 'https://www.meetup.com/young-lgbt-professionals/'

UA = ('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')

DEFAULT_CATEGORIES = ['social']


def curl(url):
    r = subprocess.run(['curl', '-sL', url, '-H', f'User-Agent: {UA}'],
                       capture_output=True, text=True, check=True)
    return r.stdout


def fetch_apollo(url):
    html = curl(url)
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.DOTALL)
    if not m:
        return None, None
    try:
        d = json.loads(m.group(1))
    except Exception:
        return None, None
    pp = d.get('props', {}).get('pageProps', {})
    return pp, pp.get('__APOLLO_STATE__', {})


def discover_event_urls():
    """Read URLs from the group page Apollo state (more complete than HTML)."""
    _, apollo = fetch_apollo(GROUP_EVENTS_URL)
    if not apollo:
        return []
    urls = []
    for k, v in apollo.items():
        if not k.startswith('Event:'):
            continue
        url = v.get('eventUrl')
        if url:
            urls.append(url)
    return sorted(set(urls))


def slug_from_url(url):
    m = re.search(r'/events/(\d+)', url)
    return f'meetup-{m.group(1)}' if m else url.rstrip('/').split('/')[-1]


def extract_image_url(ev_id, apollo):
    """Banner ref lives at Event.featuredEventPhoto → PhotoInfo.highResUrl."""
    apollo_ev = apollo.get(f'Event:{ev_id}') or {}
    for fk in ('featuredEventPhoto', 'displayPhoto', 'image'):
        ref = apollo_ev.get(fk)
        if isinstance(ref, dict) and '__ref' in ref:
            ph = apollo.get(ref['__ref']) or {}
            url = ph.get('highResUrl') or ph.get('source')
            if url:
                return url
    return None


def format_price(ev):
    fee = ev.get('feeSettings') or {}
    amount = fee.get('amount')
    if amount in (None, 0):
        return 'Free'
    currency = fee.get('currency') or 'GBP'
    sym = '£' if currency == 'GBP' else f'{currency} '
    return f'{sym}{amount:.2f}' if amount != int(amount) else f'{sym}{int(amount)}'


def build_event(ev, apollo, url):
    title = ev.get('title') or 'Untitled'
    start = ev.get('dateTime')
    end = ev.get('endTime')
    desc = (ev.get('description') or '').strip()

    venue = ev.get('venue') or {}
    name = (venue.get('name') or '').strip()
    city = (venue.get('city') or '').strip()
    street = (venue.get('address') or '').strip()
    location = ', '.join([b for b in [name, street, city] if b]) or 'London'

    going = (ev.get('goingCount') or {}).get('totalCount')
    waitlist = (ev.get('waitingCount') or {}).get('totalCount')

    image_url = extract_image_url(ev.get('id'), apollo)
    price = format_price(ev)

    rec = {
        'id': slug_from_url(url),
        'source': SOURCE_ID,
        'title': title,
        'start': start,
        'end': end,
        'location': location,
        'price': price,
        'url': url,
        'image': image_url,
        'status': 'confirmed',
        'links': {'tickets': url},
        'description': desc,
        'soldOut': bool(ev.get('isSoldOut')),
        'categories': list(DEFAULT_CATEGORIES),
        'categoriesOverride': None,
    }
    if going is not None:
        rec['attendees'] = int(going)
    if waitlist:
        rec['waitlist'] = int(waitlist)
    return rec


def parse_individual_event(url):
    pp, apollo = fetch_apollo(url)
    if not pp:
        return None
    ev = pp.get('event') or {}
    if not ev:
        return None
    return ev, apollo


def main():
    today = date.today()
    existing = []
    if DATA_FILE.exists():
        existing = json.loads(DATA_FILE.read_text())
    existing_by_id = {e['id']: e for e in existing}

    print(f'GET {GROUP_EVENTS_URL}', file=sys.stderr)
    urls = discover_event_urls()
    print(f'  -> {len(urls)} event URL(s) discovered via Apollo', file=sys.stderr)

    fresh = []
    for url in urls:
        parsed = parse_individual_event(url)
        if not parsed:
            print(f'  SKIP no event payload: {url}', file=sys.stderr)
            continue
        ev, apollo = parsed
        rec = build_event(ev, apollo, url)
        fresh.append(rec)
        when = (rec['start'] or '')[:10]
        att = rec.get('attendees', '-')
        print(f"  OK   {when}  going={att!s:>3}  {rec['title'][:55]}", file=sys.stderr)

    # Idempotent merge — preserve custom fields the user has added
    merged = [merge_preserving_custom(r, existing_by_id.get(r['id'])) for r in fresh]
    # Persist every previously-stored event. Meetup drops events from the
    # upcoming listing once they start (or sometimes earlier); we keep them
    # so share links / favourites don't break. Stale rows removed manually.
    new_ids = {r['id'] for r in merged}
    kept = [e for e in existing if e['id'] not in new_ids]
    out = sorted(merged + kept, key=lambda e: e['start'] or '')

    DATA_FILE.write_text(json.dumps(out, indent=2, ensure_ascii=False) + '\n')
    print(f'\nWrote {len(out)} event(s) to {DATA_FILE.relative_to(ROOT)}',
          file=sys.stderr)


if __name__ == '__main__':
    main()
