#!/usr/bin/env bash
# Example SessionStart hook — proves the hooks mechanism is wired up.
# Wired in .claude/settings.json under hooks.SessionStart.
echo "[$(date -u +%FT%TZ)] SessionStart hook fired" >> .claude/hooks.log
