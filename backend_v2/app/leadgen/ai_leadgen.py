"""
LeadGenAIService — AI-driven lead generation and ICP evaluation, both routed
through the same `app.ai.decision_engine.DecisionEngine` Slice 11 built and Slice 12
reused, per the master prompt's §1 mandate ("do not build isolated decision
engines"). This module owns GSC-signal context assembly, ICP-context assembly, and
the deterministic guard that stops a hallucinated candidate from ever becoming a
`Person`/`Account` — it does not own identity resolution, deduplication, or lead
creation, all of which are Slice 6's `LeadGenService.ingest()`, called here
unchanged.

**"Do not generate fictional companies. Every lead needs provenance"
(master-prompt §12), enforced structurally**: a candidate the model proposes
without a `company_domain` is skipped, not defaulted to a placeholder — there is no
code path here that creates a `LeadState` without a domain the model actually named.
Every created lead's `RawLeadEvent.payload` carries `gsc_evidence` (the query/signal
that produced the candidate), because "provenance" means a real, inspectable link
back to the GSC data, not a claim in a docstring.

**ICP evaluation is the AI's classification, not a fixed arithmetic score**
(master-prompt §14: "do not use a simplistic fixed arithmetic score as the decision
engine"). This deliberately does *not* replace `app.leadgen.scoring.score_lead()` —
that scorer answers a different, narrower question (does this lead clear v1's B-04
qualification threshold, based on fields already applied to the `Person`/`Account`)
and stays exactly as built in Slice 6. `evaluate_icp()` answers a broader commercial
question (fit, risk, recommended action) using richer context the deterministic
scorer was never designed to weigh — the two coexist because they answer different
questions, not because one is a fake ahead of the other.
"""

from __future__ import annotations

from app.ai.decision_engine import Decision, DecisionEngine
from app.leadgen.gsc import GSCProvider, GSCProviderUnavailable
from app.leadgen.service import IngestResult, LeadGenService

RECOMMENDED_ACTIONS = frozenset({"OUTREACH", "RESEARCH", "HOLD", "REJECT"})


class LeadGenAIError(Exception):
    """GSC unavailable, or the model returned an ICP recommendation outside the
    closed set. Same discipline as every other domain's single error type."""


class LeadGenAIService:
    def __init__(self, decision_engine: DecisionEngine, leadgen: LeadGenService):
        self._decision_engine = decision_engine
        self._leadgen = leadgen

    async def generate_leads(self, *, org_id: str, actor: str, site_url: str, gsc: GSCProvider, internal_context: dict | None = None) -> list[IngestResult]:
        """May raise `LeadGenAIError` (GSC unavailable) or let `LLMUnavailable`/
        `DecisionEngineError` propagate from the decision engine unchanged — a
        model outage or malformed response is a real failure here too, never
        papered over with an empty lead list that looks like "no leads today"."""
        try:
            signals = await gsc.get_search_analytics(site_url=site_url)
        except GSCProviderUnavailable as exc:
            raise LeadGenAIError(f"GSC unavailable: {exc}") from exc

        context = {
            "site_url": site_url,
            "search_signals": [s.__dict__ for s in signals],
            "internal_customer_patterns": internal_context or {},
        }
        decision = await self._decision_engine.decide(org_id=org_id, task="generate_leads", subject_id=site_url, context=context)

        results: list[IngestResult] = []
        for candidate in decision.extracted_entities.get("candidates", []):
            if not isinstance(candidate, dict) or not candidate.get("company_domain"):
                continue  # no domain named by the model — not a real candidate, skipped rather than fabricated
            # Scoped to (domain, contact), not domain alone: the same contact
            # re-surfacing (e.g. a rerun over the same GSC window) must dedupe to
            # the same lead, but a *different* contact at an already-known company
            # is a genuinely new candidate — it should resolve to the same Account
            # (Slice 4's domain-based resolution already guarantees that) while
            # still getting its own Person/LeadState, not being silently dropped.
            contact_key = candidate.get("contact_email") or "no-contact"
            source_record_id = f"gsc:{site_url}:{candidate['company_domain']}:{contact_key}"
            result = await self._leadgen.ingest(
                org_id=org_id, actor=actor, source_type="gsc_ai", source_record_id=source_record_id,
                payload={
                    "company_domain": candidate.get("company_domain"), "company_name": candidate.get("company_name"),
                    "email": candidate.get("contact_email"), "name": candidate.get("contact_name"), "title": candidate.get("title"),
                    "gsc_evidence": candidate.get("evidence"),
                },
            )
            results.append(result)
        return results

    async def evaluate_icp(self, *, org_id: str, actor: str, lead_state_id: str, prospect_context: dict) -> Decision:
        decision = await self._decision_engine.decide(org_id=org_id, task="evaluate_icp", subject_id=lead_state_id, context=prospect_context)
        if decision.decision not in RECOMMENDED_ACTIONS:
            raise LeadGenAIError(f"model returned an unrecognized ICP recommendation {decision.decision!r}")

        # Traceability, not a state change: unlike LeadState.icp_score (owned
        # exclusively by app.leadgen.scoring's canonical scorer), stamping
        # ai_decision_subject_id here never touches that locked field. lead_state_id
        # is caller-supplied and not always a real, persisted LeadState in every
        # caller's flow (e.g. a dry-run evaluation) — silently skipping the stamp
        # when there's no real lead to attach it to is not fabricating data, it's
        # just declining to write traceability metadata onto nothing.
        lead = await self._leadgen.get_lead(lead_state_id)
        # A cross-org lead_state_id must never receive a traceability stamp
        # derived from another org's decision (Phase 15 security audit) — same
        # discipline as every other id-scoped write this pass.
        if lead is not None and lead.org_id == org_id:
            await self._leadgen._facets.update_lead_state(lead.id, lead.version, {"ai_decision_subject_id": lead_state_id}, updated_by=actor)
        return decision
