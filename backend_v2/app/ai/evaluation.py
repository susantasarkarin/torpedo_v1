"""
DecisionEvaluator — a repeatable evaluation harness for the DecisionEngine,
per the master completion program's explicit "AI evaluation harness"
requirement (Phase 2). Runs a fixed set of scripted `(task, context,
acceptance check)` cases against any `LLMProvider` — `FakeLLM` today, since
no real model exists yet (`RUNPOD_API_KEY` confirmed absent), and the exact
same real `GpuBrokerLLMProvider` the moment one is activated, with zero
change to this module. This is infrastructure, not a claim that evaluation
has run against a real model — see `docs/GPU_ACTIVATION_RUNBOOK.md`'s Phase C
("run the existing 385+ tests... against the real backend") for when it does.

**What this measures, honestly**: whether a model's response, for a given
real business context, (a) parses as a valid `Decision` at all, (b) never
names a candidate outside the offered set (the same "hallucinated ID"
protection every domain service already enforces at the point of execution —
this harness measures the *rate*, across a fixture set, rather than gating
one call), and (c) satisfies a caller-supplied acceptance check specific to
that fixture (e.g. "the AR follow-up for a 60-day-overdue invoice should not
be NO_ACTION"). It does NOT score business correctness in any general sense —
that needs real historical outcomes (Phase 12's decision→execution→outcome
loop), not a fixed fixture set.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from app.ai.decision_engine import Decision, DecisionEngine, DecisionEngineError
from app.ai.llm import LLMUnavailable


@dataclass(frozen=True)
class EvalCase:
    name: str
    task: str
    subject_id: str
    context: dict
    check: Callable[[Decision], bool]  # True if the decision is acceptable for this fixture
    # If set, decision.decision and every entry in decision.entities must be
    # a member of this set (or the literal sentinel "NONE") — the same
    # candidate-set discipline every domain service enforces, measured here
    # across a fixture set rather than gated on one live call.
    candidate_ids: frozenset[str] | None = None


@dataclass(frozen=True)
class EvalResult:
    name: str
    passed: bool
    decision: Decision | None
    error: str | None


async def run_evaluation(engine: DecisionEngine, *, org_id: str, cases: list[EvalCase]) -> list[EvalResult]:
    results: list[EvalResult] = []
    for case in cases:
        try:
            decision = await engine.decide(org_id=org_id, task=case.task, subject_id=case.subject_id, context=case.context)
        except (DecisionEngineError, LLMUnavailable) as exc:
            results.append(EvalResult(name=case.name, passed=False, decision=None, error=str(exc)))
            continue

        if case.candidate_ids is not None:
            named = {decision.decision, *decision.entities} - {"NONE"}
            if named - case.candidate_ids:
                results.append(EvalResult(name=case.name, passed=False, decision=decision, error=f"named {sorted(named - case.candidate_ids)}, outside the offered candidate set"))
                continue

        passed = case.check(decision)
        results.append(EvalResult(name=case.name, passed=passed, decision=decision, error=None if passed else "acceptance check failed"))
    return results


def summarize(results: list[EvalResult]) -> dict:
    total = len(results)
    passed = sum(1 for r in results if r.passed)
    hallucinated = sum(1 for r in results if r.error and "candidate set" in r.error)
    errored = sum(1 for r in results if r.decision is None)
    return {
        "total": total,
        "passed": passed,
        "failed": total - passed,
        "pass_rate": round(passed / total, 3) if total else None,
        "hallucinated_candidate_count": hallucinated,
        "engine_errored_count": errored,
    }
