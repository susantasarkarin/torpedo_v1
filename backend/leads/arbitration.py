"""
CROSS-ENTITY ARBITRATION
========================

One person, one entity. When several ICPs express interest in the same human
and those interests map to different buckets, exactly one entity may contact
them — and after any send, no other entity may contact them for the cooldown.

Interest is plural, sending is singular. lead_interests keeps every ICP's
interest because that is real signal; this module decides who gets to act.

    arbitrate(interests, person) -> ArbitrationResult

OUTCOMES
--------
    single_interest          one bucket in play, nothing to arbitrate
    arbitrated               a winner was selected; losers carry the reason
                             'lost_arbitration' with winner AND runner-up
    ambiguous_review         top two within ARBITRATION_AMBIGUITY_MARGIN;
                             a human decides (branch gated, see below)
    review_branch_disabled   ambiguous, but nobody owns the queue so nothing
                             was routed. Remedy: name a human.
    blocked_review_capacity  ambiguous, routed, and the queue is at its cap.
                             Remedy: work the queue, or fix the classifier.
                             Kept apart from review_branch_disabled because
                             "capacity" would point at raising a cap that is
                             not the problem, and at the wrong person.
    cooldown_block           another entity contacted this person recently
    no_bucket                no interest carries a classifier bucket

Every outcome is a recorded reason. Nothing is dropped silently — the
existing rejection-reason logging is added to, never removed.

THE REVIEW BRANCH IS OFF BY DEFAULT, AND THAT IS DELIBERATE
-----------------------------------------------------------
Basket D is 11,291 of 20,639 classified leads (55%). Those are precisely the
leads the classifier could not separate between SFW and Cogentix, which is
precisely the population that lands inside the ambiguity margin. Routing them
to review means routing them to routers/review_queue.py, which has an API and
no demonstrated consumer: no UI, no assignee, no SLA, no aging metric.

That is the same shape as the deferred cleanup of the 9,747 multi-brand
enrollments — a correct-sounding deferral into a place nothing drains. So:

  * REVIEW_BRANCH_ENABLED defaults FALSE. A flag defaulting on with a TODO to
    find an owner is that failure in miniature.
  * REVIEW_QUEUE_CAP defaults 500 and FAILS CLOSED. The cap is not
    backpressure sized to human throughput — it is an INSTRUMENT. Filling it
    is the measurement. If the classifier genuinely cannot tell which of two
    entities should contact someone, then not contacting them is the correct
    output, not a deferral with a cost. You do not know who should email them.
  * blocked_review_capacity is reported separately from lost_arbitration so
    the cost of the classifier problem appears in the per-entity funnel where
    someone would act on it, rather than the leads vanishing from reporting.

Queue depth over time also answers a question the repo cannot: a fixable
classifier converges as it improves, a genuine market overlap does not. Which
is why losers record the RUNNER-UP as well as the winner — if SFW wins and
Cogentix is runner-up across most of the ~11k, that is a market overlap
wearing a confidence score, and the evidence is already collected rather than
needing a backfill.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)


def _env_float(key: str, default: float) -> float:
    try:
        return float(os.getenv(key, default))
    except (TypeError, ValueError):
        return default


def _env_int(key: str, default: int) -> int:
    try:
        return int(os.getenv(key, default))
    except (TypeError, ValueError):
        return default


def _env_bool(key: str, default: bool) -> bool:
    return (os.getenv(key) or str(default)).strip().lower() in ("1", "true", "yes", "on")


# ---------------------------------------------------------------------------
# Configuration — ordering is configurable, never hardcoded
# ---------------------------------------------------------------------------

CROSS_ENTITY_COOLDOWN_DAYS = _env_int("CROSS_ENTITY_COOLDOWN_DAYS", 90)
ARBITRATION_AMBIGUITY_MARGIN = _env_float("ARBITRATION_AMBIGUITY_MARGIN", 0.15)

REVIEW_BRANCH_ENABLED = _env_bool("ARBITRATION_REVIEW_BRANCH_ENABLED", False)
REVIEW_QUEUE_CAP = _env_int("ARBITRATION_REVIEW_QUEUE_CAP", 500)

# Sort keys applied in order, each (field, descending). Overridable via
# ARBITRATION_ORDERING as a comma-separated list, e.g.
#     ARBITRATION_ORDERING="score:desc,bucket_confidence:desc"
_DEFAULT_ORDERING: Tuple[Tuple[str, bool], ...] = (
    ("bucket_confidence", True),   # primary: the classifier's own certainty
    ("score", True),               # tie-break: ICP fit
    ("discovered_at", False),      # tie-break: first entity to find them
)


def _parse_ordering() -> Tuple[Tuple[str, bool], ...]:
    raw = os.getenv("ARBITRATION_ORDERING", "").strip()
    if not raw:
        return _DEFAULT_ORDERING
    parsed: List[Tuple[str, bool]] = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        name, _, direction = part.partition(":")
        parsed.append((name.strip(), direction.strip().lower() != "asc"))
    return tuple(parsed) or _DEFAULT_ORDERING


ORDERING = _parse_ordering()


# ---------------------------------------------------------------------------
# Result
# ---------------------------------------------------------------------------

@dataclass
class ArbitrationResult:
    outcome: str
    winner: Optional[str] = None          # winning bucket / entity
    runner_up: Optional[str] = None
    winning_interest: Optional[Dict[str, Any]] = None
    losers: List[Dict[str, Any]] = field(default_factory=list)
    margin: Optional[float] = None
    detail: Optional[str] = None

    @property
    def may_send(self) -> bool:
        return self.outcome in ("single_interest", "arbitrated")


# ---------------------------------------------------------------------------
# Sorting
# ---------------------------------------------------------------------------

def _sort_key(interest: Dict[str, Any]):
    key = []
    for name, descending in ORDERING:
        val = interest.get(name)
        if val is None:
            # Missing values sort last regardless of direction — an interest
            # with no confidence must never outrank one that has it.
            val = float("-inf") if descending else datetime.max
        if isinstance(val, datetime):
            val = val.timestamp()
        try:
            val = float(val)
        except (TypeError, ValueError):
            val = float("-inf") if descending else float("inf")
        key.append(-val if descending else val)
    return tuple(key)


def rank(interests: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Bucketed interests, best first, per the configured ordering."""
    return sorted([i for i in interests if i.get("bucket")], key=_sort_key)


