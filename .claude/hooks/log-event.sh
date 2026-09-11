#!/usr/bin/env bash
# Generic structured-event logger, wired to multiple hook events in
# .claude/settings.json. Reads Claude Code's hook JSON off stdin, wraps it with a
# timestamp and event type, and appends one line to .claude/logs/events.jsonl.
# Always exits 0 — see docs/observability.md for the log schema and rationale.
event_type="${1:-unknown}"
mkdir -p .claude/logs

python3 -c '
import sys, json, datetime

event_type = sys.argv[1]
try:
    payload = json.load(sys.stdin)
except Exception:
    payload = {"raw": sys.stdin.read()}

line = {
    "ts": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    "event_type": event_type,
    "payload": payload,
}
print(json.dumps(line))
' "$event_type" >> .claude/logs/events.jsonl 2>> .claude/logs/hook-errors.log

exit 0
