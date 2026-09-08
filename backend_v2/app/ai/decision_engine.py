"""
DecisionEngine — event → context → structured decision → audit log. This is where
"the AI is the decision-making engine" (master prompt §3) meets I-4 ("AI proposes,
a deterministic function or a human decides"): `decide()` produces a `Decision` and
persists it as an `AiProposal` (Slice 6/7's existing model — reused, not duplicated,
per I-1). **It never executes an action.** Whatever calls this is the deterministic
code that reads the returned `Decision` and chooses whether/how to act, through the
same permission-gated domain services every other slice already built — a
`Decision.requires_human_approval=True` or a confidence below threshold both mean
"do not auto-apply," exactly the way `AiProposal.status="rejected"` already meant in
Slice 6.

**The structured decision contract matches master-prompt §7 field-for-field**
(`decision`/`reasoning_summary`/`confidence`/`priority`/`entities`/`actions`/
`follow_up_at`/`requires_human_approval`), plus one addition made in Slice 12:
**`extracted_entities: dict`**. Email entity extraction (invoice numbers, amounts,
dates, company names) and ICP evaluation (score/classification/fit_reasons/risks)
both need a richer structured payload than a flat `list[str]` of entity references
— rather than give each domain its own decision schema (exactly what §1 of the
Slice 12-14 instruction forbids: "do not build isolated decision engines"), this one
flexible field carries whatever structured payload a task needs, keeping one
`Decision` shape for every task type. `entities` stays a `list[str]` of entity *ID*
references (unchanged, already tested); `extracted_entities` is for the values.

**`AiProposal.status` stays binary (`approved`/`rejected`)**, its documented Slice 6
scope — a decision needing human approval is `status="rejected"` here too (not
auto-applied), with `requires_human_approval` preserved inside `proposed_fields` so
a reviewer can tell "the model was confident but this needs a human" apart from
"the model wasn't confident." A real pending-review queue, with its own review
actions and a real API (`app.governance.approvals.ApprovalService`,
`GET/POST /governance/proposals`), was the deferred piece this paragraph once
described — built in Slice 22 and extended in Phase 11, additive to `status`,
never rewriting it: `reviewed_by`/`review_action`/`review_notes`/`modified_fields`
record a human's separate, independent verdict, so a reviewer can always tell
what the system decided apart from what a human later decided about it.
"""

from __future__ import annotations

import json
import time
from datetime import datetime

from pydantic import BaseModel, ValidationError, field_validator

from app.ai.llm import LLMProvider, LLMUnavailable
from app.ai.tools import ToolRegistry
from app.models.ai_proposal import AiProposal
from app.models.base import CanonicalRepository

# Reuses app.leadgen.ai's AI_CONFIDENCE_THRESHOLD value deliberately, not a fresh
# number invented for this engine — the same "how confident is confident enough"
# question, answered once (register §4.2's bucket_classifier precedent).
DECISION_CONFIDENCE_THRESHOLD = 0.70

# Bumped whenever _DECISION_SYSTEM_PROMPT's wording changes in a way that could
# shift a real model's behavior — recorded on every AiProposal (Phase 2
# production-platform audit) so a real-world confidence/behavior shift can be
# correlated to "did the prompt change" before "did the model change," the
# same way model/model_version already let that question be asked about the
# model itself.
PROMPT_VERSION = "v1"

PRIORITIES = ("LOW", "MEDIUM", "HIGH", "CRITICAL")


class DecisionEngineError(Exception):
    """The model returned something that doesn't parse as a Decision. Raised, never
    papered over with a default decision — a malformed response is a real failure,
    not a low-confidence one."""


class Decision(BaseModel):
    decision: str
    reasoning_summary: str
    confidence: float
    priority: str
    entities: list[str] = []
    actions: list[str] = []
    follow_up_at: datetime | None = None
    requires_human_approval: bool = False
    extracted_entities: dict = {}

    @field_validator("confidence")
    @classmethod
    def _confidence_in_unit_interval(cls, v: float) -> float:
        if not (0.0 <= v <= 1.0):
            raise ValueError(f"confidence must be between 0 and 1, got {v!r}")
        return v

    def is_auto_appliable(self) -> bool:
        return self.confidence >= DECISION_CONFIDENCE_THRESHOLD and not self.requires_human_approval


_DECISION_SYSTEM_PROMPT = (
    "You are Torpedo's business decision engine. You are given a task and business "
    "context as JSON. Respond with exactly one JSON object matching this schema: "
    '{"decision": str, "reasoning_summary": str (a short business rationale, never '
    'chain-of-thought), "confidence": float 0-1, "priority": "LOW"|"MEDIUM"|"HIGH"|'
    '"CRITICAL", "entities": [str], "actions": [str], "follow_up_at": ISO-8601 '
    'datetime or null, "requires_human_approval": bool, "extracted_entities": '
    "{} (a flat object for any structured, task-specific data — invoice numbers, "
    "amounts, dates, ICP scores, fit reasons, whatever this task calls for)}. "
    "You do not execute actions yourself — you only decide and explain."
)


class DecisionEngine:
    def __init__(self, llm: LLMProvider, tools: ToolRegistry, ai_proposals: CanonicalRepository[AiProposal]):
        self._llm = llm
        self._tools = tools
        self._ai_proposals = ai_proposals

    async def decide(self, *, org_id: str, task: str, subject_id: str, context: dict) -> Decision:
        """May raise `LLMUnavailable` (the model/GPU broker couldn't answer at
        all — re-raised, never substituted with a fabricated decision) or
        `DecisionEngineError` (the model answered, but not as a valid Decision)."""
        messages = [
            {"role": "system", "content": _DECISION_SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps({"task": task, "context": context, "available_tools": self._tools.describe_all()})},
        ]

        started_at = time.perf_counter()
        response = await self._llm.chat(messages=messages, response_format={"type": "json_object"})
        latency_ms = (time.perf_counter() - started_at) * 1000

        try:
            decision = Decision.model_validate(json.loads(response.content))
        except (json.JSONDecodeError, ValidationError) as exc:
            raise DecisionEngineError(f"model returned a malformed decision: {exc}") from exc
        if decision.priority not in PRIORITIES:
            raise DecisionEngineError(f"model returned an unrecognized priority {decision.priority!r}")

        await self._ai_proposals.insert(
            AiProposal(
                org_id=org_id, created_by="system", updated_by="system",
                task=task, subject_id=subject_id, model=response.model, model_version=response.model,
                confidence=decision.confidence, proposed_fields=decision.model_dump(mode="json"),
                status="approved" if decision.is_auto_appliable() else "rejected",
                latency_ms=latency_ms, prompt_tokens=response.prompt_tokens,
                completion_tokens=response.completion_tokens, total_tokens=response.total_tokens,
                prompt_version=PROMPT_VERSION,
            )
        )
        return decision
