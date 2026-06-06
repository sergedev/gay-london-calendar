#!/usr/bin/env python3
"""
Run every refresh + enrich script in sequence.

Discovers `scripts/refresh-*.py` and `scripts/enrich-*.py`, runs each one,
and prints a pass/fail summary at the end.

A failing script does NOT abort the run — every other script still runs.
The exit code is non-zero if anything failed, so it's safe to chain in CI
or cron later.

Order: all refresh-* scripts first, then enrich-* scripts (enrichment
runs on the freshest data).

Run: python3 scripts/refresh-all.py
"""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = ROOT / 'scripts'
SELF = Path(__file__).name


def discover():
    refresh = sorted(p for p in SCRIPTS_DIR.glob('refresh-*.py') if p.name != SELF)
    enrich = sorted(SCRIPTS_DIR.glob('enrich-*.py'))
    return refresh + enrich


def run_one(script: Path) -> bool:
    rel = script.relative_to(ROOT)
    print(f"\n{'=' * 60}", flush=True)
    print(f"  {rel}", flush=True)
    print('=' * 60, flush=True)

    result = subprocess.run([sys.executable, str(script)], cwd=str(ROOT))
    return result.returncode == 0


def main() -> int:
    scripts = discover()
    if not scripts:
        print("No refresh-*.py or enrich-*.py scripts found.", file=sys.stderr)
        return 1

    results: list[tuple[str, bool]] = []
    for script in scripts:
        ok = run_one(script)
        results.append((script.name, ok))

    passed = [n for n, ok in results if ok]
    failed = [n for n, ok in results if not ok]

    print(f"\n{'=' * 60}", flush=True)
    print("  SUMMARY", flush=True)
    print('=' * 60, flush=True)
    print(f"  Passed: {len(passed)}/{len(results)}")
    for n in passed:
        print(f"    OK    {n}")
    if failed:
        print(f"  Failed: {len(failed)}/{len(results)}")
        for n in failed:
            print(f"    FAIL  {n}")

    return 0 if not failed else 1


if __name__ == '__main__':
    sys.exit(main())
