"""Short-code helpers for shareable event references.

Each event carries a 3-char base62 shortCode that's:
- Assigned once on first appearance
- Stored on the event JSON itself (preserved by _merge.py — non-authoritative)
- Unique across all events in data/*.json (uniqueness checked at assignment time
  by scanning every event JSON)

If you rename an event's `id`, KEEP its `shortCode` field on the record so
old share links continue to resolve.
"""

import json
import secrets
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / 'data'

ALPHABET = (
    'abcdefghijklmnopqrstuvwxyz'
    'ABCDEFGHIJKLMNOPQRSTUVWXYZ'
    '0123456789'
)
CODE_LEN = 3


def collect_existing_codes() -> set:
    """Return the set of shortCodes already assigned across all event JSONs."""
    codes = set()
    for path in DATA_DIR.glob('*.json'):
        if path.name == 'sources.json':
            continue
        try:
            events = json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        if not isinstance(events, list):
            continue
        for ev in events:
            c = ev.get('shortCode')
            if c:
                codes.add(c)
    return codes


def _random_code() -> str:
    return ''.join(secrets.choice(ALPHABET) for _ in range(CODE_LEN))


def pick_unused_code(existing: set) -> str:
    """Pick a fresh 3-char base62 code not in `existing`."""
    for _ in range(1000):
        c = _random_code()
        if c not in existing:
            return c
    raise RuntimeError(
        f"Could not find unused {CODE_LEN}-char code after 1000 tries — "
        f"registry near full ({len(existing)} codes)."
    )


def assign_to_event(ev: dict, existing: set) -> str:
    """Ensure ev has a shortCode. Mutates ev. Returns the code."""
    if ev.get('shortCode'):
        return ev['shortCode']
    c = pick_unused_code(existing)
    ev['shortCode'] = c
    existing.add(c)
    return c
