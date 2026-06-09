#!/usr/bin/env python3
"""
Refresh events for the LGBTQ+ London Meetup group.

Discovery: scrapes the group's /events/ page for individual event URLs.
Enrichment: fetches each event page and pulls title, time, location, price,
description, attendees, image from Meetup's Apollo state.

Idempotent — re-runs preserve any custom fields on existing event records
(categories, area tags, etc.). Authoritative fields are always refreshed.

Categories assigned by title pattern; the rules are explicit (no regex)
and easy to extend when LGBTQ+ London adds new event series.

Run: python3 scripts/refresh-lgbtq-london.py
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

DATA_FILE = ROOT / 'data' / 'lgbtq-london.json'

SOURCE_ID = 'lgbtq-london'
GROUP_EVENTS_URL = 'https://www.meetup.com/lgbtq-london/events/'

UA = ('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')

# Title-substring → category(s). First match wins. Always check substrings in
# lowercase. Update this when LGBTQ+ London launches a new event series.
CATEGORY_RULES = [
    ('boardgames', ['games']),
    ('videogames', ['games']),
    ('board games', ['games']),
    ('theatre night', ['arts']),
    ('interactive theatre', ['arts']),
    ('queers & beers', ['social']),
    ('pop queens', ['social']),
    ('soho social', ['social']),
    ('summer social', ['outdoors', 'social']),
    ('dog social', ['outdoors', 'social']),
    ('queer travel', ['social']),
]
DEFAULT_CATEGORIES = ['social']


def curl(url):
    r = subprocess.run(['curl', '-sL', url, '-H', f'User-Agent: {UA}'],
                       capture_output=True, text=True, check=True)
    return r.stdout


def discover_event_urls():
    html = curl(GROUP_EVENTS_URL)
    urls = re.findall(r'https://www\.meetup\.com/lgbtq-london/events/\d+', html)
    return sorted(set(urls))


def categorise(title):
    t = (title or '').lower()
    for needle, cats in CATEGORY_RULES:
        if needle in t:
            return list(cats)
    return list(DEFAULT_CATEGORIES)


def slug_from_url(url):
    m = re.search(r'/events/(\d+)', url)
    return f'meetup-{m.group(1)}' if m else url.rstrip('/').split('/')[-1]


def parse_event(url):
    html = curl(url)
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>',
                  html, re.DOTALL)
    if not m:
        return None
    try:
        d = json.loads(m.group(1))
    except Exception:
        return None
    pp = d.get('props', {}).get('pageProps', {})
    ev = pp.get('event') or {}
    apollo = pp.get('__APOLLO_STATE__') or {}
    if not ev:
        return None
    return ev, apollo


def resolve_ref(apollo, value):
    """Apollo cache uses {__ref: 'Type:id'} pointers. Resolve them lazily."""
    if isinstance(value, dict) and '__ref' in value:
        return apollo.get(value['__ref'], {})
    return value


def extract_image_url(ev, apollo):
    """Meetup attaches the event banner via Apollo Event entry's
    `featuredEventPhoto` (or `displayPhoto`) → ref → `PhotoInfo.highResUrl`.
    The top-level `event.image` field is usually null."""
    eid = ev.get('id')
    if not eid:
        return None
    apollo_ev = apollo.get(f'Event:{eid}') or {}
    for fk in ('featuredEventPhoto', 'displayPhoto', 'image'):
        ref = apollo_ev.get(fk)
        if isinstance(ref, dict) and '__ref' in ref:
            ph = apollo.get(ref['__ref']) or {}
            url = ph.get('highResUrl') or ph.get('source')
            if url:
                return url
    return None


def format_price(ev):
    # Meetup events: free flag + fee struct
    if ev.get('isOnline') is True and ev.get('feeSettings') is None:
        return 'Free'
    fee = ev.get('feeSettings') or {}
    amount = fee.get('amount')
    if amount in (None, 0):
        return 'Free'
    currency = fee.get('currency') or 'GBP'
    sym = '£' if currency == 'GBP' else f'{currency} '
    a = amount  # already in main currency unit on Meetup, not pence
    return f'{sym}{a:.2f}' if a != int(a) else f'{sym}{int(a)}'


def build_event(ev, apollo, url):
    title = ev.get('title') or 'Untitled'
    start = ev.get('dateTime')  # ISO with TZ offset
    end = ev.get('endTime')
    desc = (ev.get('description') or '').strip()

    # Venue
    venue = ev.get('venue') or {}
    location = ''
    name = (venue.get('name') or '').strip()
    city = (venue.get('city') or '').strip()
    street = (venue.get('address') or '').strip()
    bits = [name, street, city]
    location = ', '.join([b for b in bits if b])

    # Attendees (going + waitlist)
    going = (ev.get('goingCount') or {}).get('totalCount')
    waitlist = (ev.get('waitingCount') or {}).get('totalCount')

    image_url = extract_image_url(ev, apollo)
    price = format_price(ev)

    rec = {
        'id': slug_from_url(url),
        'source': SOURCE_ID,
        'title': title,
        'start': start,
        'end': end,
        'location': location or 'London',
        'price': price,
        'url': url,
        'image': image_url,
        'status': 'confirmed',
        'links': {'tickets': url},
        'description': desc,
        'soldOut': bool(ev.get('isSoldOut')),
        'categories': categorise(title),
        'categoriesOverride': None,
    }
    if going is not None:
        rec['attendees'] = int(going)
    if waitlist:
        rec['waitlist'] = int(waitlist)
    return rec


def main():
    today = date.today()
    existing = []
    if DATA_FILE.exists():
        existing = json.loads(DATA_FILE.read_text())
    existing_by_id = {e['id']: e for e in existing}

    print(f'GET {GROUP_EVENTS_URL}', file=sys.stderr)
    urls = discover_event_urls()
    print(f'  -> {len(urls)} event URL(s)', file=sys.stderr)

    fresh = []
    for url in urls:
        parsed = parse_event(url)
        if not parsed:
            print(f'  SKIP no event payload: {url}', file=sys.stderr)
            continue
        ev, apollo = parsed
        rec = build_event(ev, apollo, url)
        fresh.append(rec)
        cats = ','.join(rec['categories'])
        when = (rec['start'] or '')[:10]
        att = rec.get('attendees', '-')
        print(f"  OK   {when}  going={att!s:>3}  [{cats:<18}]  {rec['title'][:50]}",
              file=sys.stderr)

    # Idempotent merge: preserve custom fields on existing records
    merged = [merge_preserving_custom(r, existing_by_id.get(r['id'])) for r in fresh]
    # Persist every previously-stored event. Meetup drops events from the
    # upcoming listing once they start (or sometimes earlier), but we keep
    # them around so share links / favourites don't break. Stale rows can
    # always be removed manually.
    new_ids = {r['id'] for r in merged}
    kept = [e for e in existing if e['id'] not in new_ids]
    out = sorted(merged + kept, key=lambda e: e['start'] or '')

    DATA_FILE.write_text(json.dumps(out, indent=2, ensure_ascii=False) + '\n')
    print(f'\nWrote {len(out)} event(s) to {DATA_FILE.relative_to(ROOT)}',
          file=sys.stderr)


if __name__ == '__main__':
    main()
