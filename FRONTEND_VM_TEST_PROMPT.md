# Frontend VM Testing Prompt (Campaign Platform)

Use this prompt to run and validate the frontend on the VM at 139.59.32.72. It performs a practical smoke test and verifies that the Classified Gmail UI is served and responsive.

## Objective
- Build and serve the React frontend on the VM.
- Verify preview server responds with HTTP 200.
- Check homepage contains 'Classified Gmail' (new feature).
- Capture logs for troubleshooting.

## Environment Assumptions
- VM OS: Ubuntu/Debian
- Repo path: `/var/www/campaign_platform`
- Frontend path: `/var/www/campaign_platform/Campaign_platform`
- Node.js may or may not be installed

## Acceptance Criteria
- Preview server starts and serves `index.html` (HTTP 200)
- Homepage loads without console errors
- Text "Classified Gmail" present (if routing exposes it)
- Build artifacts exist in `dist/`

## Commands (run from your local machine)

1) Copy test script to VM:
```powershell
scp scripts\test_frontend_vm.sh root@139.59.32.72:/var/www/campaign_platform/scripts/test_frontend_vm.sh
```

2) Run the script on VM:
```powershell
ssh root@139.59.32.72 "sudo bash /var/www/campaign_platform/scripts/test_frontend_vm.sh"
```

3) Inspect logs if needed:
```powershell
ssh root@139.59.32.72 "tail -n 120 /var/www/campaign_platform/logs/frontend_preview.log"
```

## Alternate Manual Steps (if you prefer running commands yourself)
```bash
ssh root@139.59.32.72
cd /var/www/campaign_platform/Campaign_platform
# Ensure Node/npm
node -v || (curl -fsSL https://deb.nodesource.com/setup_18.x | bash - && apt-get install -y nodejs)
# Install deps
npm ci || npm install --no-audit --no-fund
# Build
npm run build
# Serve preview on 0.0.0.0:4173
nohup npm run preview -- --host 0.0.0.0 --port 4173 > /var/www/campaign_platform/logs/frontend_preview.log 2>&1 &
# Smoke test
curl -I http://127.0.0.1:4173
curl -s http://127.0.0.1:4173 | grep -i "Classified Gmail" || echo "Text not found (routing may hide it)"
```

## Troubleshooting
- If `npm run build` fails:
  - Ensure `node_modules` exists; rerun `npm install`
  - Check `eslint.config.js` and `vite.config.js` for syntax errors
- If preview returns non-200:
  - Tail logs: `/var/www/campaign_platform/logs/frontend_preview.log`
  - Confirm port `4173` is open on VM firewall
- If "Classified Gmail" not found:
  - Navigate in the UI; the text may be on a route
  - Confirm feature was deployed in `src/pages/sales/ClassifiedGmail.jsx`

## Success Output (expected)
- HTTP 200 on `http://127.0.0.1:4173`
- Console shows Node/npm versions and build success
- Log file path displayed: `/var/www/campaign_platform/logs/frontend_preview.log`
- Optional: "PASS: 'Classified Gmail' text detected" message

---

For deeper testing (browser-based, a11y, performance), consider adding Playwright/Lighthouse in a follow-up. This prompt focuses on a reliable smoke test to validate deployment and the recent changes.
