# Marketing runbook

For whoever runs Torpedo's marketing module day to day. Everything here is done in the app (Admin) or, where noted, on the VM (`ssh root@139.59.32.72`, repo `/var/www/campaign_platform`). Times are IST.

## 0. Where things are

| What | Where |
|---|---|
| Tokens and platform IDs | Admin → Marketing → **Integrations** |
| Content calendar, brand voice, tagged links | Admin → Marketing → **Content calendar** |
| Inbox (forms, social, WhatsApp, lead forms) | Admin → Marketing → **Inbox** |
| Dashboard 13 + Needs attention | Admin → Marketing → **Marketing dashboard** (`/admin/dashboards/marketing`) |
| Weekly report (Mon 09:00) | Admin → Marketing → **Weekly report** |
| Decisions to approve / reject | Admin → **Review Queue**, type *marketing decision* |
| Decision log, undo, scorecard, autonomy | Admin → Marketing → **Decision Engine** |
| All settings below | `torpedo_settings.config`, section **marketing** (API `PUT /api/platform/config/marketing`, needs *approve*) |

Scheduled jobs (all in the backend scheduler; `grep -a "Marketing" /var/log/torpedo_backend.log`):

| Job | When |
|---|---|
| Decisions P1 anomalies / P2 pauses, negatives, leads | hourly / hourly at :20 |
| Decisions P3 budget, bids, SEO, content, weekly review (Mon) | 22:30 |
| Outcomes + stop-loss + rejection sync | 06:00 |
| Search Console + GA4 import (URL inspection Mondays) | 07:00 |
| SEO crawl + PageSpeed | Sun 22:00 |
| Touchpoints + attribution | 05:00 |
| Content publish (shadow until live) / Qwen drafts | every 15 min / 23:30 |
| Inbox sync from Review Queue | every 15 min |
| Engine evaluation (42 cases) | Tue 23:00 |
| Weekly report | Mon 09:00 |

## 1. Reconnect an expired or revoked token

1. Integrations shows the platform's **Last error** (e.g. `HTTP 401`, `invalid_grant`). Nothing else breaks: that platform's jobs skip and the rest carry on.
2. Get a new token at the source (MARKETING_AUDIT.md §4 has the exact clicks per platform):
   - Google service account: Cloud Console → IAM → Service accounts → *torpedo-reader* → Keys → Add key → JSON. Delete the old key there.
   - Google Ads refresh token: re-run the OAuth consent (ask Claude to run the one-time flow with you).
   - LinkedIn access token (60 days): developer app → Auth → generate; or the refresh token if the app has it.
   - Meta system-user token: Business Settings → Users → System users → Generate new token (same permissions).
   - WhatsApp: same system-user token; the verify token is any string you choose and also set in the Meta app's webhook settings.
3. Integrations → paste into the field (it shows *Stored. Type to replace.*) → **Save**. The old value is overwritten; it is never shown.
4. Check: the next job run fills **Last OK**. To run the Google import now (VM): `cd backend && venv/bin/python -c "from marketing import google_data; print(google_data.run())"`.
5. If saving says *MARKETING_SECRETS_KEY is not set*: the server lost its key. **Do not generate a new one casually** — every stored token becomes unreadable. Restore it from the `.env` backup (`/root/backups/env.bak-*`), then restart the backend.

## 2. Change autonomy levels and limits

Levels per decision type D1–D14: `L0` off · `L1` recommend (Review Queue only, the default) · `L2` act within limits and notify · `L3` act. L3 is refused in code for budget, bids and client-facing types (D1, D3, D5, D8, D10, D11).

**A type above L1 still acts as L1** until it passes the go-live gate: ≥ 10 of your verdicts in the last 14 days with ≥ 85 % agreement (approve unchanged). The decision shows `gate: …` with the reason.

Change (approve capability): `PUT /api/platform/config/marketing` with the **whole** `autonomy` map (the store replaces the map; send all 14 types), e.g.
`{"autonomy": {"D1":"L1","D2":"L2","D3":"L1","D4":"L2","D5":"L1","D6":"L1","D7":"L1","D8":"L1","D9":"L1","D10":"L1","D11":"L1","D12":"L1","D13":"L2","D14":"L1"}}`

