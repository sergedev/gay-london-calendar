#!/usr/bin/env python3
"""
Refresh Elephant Social London monthly mixer events.

PROJECTION-ONLY. Elephant Social doesn't list events on a structured platform
— the mixer is announced ad-hoc on Instagram a few days/weeks ahead. So this
script just generates `last-friday-monthly` placeholders for the projection
window. Any custom edits on a projection (e.g. confirming a specific venue
or marking it as actually happening) survive a re-run via the merge helper.

When Elephant Social eventually posts a real ticket link or confirmed
details, the right move is to edit the corresponding projected entry by
hand — id stays the same (`elephant-social-YYYY-MM-projected`).

Run: python3 scripts/refresh-elephant-social.py
"""

import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))
from _merge import merge_preserving_custom  # noqa: E402

DATA_FILE = ROOT / 'data' / 'elephant-social-london.json'

SOURCE_ID = 'elephant-social-london'
PROJECTION_MONTHS = 4

LONDON = ZoneInfo('Europe/London')

VENUE = "Betty & Joan's, Elephant & Castle"
TITLE = 'Elephant Social Monthly Mixer'
PROJECTED_START_HM = (20, 0)   # 8:00 PM London local
PROJECTED_END_HM   = (23, 30)  # ~11:30 PM London local — rough guess

LINKS_BASE = {
    'website': 'https://www.instagram.com/elephant_social_london',
    'instagram': 'https://www.instagram.com/elephant_social_london',
}
DESC_PROJECTED = (
    "Projected based on the usual last-Friday-of-month cadence. Elephant "
    "Social announces the mixer ad-hoc on Instagram a few days ahead — "
    "check there closer to the date for venue confirmation."
)


def last_friday_of_month(year, month):
    if month == 12:
        first_next = date(year + 1, 1, 1)
    else:
        first_next = date(year, month + 1, 1)
    d = first_next - timedelta(days=1)
    while d.weekday() != 4:  # Friday
        d -= timedelta(days=1)
    return d


def upcoming_months(start_ym, n):
    y, m = start_ym
    for _ in range(n):
        yield (y, m)
        m += 1
        if m > 12:
            m, y = 1, y + 1


def projection(year, month):
    d = last_friday_of_month(year, month)
    sh, sm = PROJECTED_START_HM
    eh, em = PROJECTED_END_HM
    start_dt = datetime(d.year, d.month, d.day, sh, sm, tzinfo=LONDON)
    end_dt   = datetime(d.year, d.month, d.day, eh, em, tzinfo=LONDON)
    ym = f'{year:04d}-{month:02d}'
    return {
        'id': f'elephant-social-{ym}-projected',
        'source': SOURCE_ID,
        'title': TITLE,
        'start': start_dt.isoformat(timespec='seconds'),
        'end':   end_dt.isoformat(timespec='seconds'),
        'location': VENUE,
        'price': None,
        'url': LINKS_BASE['instagram'],
        'image': None,
        'status': 'projected',
        'recurrence': 'last-friday-monthly',
        'links': dict(LINKS_BASE),
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
    existing_by_id = {e['id']: e for e in existing}

    projected = []
    for (y, m) in upcoming_months((today.year, today.month), PROJECTION_MONTHS + 1):
        if last_friday_of_month(y, m) < today:
            continue
        projected.append(projection(y, m))

    # Idempotent merge — preserve custom fields on existing records
    merged = [merge_preserving_custom(p, existing_by_id.get(p['id']))
              for p in projected]

    # Preserve any past entries that aren't being regenerated (history)
    new_ids = {r['id'] for r in merged}
    past = [e for e in existing
            if e['id'] not in new_ids and e.get('start', '')[:10] < today.isoformat()]
    out = sorted(merged + past, key=lambda e: e['start'])

    DATA_FILE.write_text(json.dumps(out, indent=2, ensure_ascii=False) + '\n')
    print(f'Wrote {len(out)} event(s) to {DATA_FILE.relative_to(ROOT)}', file=sys.stderr)
    for e in out:
        when = e['start'][:10]
        tag = 'past' if when < today.isoformat() else e['status']
        print(f"  [{tag:<9}] {when}  {e['title']}", file=sys.stderr)


if __name__ == '__main__':
    main()
