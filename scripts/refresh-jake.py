#!/usr/bin/env python3
"""
Refresh JAKE events (events.jakeldn.com).

JAKE runs on Squarespace, so each event page exposes a Schema.org `Event`
JSON-LD block with name, start/end, and full venue address. The events
index page lists every event (past + future) with a `<time datetime=...>`
near each event link — we use that to identify which are upcoming, then
fetch each upcoming event individually for full details.

No attendee counts (Squarespace doesn't expose them).
Categorisation via title heuristic — JAKE's events are mostly social /
singles mingles / parties / themed nights.

Idempotent: scraped events merge with existing records preserving custom
fields. Past confirmed entries already on disk are kept as history.

Run: python3 scripts/refresh-jake.py
"""

import html as html_mod
import json
import re
import subprocess
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))
from _merge import merge_preserving_custom  # noqa: E402

DATA_FILE = ROOT / 'data' / 'jake.json'

SOURCE_ID = 'jake'
INDEX_URL = 'https://events.jakeldn.com/events'

UA = ('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')

LINKS_BASE = {
    'website': 'https://events.jakeldn.com/events',
    'instagram': 'https://www.instagram.com/letsdojake/',
}

# Every JAKE event is a social by nature (parties, mingles, BBQs, themed
# nights). Categorise() always includes 'social' as the base tag, then layers
# on extra tags from the title.
# Pride-tagging rule: JAKE Pride events are *parties*, not marches, so they
# get both `pride` AND `social`. (TRYBZ's "Pride London" is a march, which
# is why that one is `pride` only — see decisions.md.)
EXTRA_TAG_RULES = [
    ('pride',     ['pride']),
    ('bbq',       ['food']),
    ('barbecue',  ['food']),
]


def curl(url):
    r = subprocess.run(['curl', '-sL', url, '-H', f'User-Agent: {UA}'],
                       capture_output=True, text=True, check=True)
    return r.stdout


def discover_upcoming_events(today_iso):
    """Return [(date_str, full_url)] for events with date >= today.

    JAKE's events index has, for each event, a <time datetime="YYYY-MM-DD">
    element somewhere within the ~3000 chars preceding the event link.
    """
    page = curl(INDEX_URL)
    upcoming = {}
    for m in re.finditer(r'href="([^"]*events/[a-zA-Z0-9-]+)"', page):
        href = m.group(1)
        slug = href.rstrip('/').split('/')[-1]
        # find nearest datetime above this link
        before = page[max(0, m.start() - 3000):m.start()]
        dates = re.findall(r'datetime="(\d{4}-\d{2}-\d{2})"', before)
        if not dates:
            continue
        when = dates[-1]
        if when < today_iso:
            continue
        full_url = href if href.startswith('http') else f'https://events.jakeldn.com{href}'
        # Dedupe by slug; keep earliest date if multiple
        if slug not in upcoming:
            upcoming[slug] = (when, full_url)
    return sorted(upcoming.values())


def parse_event_jsonld(html):
    """Find the Schema.org Event/SocialEvent block."""
    for b in re.findall(r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>',
                        html, re.DOTALL):
        try:
            d = json.loads(b)
        except Exception:
            continue
        if isinstance(d, dict) and d.get('@type') in ('Event', 'SocialEvent'):
            return d
    return None


def og(html, key):
    m = re.search(rf'<meta[^>]+og:{key}"[^>]+content="([^"]*)"', html)
    return html_mod.unescape(m.group(1)) if m else ''


def categorise(title):
    """Always 'social' (base for JAKE) + any extras matched in the title.
    A 'BIG PRIDE BBQ' → ['social', 'pride', 'food']."""
    t = (title or '').lower()
    cats = ['social']
    for needle, extras in EXTRA_TAG_RULES:
        if needle in t:
            for c in extras:
                if c not in cats:
                    cats.append(c)
    return cats


def clean_title(s):
    # Drop the trailing " — JAKE" suffix Squarespace appends
    return re.sub(r'\s*[—\-]\s*JAKE\s*$', '', html_mod.unescape(s or '')).strip()


def format_location(loc):
    """JAKE puts address as a multi-line string. Take just the venue name +
    first line of address for the short location display."""
    if not isinstance(loc, dict):
        return ''
    name = html_mod.unescape((loc.get('name') or '').strip())
    addr = (loc.get('address') or '').strip()
    addr_first = addr.split('\n')[0].strip() if addr else ''
    if name and addr_first:
        return f'{name}, {addr_first}'
    return name or addr_first


def build_event(jsonld, slug, url, html_page):
    title = clean_title(jsonld.get('name', ''))
    start = jsonld.get('startDate')
    end   = jsonld.get('endDate')
    location = format_location(jsonld.get('location'))
    image = og(html_page, 'image')
    description = og(html_page, 'description')

    return {
        'id': f'jake-{slug}',
        'source': SOURCE_ID,
        'title': title,
        'start': start,
        'end': end,
        'location': location,
        'price': None,
        'url': url,
        'image': image or None,
        'status': 'confirmed',
        'links': {'tickets': url, **LINKS_BASE},
        'description': description,
        'soldOut': False,
        'categories': categorise(title),
        'categoriesOverride': None,
    }


def main():
    today = date.today()
    existing = []
    if DATA_FILE.exists():
        existing = json.loads(DATA_FILE.read_text())
    existing_by_id = {e['id']: e for e in existing}

    print(f'GET {INDEX_URL}', file=sys.stderr)
    upcoming = discover_upcoming_events(today.isoformat())
    print(f'  -> {len(upcoming)} upcoming event(s)', file=sys.stderr)

    confirmed = []
    for when, url in upcoming:
        slug = url.rstrip('/').split('/')[-1]
        try:
            page = curl(url)
        except subprocess.CalledProcessError as e:
            print(f'  FAIL {url}: {e}', file=sys.stderr)
            continue
        jsonld = parse_event_jsonld(page)
        if not jsonld:
            print(f'  SKIP no JSON-LD: {url}', file=sys.stderr)
            continue
        rec = build_event(jsonld, slug, url, page)
        # Re-filter against JSON-LD startDate — JAKE's index page sometimes
        # shows future dates for events whose canonical JSON-LD start is
        # actually past (stale/republished listings).
        if (rec.get('start') or '')[:10] < today.isoformat():
            print(f"  SKIP past per JSON-LD ({rec['start'][:10]}): {slug}", file=sys.stderr)
            continue
        confirmed.append(rec)
        print(f"  OK   {rec['start'][:10]}  [{','.join(rec['categories']):<14}]  {rec['title'][:55]}",
              file=sys.stderr)

    merged = [merge_preserving_custom(r, existing_by_id.get(r['id'])) for r in confirmed]
    new_ids = {r['id'] for r in merged}
    past = [e for e in existing
            if e['id'] not in new_ids and e.get('start', '')[:10] < today.isoformat()
            and e.get('status') != 'projected']
    out = sorted(merged + past, key=lambda e: e.get('start') or '')

    DATA_FILE.write_text(json.dumps(out, indent=2, ensure_ascii=False) + '\n')
    print(f'\nWrote {len(out)} event(s) to {DATA_FILE.relative_to(ROOT)}', file=sys.stderr)
    print(f'  {len(confirmed)} confirmed, {len(past)} past kept', file=sys.stderr)


if __name__ == '__main__':
    main()
