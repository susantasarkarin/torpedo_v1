"""
Task — the checklist's own "Task/reminder entity | NOT_STARTED — no locked
schema found in schema_catalogue.md for this; deferred rather than invented
ungrounded, per the no-fake-completion rule." That deferral was correct while
no shape existed to build against; this is a deliberate, minimal, generic
design — a real decision now made and stated here, not a guess left
unstated.

**Generic, not per-domain** — I-1 applied here the same way it already is to
`Activity`: one `Task` entity, usable by CRM, Finance, Governance, or
anything else that needs a real reminder, rather than a `CrmTask`/`FinanceTask`
pair the next domain would reinvent. `subject_type`/`subject_id` reuse
`Activity`'s exact polymorphic-link shape (optional here — a task need not
be tied to another entity at all, e.g. a free-standing reminder).

**`assignee` is an opaque user_id, not FK-validated** — the same, explicitly
stated design already used for `Allocation.person_id`/`vendor_id` elsewhere
in this codebase: no user/identity registry exists to validate against for
internal Torpedo operators (`app.rbac`/`app.auth` manage credentials and
roles, not a browsable directory), so this field is a reference a caller
supplies, not a foreign key this module can enforce.

**Three statuses, no more** — `OPEN` -> `DONE` or `OPEN` -> `CANCELLED`,
both terminal. No `IN_PROGRESS`/`BLOCKED`/etc. — a genuine reminder either
still needs doing or it doesn't; a richer workflow state machine is real,
unrequested scope this design deliberately doesn't invent.

**`priority` reuses `Decision.priority`'s exact closed set** (`LOW`/`MEDIUM`/
`HIGH`) rather than a new one — the same value the AI decision contract
already uses, so a task created from an AI-flagged condition (a stale
governance review, an AR follow-up someone needs to chase by hand) can
carry the same priority value through without translation.
"""

from __future__ import annotations

from datetime import datetime

from app.models.base import CanonicalDocument

OPEN = "OPEN"
DONE = "DONE"
CANCELLED = "CANCELLED"
TASK_STATUSES = frozenset({OPEN, DONE, CANCELLED})

TASK_PRIORITIES = frozenset({"LOW", "MEDIUM", "HIGH"})


class Task(CanonicalDocument):
    title: str
    description: str | None = None
    due_at: datetime | None = None
    assignee: str | None = None  # opaque user_id — see module docstring
    priority: str | None = None  # one of TASK_PRIORITIES, or None (unset)
    status: str = OPEN
    completed_at: datetime | None = None
    cancelled_at: datetime | None = None
    cancel_reason: str | None = None
    # Polymorphic link, same shape as Activity.subject_type/subject_id — both
    # set or both omitted (a free-standing reminder needs neither).
    subject_type: str | None = None
    subject_id: str | None = None
