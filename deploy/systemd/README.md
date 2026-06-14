# Prod systemd drop-ins (torpedo-prod @ 139.59.32.72)

Version-controlled copies of the systemd **drop-in overrides** applied on the
production VM. They live under `/etc/systemd/system/<unit>.d/` on the box, which
is **outside** this repo, so a deploy that regenerates unit files (or a rebuilt
VM) can silently drop them. Keep this directory in sync with the VM and reinstall
after any change to the base units.

These files contain **no secrets** — only `EnvironmentFile` path references and
resource limits. The actual secrets stay in `backend/.env` on the VM.

## What each fixes

- **`torpedo-linkedin-worker.service.d/10-mongo-env.conf`**
- **`torpedo-linkedin-beat.service.d/10-mongo-env.conf`**
  Base units read `EnvironmentFile=-/etc/torpedo/linkedin-automation.env`, but
  that file is empty (0 bytes) on prod, so `MONGO_URI` is unset and
  `backend/db_pools.py` aborts on import → both services crash-loop
  (`Restart=always`), starving the 1-vCPU/2GB box → API returns 502s. The drop-in
  re-points `EnvironmentFile` at `backend/.env` which has the real `MONGO_URI`.
  (Alternative permanent fix: populate `/etc/torpedo/linkedin-automation.env`.)

- **`torpedo-backend.service.d/override.conf`**
  (1) `--timeout-graceful-shutdown 10` + `TimeoutStopSec=20` so restarts take a
  few seconds instead of ~90s (uvicorn otherwise waits on lingering cint
  WebSocket connections until SIGKILL). (2) `MemoryMax=1000M` + `OOMPolicy=kill` +
  `Restart=always` so an OOM is contained to the backend (auto-restart) rather
  than the kernel OOM-killer taking down mongod.

## Install / re-apply on the VM

```bash
cd /var/www/campaign_platform
for u in torpedo-backend torpedo-linkedin-worker torpedo-linkedin-beat; do
  mkdir -p "/etc/systemd/system/$u.service.d"
  cp -v "deploy/systemd/$u.service.d/"*.conf "/etc/systemd/system/$u.service.d/"
done
systemctl daemon-reload
# MemoryMax applies live; the rest take effect on next (re)start:
systemctl restart torpedo-backend torpedo-linkedin-worker torpedo-linkedin-beat
```

## Verify

```bash
systemctl show torpedo-backend.service -p MemoryMax,OOMPolicy,Restart,TimeoutStopUSec
systemctl show torpedo-linkedin-worker.service torpedo-linkedin-beat.service -p ActiveState,NRestarts
```

Expect `MemoryMax=1048576000`, `OOMPolicy=kill`, both LinkedIn services
`active` with `NRestarts=0`.
