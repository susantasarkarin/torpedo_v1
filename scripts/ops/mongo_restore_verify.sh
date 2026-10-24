#!/usr/bin/env bash
# Prove a backup archive restores: load it into a throwaway mongod on its own
# port and dbpath (never the live instance), compare every collection's exact
# document count with the counts mongodump logged, then stop and delete it.
#
# Usage: mongo_restore_verify.sh [backup_dir]   (default: backups/latest)
# Exit 0 only if every collection restored with the logged count.
set -u
APP_DIR="${APP_DIR:-/var/www/campaign_platform}"
SRC="${1:-$APP_DIR/backups/latest}"
SRC="$(readlink -f "$SRC")"
PORT="${VERIFY_PORT:-27019}"
WORK="$(mktemp -d /var/tmp/mongo_verify.XXXXXX)"

cleanup() {
    mongosh --quiet --port "$PORT" --eval 'db.getSiblingDB("admin").shutdownServer({force:true})' >/dev/null 2>&1
    sleep 2
    pkill -f "mongod --port $PORT" 2>/dev/null
    rm -rf "$WORK"
}
trap cleanup EXIT

[ -f "$SRC/full.archive.gz" ] || { echo "no archive in $SRC"; exit 2; }

mkdir -p "$WORK/db"
# A login shell has `ulimit -n 1024`; ~300 collections + their indexes need far
# more files than that (the live mongod.service gets 64000). With the default,
# the temp server WiredTiger-panics with "Too many open files" mid-restore.
ulimit -n 64000 2>/dev/null || ulimit -n "$(ulimit -Hn)"
nice -n 19 mongod --port "$PORT" --bind_ip 127.0.0.1 --dbpath "$WORK/db" \
    --wiredTigerCacheSizeGB 0.25 --fork --logpath "$WORK/mongod.log" >/dev/null || { echo "temp mongod failed"; exit 3; }

URI="mongodb://127.0.0.1:$PORT/?serverSelectionTimeoutMS=60000&connectTimeoutMS=60000"
# admin/config are server metadata, not application data, and restoring
# admin.system.version into a fresh server fails (rc=1).
nice -n 19 ionice -c3 mongorestore --port "$PORT" --gzip --archive="$SRC/full.archive.gz" \
    --nsExclude='admin.*' --nsExclude='config.*' \
    --numParallelCollections=1 --numInsertionWorkersPerCollection=1 > "$WORK/restore.log" 2>&1
rc=$?
echo "mongorestore rc=$rc ($(grep -c 'finished restoring' "$WORK/restore.log") collections, $(tail -1 "$WORK/restore.log" | cut -c1-120))"

# The temp server can be slow to answer right after a large restore on a busy VM.
for i in $(seq 1 30); do
    mongosh --quiet "$URI" --eval 'db.adminCommand({ping: 1}).ok' >/dev/null 2>&1 && break
    sleep 10
done

# Expected counts from the dump log: "done dumping db.coll (N documents)"
grep -oE 'done dumping [^ ]+ \([0-9]+ documents?\)' "$SRC/dump.log" \
    | grep -vE 'dumping (admin|config)\.' \
    | sed -E 's/done dumping ([^ ]+) \(([0-9]+) documents?\)/\1 \2/' > "$WORK/expected.txt"

mongosh --quiet "$URI" --eval '
  const out = [];
  db.adminCommand({listDatabases: 1}).databases.forEach(d => {
    if (["admin","config","local"].includes(d.name)) return;
    const s = db.getSiblingDB(d.name);
    s.getCollectionNames().forEach(c => { if (!c.startsWith("system.")) out.push(d.name + "." + c + " " + s.getCollection(c).countDocuments({})); });
  });
  print(out.join("\n"));' > "$WORK/restored.txt"

python3 - "$WORK/expected.txt" "$WORK/restored.txt" <<'EOF'
import sys
exp = dict(l.rsplit(" ", 1) for l in open(sys.argv[1]) if l.strip())
got = dict(l.rsplit(" ", 1) for l in open(sys.argv[2]) if l.strip())
missing = [k for k in exp if k not in got]
diff = [(k, exp[k], got[k]) for k in exp if k in got and exp[k] != got[k]]
tot_e = sum(int(v) for v in exp.values()); tot_g = sum(int(got.get(k, 0)) for k in exp)
print(f"collections expected={len(exp)} restored={len(got)} missing={len(missing)} count_mismatch={len(diff)}")
print(f"documents expected={tot_e:,} restored={tot_g:,}")
for k in missing[:20]: print("  MISSING", k)
for k, e, g in diff[:20]: print(f"  MISMATCH {k} expected={e} restored={g}")
sys.exit(0 if not missing and not diff else 1)
EOF
ok=$?
[ $rc -eq 0 ] && [ $ok -eq 0 ] && echo "RESTORE VERIFIED: $SRC" || echo "RESTORE CHECK FAILED: $SRC"
[ $rc -eq 0 ] && [ $ok -eq 0 ]
