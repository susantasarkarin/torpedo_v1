#!/usr/bin/env bash
# Phase 19 (backup/recovery audit): torpedo_v2's MongoDB database had zero
# backup coverage — no automated dump, no retention, no tested restore path
# — despite mongodump already being installed on the VM and v1's own cron
# jobs proving the "systemd timer / cron calling a small script" pattern is
# already how this platform runs scheduled operational tasks (see
# scheduler_tick.sh for the Phase 14 precedent this follows).
#
# Dumps to a location OUTSIDE the git-tracked backend_v2 tree on purpose —
# a database dump must never be swept up by `git add -A` or land in a
# deploy diff. Requires MONGO_URI/MONGO_DB_NAME in the environment, read
# from an EnvironmentFile by the paired .service unit — never hardcoded
# here or passed on a command line where it would show up in `ps`.
set -euo pipefail

: "${MONGO_URI:?MONGO_URI not set — refusing to run without a real connection string}"
: "${MONGO_DB_NAME:?MONGO_DB_NAME not set}"

BACKUP_DIR="${TORPEDO_V2_BACKUP_DIR:-/var/backups/torpedo-v2-mongo}"
RETENTION_DAYS="${TORPEDO_V2_BACKUP_RETENTION_DAYS:-7}"
TIMESTAMP=$(date -u +%Y%m%d-%H%M%S)
ARCHIVE_PATH="${BACKUP_DIR}/${MONGO_DB_NAME}_${TIMESTAMP}.archive.gz"

mkdir -p "$BACKUP_DIR"

mongodump --uri="$MONGO_URI" --db="$MONGO_DB_NAME" --archive="$ARCHIVE_PATH" --gzip

# A dump that produced an empty or missing archive is a silent-failure risk
# worse than no backup at all (false confidence) — fail loud instead.
if [ ! -s "$ARCHIVE_PATH" ]; then
  echo "backup_mongo.sh: archive at ${ARCHIVE_PATH} is missing or empty — treating as a failed backup" >&2
  exit 1
fi

find "$BACKUP_DIR" -name "${MONGO_DB_NAME}_*.archive.gz" -mtime "+${RETENTION_DAYS}" -delete

echo "backup_mongo.sh: wrote ${ARCHIVE_PATH} ($(du -h "$ARCHIVE_PATH" | cut -f1))"
