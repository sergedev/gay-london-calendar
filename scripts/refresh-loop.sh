#!/usr/bin/env bash
# Background-friendly loop that runs refresh-all.py at fixed times each day.
#
# Schedule: 08:00, 14:00, 20:00 local time. Edit SLOTS below to change.
#
# Behaviour:
#   - On startup, reads .last-refresh timestamp. If the most recent scheduled
#     slot has passed without a run since, runs immediately. Otherwise sleeps
#     until the next slot.
#   - After every run, writes .last-refresh and sleeps until the next slot.
#   - When the laptop sleeps, `sleep` pauses with the system; on wake the loop
#     re-evaluates the schedule and runs immediately if a slot was missed.
#   - Stop with Ctrl+C. Restart later: picks up via the timestamp file.
#
# Run from the repo root in its own terminal tab:
#   ./scripts/refresh-loop.sh

set -u

SLOTS=("08:00" "14:00" "20:00")

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TIMESTAMP_FILE="$ROOT/.last-refresh"
REFRESH_ALL="$ROOT/scripts/refresh-all.py"

if [ ! -f "$REFRESH_ALL" ]; then
  echo "error: $REFRESH_ALL not found" >&2
  exit 1
fi

trap 'echo; echo "loop stopped at $(date "+%H:%M:%S")"; exit 0' INT TERM

run_refresh() {
  echo
  echo "=== refresh starting at $(date "+%Y-%m-%d %H:%M:%S") ==="
  if (cd "$ROOT" && python3 "$REFRESH_ALL"); then
    date +%s > "$TIMESTAMP_FILE"
    echo "=== refresh finished at $(date "+%Y-%m-%d %H:%M:%S") ==="
  else
    echo "=== refresh exited non-zero at $(date "+%Y-%m-%d %H:%M:%S") ==="
    # Still record so a persistent failure doesn't hammer every loop tick.
    date +%s > "$TIMESTAMP_FILE"
  fi
}

# Most recent scheduled slot epoch at or before $1 (epoch seconds).
most_recent_slot_at_or_before() {
  local target=$1
  local today=$(date -r "$target" +%Y-%m-%d)
  local yday=$(date -j -v-1d -r "$target" +%Y-%m-%d)
  local best=0
  for d in "$yday" "$today"; do
    for slot in "${SLOTS[@]}"; do
      local t
      t=$(date -j -f "%Y-%m-%d %H:%M" "$d $slot" +%s 2>/dev/null) || continue
      if [ "$t" -le "$target" ] && [ "$t" -gt "$best" ]; then
        best=$t
      fi
    done
  done
  echo "$best"
}

# Next scheduled slot epoch strictly after $1 (epoch seconds).
next_slot_after() {
  local target=$1
  local today=$(date -r "$target" +%Y-%m-%d)
  local tmrw=$(date -j -v+1d -r "$target" +%Y-%m-%d)
  local best=0
  for d in "$today" "$tmrw"; do
    for slot in "${SLOTS[@]}"; do
      local t
      t=$(date -j -f "%Y-%m-%d %H:%M" "$d $slot" +%s 2>/dev/null) || continue
      if [ "$t" -gt "$target" ] && { [ "$best" -eq 0 ] || [ "$t" -lt "$best" ]; }; then
        best=$t
      fi
    done
  done
  echo "$best"
}

read_last_run() {
  if [ -f "$TIMESTAMP_FILE" ]; then
    cat "$TIMESTAMP_FILE"
  else
    echo "0"
  fi
}

format_until() {
  local secs=$1
  local h=$((secs / 3600))
  local m=$(((secs % 3600) / 60))
  printf '%dh %02dm' "$h" "$m"
}

echo "refresh-loop started at $(date "+%Y-%m-%d %H:%M:%S")"
echo "slots: ${SLOTS[*]} | timestamp file: $TIMESTAMP_FILE"
echo "press Ctrl+C to stop"

while true; do
  now=$(date +%s)
  last=$(read_last_run)
  most_recent=$(most_recent_slot_at_or_before "$now")

  if [ "$last" -lt "$most_recent" ]; then
    run_refresh
    continue
  fi

  next=$(next_slot_after "$now")
  remaining=$((next - now))
  echo "next refresh at $(date -r "$next" "+%Y-%m-%d %H:%M:%S") (in $(format_until "$remaining"))"
  sleep "$remaining"
done