# ---------------------------------------------------------------------------
# Cooldown — global, never scoped by entity
# ---------------------------------------------------------------------------

def cooldown_blocker(
    person: Dict[str, Any],
    candidate_entity: str,
    now: Optional[datetime] = None,
    cooldown_days: int = None,
) -> Optional[str]:
    """
    Return the entity that blocks this candidate, or None if clear.

    Reads persons.last_contacted_at / last_contacted_by_entity, which are
    global by construction. This query is NEVER filtered by entity — three
    entity-scoped checks each returning "no, not me" is how one human received
    three cold emails.

    A brand may follow up with its own prospect, so the same entity does not
    block itself.
    """
    days = CROSS_ENTITY_COOLDOWN_DAYS if cooldown_days is None else cooldown_days
    last_at = person.get("last_contacted_at")
    last_by = person.get("last_contacted_by_entity")
    if not last_at or not last_by:
        return None
    if last_by == candidate_entity:
        return None
    now = now or datetime.utcnow()
    if (now - last_at) < timedelta(days=days):
        return last_by
    return None


# ---------------------------------------------------------------------------
# Arbitration
# ---------------------------------------------------------------------------

def arbitrate(
    interests: Sequence[Dict[str, Any]],
    person: Optional[Dict[str, Any]] = None,
    now: Optional[datetime] = None,
    review_queue_depth: Optional[int] = None,
) -> ArbitrationResult:
    """
    Decide which single entity, if any, may contact this person.

    `review_queue_depth` is injected rather than queried so the caller owns
    the read and this stays testable without a database.
    """
    person = person or {}
    now = now or datetime.utcnow()

    ranked = rank(interests)
    if not ranked:
        return ArbitrationResult("no_bucket",
                                 detail="no interest carries a classifier bucket")

    distinct_buckets = {i["bucket"] for i in ranked}
    best = ranked[0]

    # One bucket in play — nothing to arbitrate, but cooldown still applies.
    if len(distinct_buckets) == 1:
        blocker = cooldown_blocker(person, best["bucket"], now)
        if blocker:
            return ArbitrationResult(
                "cooldown_block", winner=None, detail=f"blocked_by:{blocker}")
        return ArbitrationResult("single_interest", winner=best["bucket"],
                                 winning_interest=best)

    # Two or more buckets. Runner-up is the best interest of a DIFFERENT
    # bucket, not merely the second row — several ICPs may share the winner.
    runner = next((i for i in ranked if i["bucket"] != best["bucket"]), None)
    margin = None
    if runner is not None:
        top_conf = best.get("bucket_confidence")
        run_conf = runner.get("bucket_confidence")
        if top_conf is not None and run_conf is not None:
            margin = round(float(top_conf) - float(run_conf), 4)

    # Ambiguity: a human decides. Guessing wrong burns the relationship for
    # both brands, so this is not a coin flip.
    #
    # Note `0 <= margin`. A NEGATIVE margin means the configured ordering
    # deliberately picked a lower-confidence bucket — e.g. under
    # ARBITRATION_ORDERING="score:desc", where the operator has said score
    # matters more than classifier certainty. That is a decisive configured
    # choice, not ambiguity, and treating it as ambiguous would send every
    # such lead to review and make the ordering knob unusable.
    if margin is not None and 0 <= margin < ARBITRATION_AMBIGUITY_MARGIN:
        if not REVIEW_BRANCH_ENABLED:
            # DISTINCT from blocked_review_capacity, deliberately.
            #
            # "capacity" implies the remedy is raising the cap. The actual
            # state here is that nobody owns the queue, so nothing was routed
            # at all — the remedy is naming a human. Collapsing the two would
            # point whoever reads the funnel at the wrong lever, and at a
            # different person than the one who can act.
            return ArbitrationResult(
                "review_branch_disabled", winner=None,
                runner_up=runner["bucket"], margin=margin,
                detail="review branch disabled: no named owner for the queue")
        if review_queue_depth is not None and review_queue_depth >= REVIEW_QUEUE_CAP:
            # FAIL CLOSED. Not contacting someone we cannot confidently assign
            # is the correct output, not a deferral.
            return ArbitrationResult(
                "blocked_review_capacity", winner=None,
                runner_up=runner["bucket"], margin=margin,
                detail=f"review queue at cap ({review_queue_depth}/{REVIEW_QUEUE_CAP})")
        return ArbitrationResult(
            "ambiguous_review", winner=None, runner_up=runner["bucket"],
            margin=margin, detail=f"top two within {ARBITRATION_AMBIGUITY_MARGIN}")

    blocker = cooldown_blocker(person, best["bucket"], now)
    if blocker:
        return ArbitrationResult(
            "cooldown_block", winner=None, runner_up=runner["bucket"] if runner else None,
            margin=margin, detail=f"blocked_by:{blocker}")

    # Winner. Losers keep BOTH the winner and the runner-up: if one bucket is
    # consistently runner-up to another across the corpus, that is a market
    # overlap wearing a confidence score, and the evidence needs to already
    # exist when someone asks.
    losers = [
        {
            "icp_id": i.get("icp_id"),
            "bucket": i.get("bucket"),
            "bucket_confidence": i.get("bucket_confidence"),
            "reason": "lost_arbitration",
            "winning_entity": best["bucket"],
            "runner_up_entity": runner["bucket"] if runner else None,
            "margin": margin,
            "arbitrated_at": now,
        }
        for i in ranked if i is not best
    ]
    return ArbitrationResult("arbitrated", winner=best["bucket"],
                             runner_up=runner["bucket"] if runner else None,
                             winning_interest=best, losers=losers, margin=margin)
