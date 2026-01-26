#!/usr/bin/env bash
set -euo pipefail

# Frontend VM smoke test for Campaign_platform
# - Installs Node.js if missing (Ubuntu/Debian)
# - Installs deps, builds, starts preview server
# - Performs HTTP smoke check and content check

FRONTEND_DIR=${FRONTEND_DIR:-/var/www/campaign_platform/Campaign_platform}
PORT=${PORT:-4173}
LOG_DIR=${LOG_DIR:-/var/www/campaign_platform/logs}

echo "[Frontend VM Test] $(date)"
echo "Directory: $FRONTEND_DIR"
echo "Port: $PORT"

if [ ! -d "$FRONTEND_DIR" ]; then
  echo "ERROR: Frontend directory not found: $FRONTEND_DIR"
  exit 1
fi
cd "$FRONTEND_DIR"

# Ensure Node.js + npm
if ! command -v node >/dev/null 2>&1; then
  echo "Node.js not found; installing Node.js 18..."
  curl -fsSL https://deb.nodesource.com/setup_18.x | bash -
  apt-get install -y nodejs
fi

echo "Node: $(node -v) | npm: $(npm -v)"

# Install dependencies
if [ -d node_modules ]; then
  echo "node_modules exists; running npm install to verify deps"
  npm install --no-audit --no-fund
else
  echo "Installing dependencies..."
  npm ci || npm install --no-audit --no-fund
fi

# Build
echo "Building frontend..."
npm run build

# Start preview server
mkdir -p "$LOG_DIR"
PREVIEW_CMD="npm run preview -- --host 0.0.0.0 --port $PORT"
echo "Starting preview: $PREVIEW_CMD"
nohup bash -lc "$PREVIEW_CMD" > "$LOG_DIR/frontend_preview.log" 2>&1 &

# Wait and smoke test
sleep 4
STATUS=$(curl -s -o /dev/null -w "%{http_code}" "http://127.0.0.1:$PORT")
if [ "$STATUS" != "200" ]; then
  echo "ERROR: Preview returned HTTP $STATUS"
  tail -n 60 "$LOG_DIR/frontend_preview.log" || true
  exit 2
fi

HTML=$(curl -s "http://127.0.0.1:$PORT")
if echo "$HTML" | grep -qi "Classified Gmail"; then
  echo "PASS: 'Classified Gmail' text detected in homepage"
else
  echo "WARN: 'Classified Gmail' not detected; homepage served"
fi

echo "OK: Frontend preview running on http://$(hostname -I | awk '{print $1}'):$PORT"
echo "Logs: $LOG_DIR/frontend_preview.log"
