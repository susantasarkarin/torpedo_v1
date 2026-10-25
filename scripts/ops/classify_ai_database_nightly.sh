#!/bin/bash
# Nightly AI Database segregation (owner 2026-10-25): up to 1,500 "unclear" records
# up the ladder (Qwen in the 22:00-07:00 IST window, Haiku/Sonnet when the Anthropic
# account has credit). Runs 22:15 UTC = 03:45 IST, after the 03:00 IST mongodump,
# because --apply refuses without a dump < 3 h old. Log: /var/log/campaign_platform/.
set -u
cd /var/www/campaign_platform/backend || exit 1
set -a; . ./.env >/dev/null 2>&1; set +a
LOG=/var/log/campaign_platform/classify_ai_database.log
echo "=== $(date -u +%FT%TZ) start" >> "$LOG"
timeout 4h ./venv/bin/python -W ignore scripts/classify_ai_database.py --apply --with-model --redo --limit 1500 >> "$LOG" 2>&1
echo "=== $(date -u +%FT%TZ) exit $?" >> "$LOG"
