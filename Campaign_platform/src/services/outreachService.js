/**
 * outreachService.js
 * All API calls for the Cold Outreach module (/api/cold-outreach/*).
 * Import individual named exports into components — do not add non-outreach calls here.
 */
import { buildApiUrl } from "../config";
import { authFetch } from "../utils/api";

// authFetch attaches the session token; only the content type is set here.
const auth = () => ({ "Content-Type": "application/json" });

// ── Bulk fetches ──────────────────────────────────────────────────────────────

export const fetchCampaigns = () =>
  authFetch(buildApiUrl("/api/cold-outreach/campaigns"), { headers: auth() });

export const fetchMailboxes = () =>
  authFetch(buildApiUrl("/api/cold-outreach/mailboxes"), { headers: auth() });

export const fetchSuppressionStats = () =>
  authFetch(buildApiUrl("/api/cold-outreach/suppression/stats"), { headers: auth() });

export const fetchSuppression = (search = "", limit = 100) =>
  authFetch(
    buildApiUrl(`/api/cold-outreach/suppression?limit=${limit}&search=${encodeURIComponent(search)}`),
    { headers: auth() }
  );

// ── Campaign actions ──────────────────────────────────────────────────────────

export const createCampaign = (bizKey) =>
  authFetch(buildApiUrl("/api/cold-outreach/campaigns"), {
    method: "POST",
    headers: auth(),
    body: JSON.stringify({ business: bizKey }),
  });

export const launchCampaign = (campaignId) =>
  authFetch(buildApiUrl(`/api/cold-outreach/campaigns/${campaignId}/launch`), {
    method: "POST",
    headers: auth(),
  });

export const pauseCampaign = (campaignId) =>
  authFetch(buildApiUrl(`/api/cold-outreach/campaigns/${campaignId}/pause`), {
    method: "POST",
    headers: auth(),
  });

export const resumeCampaign = (campaignId) =>
  authFetch(buildApiUrl(`/api/cold-outreach/campaigns/${campaignId}/resume`), {
    method: "POST",
    headers: auth(),
  });

// ── Campaign steps ────────────────────────────────────────────────────────────

export const saveStep = (campaignId, stepNum, subject, body_html) =>
  authFetch(buildApiUrl(`/api/cold-outreach/campaigns/${campaignId}/steps/${stepNum}`), {
    method: "PUT",
    headers: auth(),
    body: JSON.stringify({
      subject,
      body_html,
      body_text: body_html.replace(/<[^>]+>/g, ""),
    }),
  });

export const sendTestEmail = (campaignId, stepNum, recipient_email) =>
  authFetch(buildApiUrl(`/api/cold-outreach/campaigns/${campaignId}/steps/${stepNum}/test`), {
    method: "POST",
    headers: auth(),
    body: JSON.stringify({ recipient_email }),
  });

export const generateStep = (campaignId, stepNum) =>
  authFetch(buildApiUrl(`/api/cold-outreach/campaigns/${campaignId}/steps/${stepNum}/generate`), {
    method: "POST",
    headers: auth(),
  });

// ── Business context ──────────────────────────────────────────────────────────

export const saveContext = (campaignId, data) =>
  authFetch(buildApiUrl(`/api/cold-outreach/campaigns/${campaignId}/context`), {
    method: "PUT",
    headers: auth(),
    body: JSON.stringify(data),
  });

// ── Stats & leads ─────────────────────────────────────────────────────────────

export const fetchCampaignStats = (campaignId) =>
  authFetch(buildApiUrl(`/api/cold-outreach/campaigns/${campaignId}/stats`), {
    headers: auth(),
  });

export const fetchLeadsByStatus = (campaignId, status = "all", page = 1, limit = 50) => {
  const params = new URLSearchParams({ status, page: String(page), limit: String(limit) });
  return authFetch(
    buildApiUrl(`/api/cold-outreach/campaigns/${campaignId}/leads-by-status?${params}`),
    { headers: auth() }
  );
};

// ── Dual-Fit ──────────────────────────────────────────────────────────────────

export const enrollDualFit = () =>
  authFetch(buildApiUrl("/api/cold-outreach/dual-fit/enroll"), {
    method: "POST",
    headers: auth(),
  });

// ── Mailboxes ─────────────────────────────────────────────────────────────────

export const addMailbox = (mailboxData) =>
  authFetch(buildApiUrl("/api/cold-outreach/mailboxes"), {
    method: "POST",
    headers: auth(),
    body: JSON.stringify(mailboxData),
  });

export const removeMailbox = (mailboxId) =>
  authFetch(buildApiUrl(`/api/cold-outreach/mailboxes/${mailboxId}`), {
    method: "DELETE",
    headers: auth(),
  });

// ── Suppression ───────────────────────────────────────────────────────────────

export const addSuppression = (email) =>
  authFetch(buildApiUrl("/api/cold-outreach/suppression/manual"), {
    method: "POST",
    headers: auth(),
    body: JSON.stringify({ email }),
  });

export const removeSuppression = (email) =>
  authFetch(buildApiUrl(`/api/cold-outreach/suppression/${encodeURIComponent(email)}`), {
    method: "DELETE",
    headers: auth(),
  });
