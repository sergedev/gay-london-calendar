#!/usr/bin/env python3
"""One-off: assign shortCode to every event JSON in data/ that doesn't have one.

Idempotent — re-running is a no-op if every event already has a code.

Run: python3 scripts/backfill-short-codes.py
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _short_codes import collect_existing_codes, assign_to_event

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / 'data'


def main() -> int:
    json_files = sorted(p for p in DATA_DIR.glob('*.json') if p.name != 'sources.json')
    existing = collect_existing_codes()
    total_events = 0
    new_codes = 0
    files_changed = 0

    for path in json_files:
        try:
            events = json.loads(path.read_text())
        except (json.JSONDecodeError, OSError) as e:
            print(f"skip {path.name}: {e}", file=sys.stderr)
            continue
        if not isinstance(events, list):
            continue

        changed = False
        for ev in events:
            total_events += 1
            if not ev.get('shortCode'):
                assign_to_event(ev, existing)
                new_codes += 1
                changed = True

        if changed:
            path.write_text(json.dumps(events, indent=2, ensure_ascii=False) + '\n')
            files_changed += 1
            with_code = sum(1 for e in events if e.get('shortCode'))
            print(f"  {path.name}: {with_code}/{len(events)} have codes", file=sys.stderr)

    print(
        f"\nProcessed {total_events} events across {len(json_files)} files. "
        f"Assigned {new_codes} new code(s). {files_changed} file(s) changed.",
        file=sys.stderr,
    )
    return 0


if __name__ == '__main__':
    sys.exit(main())
