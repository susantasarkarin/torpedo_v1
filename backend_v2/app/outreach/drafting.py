"""
MessageDrafter — AI drafting behind the same gateway boundary as
`app.leadgen.ai.AIClassifier`, applying I-4 (`AI failure is never a business verdict`)
to outreach: `DraftUnavailable` is raised, never returned as an empty-but-successful
draft, so a caller can't mistake an outage for "the model wrote nothing."

The property this slice exists to prove: a drafted subject/body is not a privileged
input. `MessagingFacade.send()` runs suppression, the kill switch, budget, and the
CAN-SPAM footer check against drafted content exactly as it would against a
caller-supplied `subject`/`body` — drafting only produces text earlier in the same
pipeline, it does not open a side door around any gate.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class DraftUnavailable(Exception):
    """Raised, never returned as a low-confidence draft — mirrors AIUnavailable."""


@dataclass(frozen=True)
class DraftResult:
    subject: str
    body: str
    model: str
    model_version: str
    confidence: float


class MessageDrafter(Protocol):
    async def draft(self, *, to_email: str, context: dict) -> DraftResult:
        """May raise DraftUnavailable."""
        ...
