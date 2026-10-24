#!/usr/bin/env bash
# Nightly full MongoDB backup for torpedo-prod (CRM audit ground rule + Section 6).
#
#   backups/<UTC timestamp>/full.archive.gz   gzip mongodump archive of every DB
#   backups/<UTC timestamp>/dump.log          mongodump log (per-collection counts)
#   backups/<UTC timestamp>/OK                written only when mongodump exits 0
#   backups/latest -> <timestamp>             updated only on success
#
# Retention: successful backups older than RETENTION_DAYS (default 14) are
# removed; failed runs are kept for inspection until the same age. Runs at the
# lowest CPU/IO priority so the live app is not starved.
#
# Cron (root): 30 21 * * *  = 03:00 IST
#   30 21 * * * /var/www/campaign_platform/scripts/ops/mongo_backup.sh >> /var/log/campaign_platform/mongo_backup.log 2>&1
set -u
APP_DIR="${APP_DIR:-/var/www/campaign_platform}"
BACKUP_DIR="${BACKUP_DIR:-$APP_DIR/backups}"
RETENTION_DAYS="${RETENTION_DAYS:-14}"
ENV_FILE="${ENV_FILE:-$APP_DIR/backend/.env}"

MONGO_URI="$(grep -E '^MONGO_URI=' "$ENV_FILE" | head -1 | cut -d= -f2- | tr -d "\"'")"
if [ -z "$MONGO_URI" ]; then
    echo "$(date -u +%FT%TZ) ERROR: MONGO_URI not found in $ENV_FILE"
    exit 1
fi

TS="$(date -u +%Y%m%dT%H%M%SZ)"
OUT="$BACKUP_DIR/$TS"
mkdir -p "$OUT"
chmod 700 "$BACKUP_DIR"

start=$(date +%s)
nice -n 19 ionice -c3 mongodump --uri="$MONGO_URI" --gzip \
    --archive="$OUT/full.archive.gz" --numParallelCollections=1 > "$OUT/dump.log" 2>&1
rc=$?
secs=$(( $(date +%s) - start ))
size=$(du -sh "$OUT/full.archive.gz" 2>/dev/null | cut -f1)
colls=$(grep -c "done dumping" "$OUT/dump.log")

if [ $rc -eq 0 ]; then
    echo "$TS" > "$OUT/OK"
    ln -sfn "$TS" "$BACKUP_DIR/latest"
    echo "$(date -u +%FT%TZ) OK $TS size=$size collections=$colls secs=$secs"
else
    echo "$(date -u +%FT%TZ) FAILED $TS rc=$rc size=$size secs=$secs; see $OUT/dump.log"
fi

# Retention: only touch timestamped dirs, never 'latest' or anything else.
find "$BACKUP_DIR" -mindepth 1 -maxdepth 1 -type d -name '20*T*Z' -mtime +"$RETENTION_DAYS" \
    -exec rm -rf {} + 2>/dev/null

exit $rc
