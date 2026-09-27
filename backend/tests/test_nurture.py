"""Tests for sales/nurture.py -- the positive-lead nurture track."""
from datetime import datetime, timedelta

from sales import nurture


STEPS = [
    {"step": 1, "label": "Acknowledge & Propose Concall", "delay_days": 0,
     "subject_template": "Re: {original_subject} — next step",
     "script_template": "Hi {first_name},\n\nGlad this is relevant for {company}.\n\nBest,\nSusanta"},
    {"step": 2, "label": "Concall Reminder / Soft Nudge", "delay_days": 3,
     "subject_template": "Re: next step with {company}",
     "script_template": "Hi {first_name}, {unknown_placeholder}\n\nBest,\nSusanta"},
]


def _lead(**kw):
    base = {"_id": "L1", "email": "sean@x.com", "name": "Sean Lee", "first_name": "Sean",
            "company_name": "Acme Research", "reply_subject": "RE: fieldwork support",
            "lead_status": "Positive", "stage": "new", "classification_basket": "A",
            "reply_triage": {"mailbox_id": None, "gmail_thread_id": "t1"}}
    base.update(kw)
    return base


# ---- rendering --------------------------------------------------------------

def test_render_fills_placeholders_and_strips_reply_prefix():
    out = nurture.render_step(_lead(), STEPS[0], signer="Indira")
    assert out["subject"] == "Re: fieldwork support — next step"
    assert "Hi Sean," in out["body"] and "Acme Research" in out["body"]


def test_render_signs_as_the_thread_owner_not_a_hardcoded_name():
    out = nurture.render_step(_lead(), STEPS[0], signer="Indira")
    assert out["body"].rstrip().endswith("Best,\nIndira")


def test_render_leaves_unknown_placeholders_instead_of_crashing():
    out = nurture.render_step(_lead(), STEPS[1], signer="")
    assert "{unknown_placeholder}" in out["body"]


# ---- the due-step job ---------------------------------------------------------

class _Leads:
    """In-memory stand-in for leads_enriched supporting what the job uses."""
    def __init__(self, docs):
        self.docs = {d["_id"]: d for d in docs}

    def find(self, query):
        now = datetime.utcnow()
        due = [d for d in self.docs.values()
               if (d.get("nurture") or {}).get("status") == "active"
               and d["nurture"].get("next_due_at", now) <= now]
        class _Cur(list):
            def limit(self, n):
                return self[:n]
        return _Cur(due)

    def update_one(self, query, update):
        d = self.docs[query["_id"]]
        for k, v in update.get("$set", {}).items():
            self._set(d, k, v)
        for k, v in update.get("$push", {}).items():
            parent, key = self._walk(d, k)
            parent.setdefault(key, []).append(v)

        class _R:
            modified_count = 1
        return _R()

    @staticmethod
    def _walk(d, dotted):
        parts = dotted.split(".")
        for p in parts[:-1]:
            d = d.setdefault(p, {})
        return d, parts[-1]

    def _set(self, d, dotted, v):
        parent, key = self._walk(d, dotted)
        parent[key] = v


def _active(step=0, started_days_ago=0, **kw):
    started = datetime.utcnow() - timedelta(days=started_days_ago)
    return _lead(nurture={"track": nurture.TRACK, "status": "active", "step": step,
                          "started_at": started, "last_touch_at": started,
                          "next_due_at": datetime.utcnow() - timedelta(minutes=1), "history": []}, **kw)


def _wire(monkeypatch, docs, new_reply=False):
    col = _Leads(docs)
    tasks, notes, delivered = [], [], []
    monkeypatch.setattr(nurture, "_leads", lambda: col)
    monkeypatch.setattr(nurture, "_steps", lambda: STEPS)
    monkeypatch.setattr(nurture, "_task", lambda lead, title, due, desc="": tasks.append(title) or "task1")
    monkeypatch.setattr(nurture, "_notify", lambda *a, **k: notes.append(a[0]))
    monkeypatch.setattr(nurture, "_new_reply_since", lambda lead, since: new_reply)
    monkeypatch.setattr(nurture, "_thread_mailbox",
                        lambda lead: {"email": "indira@sfw.com", "display_name": "Indira Das", "thread_id": "t1"})

    def fake_deliver(lead, rendered, box):
        delivered.append(rendered)
        return {"mode": "draft", "success": True, "draft_id": "d1"}
    monkeypatch.setattr(nurture, "_deliver", fake_deliver)
    return col, tasks, notes, delivered


def test_first_step_creates_a_draft_and_a_concall_task(monkeypatch):
    col, tasks, notes, delivered = _wire(monkeypatch, [_active()])
    stats = nurture.run_nurture_due_batch()
    lead = col.docs["L1"]
    assert stats["delivered"] == 1
    assert lead["nurture"]["step"] == 1
    assert lead["nurture"]["history"][0]["draft_id"] == "d1"
    assert tasks == ["Concall with Sean Lee"]
    assert delivered[0]["body"].rstrip().endswith("Indira")
    # next step is scheduled from the start date, per the config's delay_days
    assert lead["nurture"]["next_due_at"] > datetime.utcnow()


def test_a_new_reply_pauses_nurture_for_a_person(monkeypatch):
    col, tasks, notes, delivered = _wire(monkeypatch, [_active(step=1)], new_reply=True)
    stats = nurture.run_nurture_due_batch()
    assert col.docs["L1"]["nurture"]["status"] == "paused_new_reply"
    assert stats["paused_new_reply"] == 1 and delivered == []


def test_a_negative_lead_is_stopped(monkeypatch):
    col, *_ = _wire(monkeypatch, [_active(lead_status="Negative")])
    nurture.run_nurture_due_batch()
    assert col.docs["L1"]["nurture"]["status"] == "stopped"


def test_last_step_completes_the_track(monkeypatch):
    col, *_ = _wire(monkeypatch, [_active(step=1, started_days_ago=4)])
    nurture.run_nurture_due_batch()
    assert col.docs["L1"]["nurture"]["status"] == "completed"
    assert col.docs["L1"]["nurture"]["step"] == 2
