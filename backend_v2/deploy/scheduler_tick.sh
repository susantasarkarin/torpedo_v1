#!/usr/bin/env bash
# Calls the one Phase 14 heartbeat endpoint (app.scheduler.routers.scheduler_tick),
# signed with the same HMAC scheme app.panel.callback_security already built for
# Cint's outcome callback — this script IS the "systemd timer calling this on a
# cadence" the endpoint's own docstring describes. It is not a giant cron script:
# all the actual logic (what to detect, how to dispatch, how to retry) lives in
# app/scheduler/, tested in tests/test_scheduler_*.py. This script's only job is
# signing and making the one HTTP call.
#
# Requires SCHEDULER_SIGNING_SECRET in the environment — read from an
# EnvironmentFile by the paired .service unit, never hardcoded here or passed on
# a command line where it would show up in `ps`.
set -euo pipefail

TORPEDO_V2_URL="${TORPEDO_V2_URL:-http://127.0.0.1:8002}"
ORG_ID="${TORPEDO_V2_ORG_ID:-torpedo}"
: "${SCHEDULER_SIGNING_SECRET:?SCHEDULER_SIGNING_SECRET not set — refusing to run unsigned}"

BODY=$(printf '{"org_id":"%s"}' "$ORG_ID")
SIGNATURE=$(printf '%s' "$BODY" | openssl dgst -sha256 -hmac "$SCHEDULER_SIGNING_SECRET" | sed 's/^.* //')

curl -sf -X POST "${TORPEDO_V2_URL}/api/v1/internal/scheduler/tick" \
  -H "Content-Type: application/json" \
  -H "X-Signature: ${SIGNATURE}" \
  --data-binary "${BODY}"
