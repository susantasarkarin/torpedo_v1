"""
EmailMessageDrafter — implements `app.outreach.drafting.MessageDrafter`, not a
second drafting abstraction. This is the whole point of Slice 12's reuse strategy:
an AI-drafted email response goes through `MessagingFacade.send()` exactly like any
other outreach send — suppression, the kill switch, the atomic budget reservation,
the CAN-SPAM footer check, idempotency — all of Slice 7's governance, none of it
rebuilt here. Master-prompt §10 ("never allow AI to bypass suppression/kill-switch/
budget/footer") is true by construction, not by a fresh check added in this module.
"""

from __future__ import annotations

import json

from app.ai.llm import LLMProvider, LLMUnavailable
from app.outreach.drafting import DraftResult, DraftUnavailable

_DRAFT_SYSTEM_PROMPT = (
    "You draft business email responses for Torpedo. Use only the facts given in "
    "the context — never invent a fact, commitment, date, or amount that isn't "
    "present in context. If you don't have enough information to answer well, say "
    "so in the draft rather than guessing. Respond with exactly one JSON object: "
    '{"subject": str, "body": str, "confidence": float 0-1}.'
)


class EmailMessageDrafter:
    def __init__(self, llm: LLMProvider):
        self._llm = llm

    async def draft(self, *, to_email: str, context: dict) -> DraftResult:
        messages = [
            {"role": "system", "content": _DRAFT_SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps({"to_email": to_email, "context": context})},
        ]
        try:
            response = await self._llm.chat(messages=messages, response_format={"type": "json_object"})
        except LLMUnavailable as exc:
            raise DraftUnavailable(str(exc)) from exc

        try:
            data = json.loads(response.content)
            return DraftResult(
                subject=data["subject"], body=data["body"], model=response.model,
                model_version=response.model, confidence=float(data.get("confidence", 0.0)),
            )
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            raise DraftUnavailable(f"model returned a malformed draft: {exc}") from exc
