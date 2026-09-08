#!/usr/bin/env bash
# Calls POST /internal/gpu/sweep (app.ai.routers.gpu_sweep), the checklist's
# own "a real, small follow-up, not fabricated here" item: GpuBroker.sweep()
# existed but nothing ever called it on a schedule, so an idle/orphaned GPU
# pod would keep running (and billing) all month instead of being reaped.
# Signed with the same HMAC scheme scheduler_tick.sh already uses, reusing
# SCHEDULER_SIGNING_SECRET rather than provisioning a second one — both are
# internal, systemd-timer-invoked endpoints on the same deployment.
#
# Deliberately its own timer, not folded into scheduler_tick.sh: sweep() is a
# global, deployment-wide GPU-broker operation, not tied to any one org, so
# it doesn't fit the per-org Event/EventOrchestrator pattern the rest of
# Phase 14 uses.
set -euo pipefail

TORPEDO_V2_URL="${TORPEDO_V2_URL:-http://127.0.0.1:8002}"
: "${SCHEDULER_SIGNING_SECRET:?SCHEDULER_SIGNING_SECRET not set — refusing to run unsigned}"

BODY='{}'
SIGNATURE=$(printf '%s' "$BODY" | openssl dgst -sha256 -hmac "$SCHEDULER_SIGNING_SECRET" | sed 's/^.* //')

curl -sf -X POST "${TORPEDO_V2_URL}/api/v1/internal/gpu/sweep" \
  -H "Content-Type: application/json" \
  -H "X-Signature: ${SIGNATURE}" \
  --data-binary "${BODY}"
