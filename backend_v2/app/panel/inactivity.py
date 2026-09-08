"""
StudyInactivityService — the deterministic detection half of the master prompt's
Phase 11 ("no traffic > 7 days"). This module finds candidates and flags them with
one `study_inactive_detected` Activity; it does **not** decide to pause, close,
reactivate, or escalate a study — that decision belongs to the AI Decision Engine
(`docs/AI_NATIVE_COMPLETION_CHECKLIST.md`, Phase 2/3), which is blocked pending the
GPU-broker resourcing decision recorded there. Hard-coding an if/else here and
calling it "AI investigation" would be exactly the fake-completion failure mode this
whole rebuild exists to avoid — so the boundary is held here, honestly, the same way
the >20% conversion gate in `service.py` holds the line between "deterministic
eligibility" and "AI ranking."

**Detection is idempotent within one inactivity episode**: a survey already flagged
inside the current window isn't re-flagged on every scan — otherwise a scheduler
running this every few minutes (Phase 14, not yet built) would produce one Activity
per run for the same still-unresolved gap, drowning the real signal.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.models.activity import Activity
from app.models.base import CanonicalRepository
from app.panel.models import Allocation, Survey

DEFAULT_INACTIVITY_WINDOW = timedelta(days=7)


class StudyInactivityService:
    def __init__(self, surveys: CanonicalRepository[Survey], allocations: CanonicalRepository[Allocation], activities: CanonicalRepository[Activity]):
        self._surveys = surveys
        self._allocations = allocations
        self._activities = activities

    async def detect_and_flag(self, *, org_id: str, as_of: datetime | None = None, window: timedelta = DEFAULT_INACTIVITY_WINDOW) -> list[Survey]:
        as_of = as_of or datetime.now(timezone.utc)
        cutoff = as_of - window

        eligible_surveys = await self._surveys.find_all({"org_id": org_id, "eligibility_is_active_in_pool": True})
        flagged: list[Survey] = []

        for survey in eligible_surveys:
            # Phase 18 performance follow-up: only the most recent timestamp
            # is needed — pulling every Allocation/Activity a survey has ever
            # had (a number that grows with a study's real traffic volume)
            # just to call max() on their created_at was wasted work on a
            # detector meant to run on every scheduler tick.
            latest_allocation = await self._allocations._collection.find({"survey_id": survey.id, "deleted_at": None}).sort("created_at", -1).limit(1).to_list(length=1)
            last_allocation_at = latest_allocation[0]["created_at"] if latest_allocation else None
            if last_allocation_at is not None and last_allocation_at >= cutoff:
                continue  # had traffic within the window — not inactive

            latest_flag = await self._activities._collection.find({"subject_type": "survey", "subject_id": survey.id, "type": "study_inactive_detected", "deleted_at": None}).sort("created_at", -1).limit(1).to_list(length=1)
            latest_flag_at = latest_flag[0]["created_at"] if latest_flag else None
            if latest_flag_at is not None and latest_flag_at >= cutoff:
                flagged.append(survey)  # already flagged for this same episode — don't spam a second Activity
                continue

            await self._activities.insert(
                Activity(
                    org_id=org_id, created_by="system", updated_by="system", type="study_inactive_detected",
                    subject_type="survey", subject_id=survey.id, actor_type="system", actor_id="system",
                    payload={"last_allocation_at": last_allocation_at.isoformat() if last_allocation_at else None, "window_days": window.days},
                )
            )
            flagged.append(survey)

        return flagged