Limits in the same section: `budget` (monthly caps per BU × platform — **no cap = no automatic budget change**; ±20 %/day; 15 %/week; never raise total spend), `bids` (±15 %, 7 days apart), `pause` (min conversions / spend, learning phase), `cooldown_days`, `contact_cap_per_day`, `rules` (thresholds such as `target_cpl_inr` per BU, `pause_min_spend_inr`), `sla_working_hours`, `approved_panel_stats`, `banned_claims`.

Going **live** needs three switches, on purpose: `mode: "live"` + `action_modes["D2:pause"] = "live"` (per type:action, or `content:linkedin` for posting) + that platform's integration registered. Anything missing → the action is logged as *would execute* (shadow).

## 3. Kill switch and undo

- **Stop everything automated**: `PUT /api/platform/config/marketing` `{"kill_switch": {"global": true, "SFW": false, "COGENTIX": false, "BIM": false}}`. One BU: set only that BU true. Checked when deciding **and** again just before acting; publishing also stops.
- **Undo** an executed action (30 days): Marketing → Decision Engine → *Executed* → **Undo** (approve capability). A live action is reversed through the platform with the stored undo payload; a shadow one is just marked undone.
- **Stop-loss** does this by itself: if most of a type's last 10 live actions did worse than baseline, the type drops to L1 and a *marketing stop-loss* item appears in the Review Queue.

## 4. Add a site, channel or campaign

- **New site**: add it to config section `web` → `sites` (`{"domain": "...", "bu": "SFW", "aliases": ["www..."]}`), create the `t.<domain>` CNAME (MARKETING_AUDIT §4.1), run the site converter on a copy of its files (`backend/scripts/site_connect.py`) and upload the zip. The weekly crawl and site-silence check pick it up automatically; add its Search Console property / GA4 ID on Integrations.
- **New social page / ad account**: add its ID to the platform's settings on Integrations as `{"SFW": "<id>"}` (pages, Instagram, ad accounts, phone numbers). The webhook uses these IDs to pick the BU.
- **New campaign**: create it on the ad platform with UTM tags (`utm_source`, `utm_medium=cpc|paid_social`, `utm_campaign=<bu>-<topic>`); it appears after the next daily import. Give it a target CPL per BU in `rules.target_cpl_inr` or the pause / bid rules stay quiet.
- **New content channel**: posts are drafted for linkedin, facebook, instagram, blog, newsletter, quora. Posting a channel live needs its publisher (integration) and `action_modes["content:<channel>"] = "live"`.
- **Quora**: no API. Use *Tagged link* on the Content page for every answer; weekly CSV export from Quora Ads into the upload folder.

## 5. Read the decision log

Collection `email_automation.decisions` (Review Queue shows the open ones). Per decision:

| Field | Meaning |
|---|---|
| `decision_type`, `entity_label`, `rule_id` | what, on which campaign / page / lead, and which rule proposed it |
| `evidence` | the numbers the rule computed (Qwen never computes) |
| `qwen_status`, `reasoning`, `risks`, `expected_impact` | Qwen's view; `unavailable` / `deferred` = rule candidate went on alone |
| `validation_problems` | why Qwen's answer was not accepted (invented number, action not allowed, outside a guardrail) |
| `confidence.score` | code score: data volume, rule/Qwen agreement, past acceptance, past accuracy; ≥ 0.70 needed to act |
| `autonomy`, `gate` | level used; why a higher level was held at L1 |
| `status` | `in_review` · `approved` · `shadow_executed` (would execute) · `executed` · `rejected` · `blocked` (conflict in cooldown) · `skipped` · `undone` · `failed` |
| `would_execute` / `undo_payload` | the exact platform call; how to reverse it |
| `outcome` | after the window: baseline vs actual, better than baseline, direction predicted right |

Evaluation: `marketing_eval_runs` (weekly) — per type validity, agreement with rules, latency. Cases in `marketing_eval_cases` are *proposed* until you mark them *agreed* (M-CP2).

## 6. Privacy rules the code enforces (don't work around them)

- No consent → only anonymous page views; no cookies, IP, click IDs.
- WhatsApp: never cold; opt-in recorded first; free text only inside 24 h of their last message, otherwise an approved template; **STOP** = opt-out at once.
- One automated touch per person per day across mail, WhatsApp and DMs.
- Copy is checked before review: no guaranteed IR / results, no panel size outside `approved_panel_stats`, no client name unless the account is marked *OK to reference*.
- Tokens only on Integrations — never in chat, mail, tickets or code.
