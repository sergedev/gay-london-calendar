#!/usr/bin/env python3
"""
Enrich every Nas.com event in trybz.json + big-gay-out.json with the
latest source-controlled fields: image, price (max active tier),
soldOut, attendees, attendeeLimit.

Idempotent. Custom fields on the on-disk record (category overrides,
area tags, notes, anything we add later) are preserved on every run —
only the authoritative fields managed by this script are overwritten.

Supersedes the older `enrich-nas-images.py` and `fix-nas-prices.py`
scripts (which only handled subsets of these fields).

Disclaimer (Nas tiered pricing — TRYBZ uses this for some mixers, e.g. their birthday): on tier-released
events the `attendeeLimit` is the *current tier's* threshold, not the
event's total cap. When the tier fills, the organiser opens a new tier and
both the price and attendeeLimit step up — so attendance == limit only
means sold out *if no further tier is released*.

Run: python3 scripts/enrich-nas-events.py
"""

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))
from _merge import merge_preserving_custom  # noqa: E402

DATA = [ROOT / 'data' / 'trybz.json',
        ROOT / 'data' / 'big-gay-out.json']

UA = ('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')


def curl(url):
    r = subprocess.run(['curl', '-sL', url, '-H', f'User-Agent: {UA}'],
                       capture_output=True, text=True, check=True)
    return r.stdout


def fetch_event_info(url):
    html = curl(url)
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.DOTALL)
    if not m:
        return None
    try:
        d = json.loads(m.group(1))
    except Exception:
        return None
    return (d.get('props', {}).get('pageProps', {})
              .get('pageInfo', {}).get('templateData', {}).get('eventInfo'))


def _format_gbp(pence):
    g = pence / 100
    return f'£{g:.2f}' if g != int(g) else f'£{int(g)}'


def extract_price(ei):
    """Public/non-member price: max active tier; fall back to top-level amount."""
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


def build_enrichment(ei):
    """Return a dict of just the fields this script controls."""
    # nas.com's `isSoldOut` only flips true when the host explicitly closes
    # registration. Events that fill organically (last RSVP takes the final
    # seat) keep `isSoldOut: false` while the rendered page shows "Sold out"
    # — the frontend infers it from attendance >= capacity. Mirror that here.
    going = ei.get('goingAttendees')
    if going is None:
        going = ei.get('attendees')
    limit = ei.get('attendeeLimit') or 0
    capacity_full = (
        bool(ei.get('isCapacitySet'))
        and limit > 0
        and going is not None
        and int(going) >= int(limit)
    )
    enrich = {
        'price': extract_price(ei),
        'soldOut': bool(ei.get('isSoldOut')) or capacity_full,
    }
    if ei.get('bannerImg'):
        enrich['image'] = ei['bannerImg']
    # attendees / capacity — respect Nas's hideAttendeesCount opt-out
    if not ei.get('hideAttendeesCount'):
        going = ei.get('goingAttendees')
        if going is None:
            going = ei.get('attendees')
        if going is not None:
            enrich['attendees'] = int(going)
        if ei.get('isCapacitySet') and ei.get('attendeeLimit'):
            enrich['attendeeLimit'] = int(ei['attendeeLimit'])
    return enrich


def process(path):
    data = json.loads(path.read_text())
    changes = 0
    for i, ev in enumerate(data):
        if ev.get('status') == 'projected':
            continue
        url = ev.get('url') or ''
        if '/events/' not in url:
            continue
        ei = fetch_event_info(url)
        if not ei:
            print(f'  SKIP no eventInfo: {ev["id"]}', file=sys.stderr)
            continue
        enrich = build_enrichment(ei)
        merged = merge_preserving_custom(enrich, ev)
        # Detect actual changes for the log
        diffs = [k for k in enrich if ev.get(k) != enrich[k]]
        if diffs:
            changes += 1
            data[i] = merged
            print(f'  {ev["id"][:55]:<55}  {{{", ".join(diffs)}}}', file=sys.stderr)
        else:
            # still write the merged record in case of new fields being added
            data[i] = merged
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + '\n')
    print(f'{path.name}: {changes} event(s) had updates', file=sys.stderr)
    return changes


def main():
    total = 0
    for p in DATA:
        total += process(p)
    print(f'\nTotal events with updated fields: {total}', file=sys.stderr)


if __name__ == '__main__':
    main()
