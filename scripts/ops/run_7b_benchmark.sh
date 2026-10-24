#!/usr/bin/env bash
# One-off RFQ-extraction benchmark of Qwen2.5-7B (owner-approved option 1, 2026-10-24).
#
#   1. refuse unless the VM is quiet (load and free memory below/above limits)
#   2. stop the production 1.5B server (torpedo-v2-llm) to free its memory
#   3. start llama-server with the 7B model on 127.0.0.1:8013 (single slot,
#      ctx 4096, --cache-ram 0, 3 threads; weights are mmap'd from disk)
#   4. run the benchmark against it, with a watchdog that kills the 7B server
#      if MemAvailable < 500 MB or free swap < 200 MB
#   5. ALWAYS (trap): stop the 7B server, start torpedo-v2-llm again, and
#      check it answers on :8003 before exiting
#
# While the 1.5B server is down, app calls to the local model fail fast with
# LocalSLMUnavailable and their jobs retry later; outreach is paused.
set -u
LOG=/var/log/campaign_platform/run_7b_benchmark.log
MODEL=/opt/torpedo-v2-llm/models/qwen2.5-7b-instruct-q4_k_m.gguf
SERVER=/opt/torpedo-v2-llm/runtime/llama-b10868/llama-server
PORT=8013
BENCH=/tmp/crm_bench
APP=/var/www/campaign_platform/backend
MAX_LOAD=${MAX_LOAD:-3.0}
MIN_AVAIL_MB=${MIN_AVAIL_MB:-3000}
exec >> "$LOG" 2>&1
say() { echo "$(date -u +%FT%TZ) $*"; }

avail_mb() { awk '/MemAvailable/ {print int($2/1024)}' /proc/meminfo; }
swapfree_mb() { awk '/SwapFree/ {print int($2/1024)}' /proc/meminfo; }

restore() {
    say "restore: stopping 7B server, restarting torpedo-v2-llm"
    [ -n "${SRV_PID:-}" ] && kill "$SRV_PID" 2>/dev/null
    [ -n "${WD_PID:-}" ] && kill "$WD_PID" 2>/dev/null
    sleep 3
    pkill -f "llama-server.*--port $PORT" 2>/dev/null
    systemctl start torpedo-v2-llm
    for i in $(seq 1 30); do
        curl -s -m 5 -o /dev/null -w "%{http_code}" http://127.0.0.1:8003/health | grep -q 200 && { say "restore: torpedo-v2-llm healthy"; return; }
        sleep 5
    done
    say "RESTORE FAILED: torpedo-v2-llm not healthy after 150 s"
}

[ -f "$MODEL" ] || { say "abort: model file missing"; exit 2; }
load=$(cut -d' ' -f1 /proc/loadavg)
if awk "BEGIN{exit !($load > $MAX_LOAD)}"; then say "abort: load $load > $MAX_LOAD"; exit 3; fi
pgrep -f rfq_extract_benchmark.py >/dev/null && { say "abort: another benchmark is running"; exit 4; }

say "start: load=$load avail=$(avail_mb)MB swapfree=$(swapfree_mb)MB"
trap restore EXIT
systemctl stop torpedo-v2-llm
sleep 5
if [ "$(avail_mb)" -lt "$MIN_AVAIL_MB" ]; then say "abort: only $(avail_mb)MB available after stopping 1.5B"; exit 5; fi

nice -n 5 "$SERVER" --model "$MODEL" --host 127.0.0.1 --port $PORT --ctx-size 4096 --parallel 1 \
    --threads 3 --cache-ram 0 --no-webui > /var/log/campaign_platform/llama_7b.log 2>&1 &
SRV_PID=$!
for i in $(seq 1 60); do
    curl -s -m 5 http://127.0.0.1:$PORT/health | grep -q '"ok"' && break
    kill -0 $SRV_PID 2>/dev/null || { say "abort: 7B server exited"; exit 6; }
    sleep 5
done
say "7B server up (pid $SRV_PID) avail=$(avail_mb)MB"

( while kill -0 $SRV_PID 2>/dev/null; do
      if [ "$(avail_mb)" -lt 500 ] || [ "$(swapfree_mb)" -lt 200 ]; then
          echo "$(date -u +%FT%TZ) WATCHDOG: avail=$(avail_mb)MB swapfree=$(swapfree_mb)MB -> killing 7B"
          kill $SRV_PID; break
      fi
      sleep 5
  done ) &
WD_PID=$!

cd "$APP" || exit 7
MONGO_URI="$(grep -E '^MONGO_URI=' .env | head -1 | cut -d= -f2- | tr -d "\"'")" \
BENCH_URL="http://127.0.0.1:$PORT/v1/chat/completions" BENCH_MODEL=qwen2.5-7b-instruct-q4_k_m BENCH_USE_GATE=0 \
PYTHONPATH="$BENCH:." nice -n 10 venv/bin/python "$BENCH/rfq_extract_benchmark.py" "$BENCH/rfq_gold_50.json" \
    > "$BENCH/result_7b.json" 2> "$BENCH/progress_7b.txt"
say "benchmark exit=$? peak note: see progress_7b.txt; avail now $(avail_mb)MB"
