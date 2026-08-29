"""
CRM spine reconciliation — the safety net behind the inline spine mirrors.

The spine_connector mirrors are best-effort and fire only on live create /
update / delete paths, so the spine can drift: bulk seeds that predate the
mirrors, mirror calls that failed silently, renames applied while the spine
was unreachable, legacy docs deleted outside the API. This nightly task walks
the source-of-truth collections and re-converges crm_db:

  1. Backfill  — finance customers/vendors and sales accounts without a
     crm_account_id back-reference are mirrored and stamped.
  2. Renames   — docs whose name no longer matches their spine account are
     propagated.
  3. Deletions — spine accounts whose finance source doc is gone (or
     soft-deleted) are flagged metadata.source_deleted (never hard-deleted;
     they anchor historical activities).
  4. QRE bridge — studies in the QRE database are mirrored as spine projects
     so fieldwork is visible on the CRM side (QRE runs as a separate app and
     cannot mirror inline).
"""

import logging
import os
import re as _re
from datetime import datetime

from bson import ObjectId

try:
    from backend.celery_app import celery_app
except ImportError:
    from celery_app import celery_app

logger = logging.getLogger(__name__)

QRE_DB_NAME = os.getenv("QRE_DB_NAME", "qre_health_survey")


def _imports():
    try:
        from db_pools import get_db
        from app.services import crm_service, spine_connector
    except ImportError:
        from backend.db_pools import get_db
        from backend.app.services import crm_service, spine_connector
    return get_db, crm_service, spine_connector


def _adopt_spine_accounts_into_sales(sales_accounts, crm_service, stats):
    """
    Reverse direction: spine accounts -> email_automation.sales_accounts.

    Everything else in this task pushes legacy collections INTO the spine. But
    mail_pool_ai creates spine accounts directly from mailbox traffic
    (crm_service.get_or_create_account), and those had no way back — so a
    company that only ever appeared over email was invisible on the Sales
    Account page. This adopts them.

    Only client-type accounts are adopted; vendor/panel accounts on the spine
    are not sales accounts and would pollute the list. Idempotent on
    crm_account_id.
    """
    accounts = crm_service._col("accounts")

    existing_ids = set(
        doc["crm_account_id"]
        for doc in sales_accounts.find(
            {"crm_account_id": {"$exists": True}}, {"crm_account_id": 1}
        )
        if doc.get("crm_account_id")
    )

    query = {
        "$or": [
            {"account_type": "client"},
            {"account_type": {"$exists": False}},
        ],
        "metadata.source_deleted": {"$ne": True},
        # Set by scripts/cleanup_person_fallback_accounts.py — a person's
        # own name stored as a "company" (see mail_pool_ai.py's finance
        # customer_name fallback fix). Excluded here so a future reconcile
        # doesn't silently re-adopt what was just cleaned off the Accounts
        # page.
        "metadata.is_likely_person": {"$ne": True},
    }

    # Sort newest-first: with no sort, Mongo's natural order is roughly
    # insertion order, so once matching accounts passed the limit, newly
    # created ones (the ones most likely to actually be missing from
    # sales_accounts, and most urgent to adopt) were silently never
    # reached at all — found via a live count: 5,749 accounts matched the
    # query but only the oldest ~5,000 were ever visited, permanently
    # starving anything created after that point. Newest-first plus a
    # limit padded well above current volume means growth has headroom
    # before this recurs.
    for account in accounts.find(query).sort("_id", -1).limit(20000):
        spine_id = str(account["_id"])
        if spine_id in existing_ids:
            continue

        name = (account.get("name") or "").strip()
        if not name:
            continue

        # Guard against creating a duplicate of a sales account that exists but
        # was never stamped with its crm_account_id.
        already = sales_accounts.find_one(
            {"account_name": {"$regex": f"^{_re.escape(name)}$", "$options": "i"}},
            {"_id": 1},
        )
        now = datetime.utcnow()
        if already:
            sales_accounts.update_one(
                {"_id": already["_id"]},
                {"$set": {"crm_account_id": spine_id, "updated_at": now}},
            )
            stats["sales_accounts_relinked"] = stats.get("sales_accounts_relinked", 0) + 1
            continue

        metadata = account.get("metadata") or {}
        sales_accounts.insert_one({
            "account_name": name,
            "company_name": name,
            "crm_account_id": spine_id,
            "industry": account.get("industry"),
            "website": account.get("website"),
            "country": account.get("country"),
            "status": "prospect",
            # Where this account came from — mail_pool_ai, qre, finance, etc.
            "source": metadata.get("source") or "crm_spine",
            "created_at": account.get("created_at") or now,
            "updated_at": now,
        })
        stats["sales_accounts_adopted"] = stats.get("sales_accounts_adopted", 0) + 1


# Company-suffix words that mean a name is almost certainly an
# organisation, not a person — used only to widen the skip below to
# pre-existing docs that predate the name_is_person_fallback flag.
_COMPANY_SUFFIX_WORDS = _re.compile(
    r"\b(inc|ltd|llc|llp|corp|co|company|gmbh|pvt|plc|group|solutions|"
    r"consulting|research|technologies|technology|associates|partners|"
    r"industries|enterprises|international|global|services)\b",
    _re.IGNORECASE,
)


def _adopt_spine_contacts_into_legacy(legacy_contacts, crm_service, stats):
    """
    Spine contacts -> email_automation.contacts, so the Contacts page (which
    reads the legacy collection — routers/legacy_contacts.py — not the spine)
    shows contacts created any other way, including lead conversion
    (crm_service.convert_lead -> crm_db.contacts) and mail_pool_ai. Mirrors
    _adopt_spine_accounts_into_sales's pattern. Before this, crm_db.contacts
    held 2,779 real records while email_automation.contacts had 0 — the
    Contacts page had no working sync at all, unlike accounts (which at
    least had a periodic, if often-stale, one).
    """
    contacts = crm_service._col("contacts")
    accounts = crm_service._col("accounts")

    existing_ids = set(
        doc["crm_contact_id"]
        for doc in legacy_contacts.find(
            {"crm_contact_id": {"$exists": True}}, {"crm_contact_id": 1}
        )
        if doc.get("crm_contact_id")
    )

    for contact in contacts.find({"metadata.source_deleted": {"$ne": True}}).limit(5000):
        spine_id = str(contact["_id"])
        if spine_id in existing_ids:
            continue

        name = (contact.get("name") or "").strip()
        email = (contact.get("email") or "").strip()
        if not name and not email:
            continue

        company_name = None
        account_id = contact.get("account_id")
        if account_id:
            try:
                account = accounts.find_one({"_id": ObjectId(account_id)}, {"name": 1})
            except Exception:
                account = None
            if account:
                company_name = account.get("name")

        now = datetime.utcnow()
        legacy_contacts.insert_one({
            "name": name or email,
            "email": email,
            "phone": contact.get("phone"),
            "title": contact.get("title"),
            "companyName": company_name,
            "stage": "Contact",
            "crm_contact_id": spine_id,
            "crm_account_id": str(account_id) if account_id else None,
            "source": (contact.get("metadata") or {}).get("source") or "crm_spine",
            "createdAt": contact.get("created_at") or now,
            "updatedAt": now,
        })
        stats["legacy_contacts_adopted"] = stats.get("legacy_contacts_adopted", 0) + 1


def _looks_like_person_not_company(name: str) -> bool:
    """True when `name` reads as a bare human name (2-4 capitalised words,
    no company-suffix word, no digits) rather than an organisation."""
    name = (name or "").strip()
    if not name:
        return False
    if _COMPANY_SUFFIX_WORDS.search(name):
        return False
    words = name.replace(",", " ").split()
    return 1 < len(words) <= 4 and not any(ch.isdigit() for ch in name)


def _reconcile_party_collection(collection, party, crm_service, spine_connector,
                                stats):
    """Backfill + rename-sync one finance party collection (customers/vendors)."""
    # 1. Backfill docs that never got a back-reference. Skip ones that are
    # recorded as a person rather than a business — mirroring those into
    # crm_db.accounts is how a contact's own name ends up listed as a
    # "company" on the Accounts page. name_is_person_fallback is the
    # explicit flag (set at the point of creation, see
    # sales/mail_pool_ai.py::_log_rfq_and_estimate); the name-shape check
    # is a fallback for docs that predate that flag.
    for doc in collection.find({"crm_account_id": {"$exists": False},
                                "is_deleted": {"$ne": True}},
                               {"name": 1, "customer_type": 1,
                                "name_is_person_fallback": 1}).limit(2000):
        if doc.get("name_is_person_fallback") or doc.get("customer_type") == "individual":
            stats["skipped_person_name"] = stats.get("skipped_person_name", 0) + 1
            continue
        if _looks_like_person_not_company(doc.get("name") or ""):
            stats["skipped_person_name"] = stats.get("skipped_person_name", 0) + 1
            continue
        spine_id = spine_connector.mirror_finance_party_to_spine(
            doc.get("name"), party, source_id=str(doc["_id"]))
        if spine_id:
            collection.update_one({"_id": doc["_id"]},
                                  {"$set": {"crm_account_id": spine_id}})
            stats["backfilled"] += 1

    # 2. Propagate renames for docs that do have a back-reference.
    for doc in collection.find({"crm_account_id": {"$exists": True},
                                "is_deleted": {"$ne": True}},
                               {"name": 1, "crm_account_id": 1}):
        account = crm_service.get("accounts", doc["crm_account_id"])
        if account and doc.get("name") and account.get("name") != doc["name"]:
            spine_connector.update_spine_account(doc["crm_account_id"],
                                                 {"name": doc["name"]})
            stats["renamed"] += 1

    # 3. Flag deletions: soft-deleted docs whose spine account isn't flagged yet.
    for doc in collection.find({"crm_account_id": {"$exists": True},
                                "is_deleted": True},
                               {"crm_account_id": 1}):
        account = crm_service.get("accounts", doc["crm_account_id"])
        if account and not (account.get("metadata") or {}).get("source_deleted"):
            spine_connector.mark_spine_account_deleted(
                doc["crm_account_id"], f"finance_{party}")
            stats["deleted_flagged"] += 1


@celery_app.task(
    name="backend.tasks.crm_spine_tasks.reconcile_crm_spine",
    bind=True,
    max_retries=1,
    default_retry_delay=600,
)
def reconcile_crm_spine(self):
    """Nightly re-convergence of crm_db against the legacy source collections."""
    get_db, crm_service, spine_connector = _imports()
    stats = {"backfilled": 0, "renamed": 0, "deleted_flagged": 0,
             "qre_projects": 0}
    try:
        finance_db = get_db("finance_db")
        _reconcile_party_collection(finance_db["customers"], "client",
                                    crm_service, spine_connector, stats)
        _reconcile_party_collection(finance_db["vendors"], "vendor",
                                    crm_service, spine_connector, stats)

        # Sales accounts: backfill only (they have no soft-delete flag).
        sales_accounts = get_db("email_automation")["sales_accounts"]
        for doc in sales_accounts.find({"crm_account_id": {"$exists": False}},
                                       {"account_name": 1, "company_name": 1,
                                        "industry": 1}).limit(2000):
            spine_id = spine_connector.mirror_sales_account_to_spine(
                doc.get("company_name") or doc.get("account_name"),
                source_id=str(doc["_id"]),
                extra={"industry": doc.get("industry")})
            if spine_id:
                sales_accounts.update_one({"_id": doc["_id"]},
                                          {"$set": {"crm_account_id": spine_id}})
                stats["backfilled"] += 1

        # ...and the reverse, so accounts the mail pipeline discovered show up
        # on the Sales Account page instead of only on the spine.
        _adopt_spine_accounts_into_sales(sales_accounts, crm_service, stats)

        # Contacts: same reverse-adoption, into the Contacts page's legacy
        # collection — see _adopt_spine_contacts_into_legacy's docstring.
        legacy_contacts = get_db("email_automation")["contacts"]
        _adopt_spine_contacts_into_legacy(legacy_contacts, crm_service, stats)

        # Operations projects: backfill ones that predate the inline mirror.
        ops_projects = get_db("torpedo_settings")["projects"]
        for doc in ops_projects.find({"crm_project_id": {"$exists": False},
                                      "is_archived": {"$ne": True}},
                                     {"name": 1, "code": 1, "status": 1,
                                      "client_name": 1}).limit(2000):
            spine_id = spine_connector.mirror_ops_project_to_spine(
                doc, client_name=doc.get("client_name"),
                source_id=str(doc["_id"]))
            if spine_id:
                ops_projects.update_one({"_id": doc["_id"]},
                                        {"$set": {"crm_project_id": spine_id}})
                stats["backfilled"] += 1

        # QRE bridge: every study becomes a spine project (idempotent on
        # metadata.source_id — QRE study ids are stable strings).
        try:
            studies = get_db(QRE_DB_NAME)["studies"]
            projects = crm_service._col("projects")
            for study in studies.find({}, {"name": 1, "type": 1, "status": 1,
                                           "client": 1}):
                sid = str(study["_id"])
                if projects.find_one({"metadata.source": "qre",
                                      "metadata.source_id": sid}, {"_id": 1}):
                    continue
                account_id = None
                client_name = (study.get("client") or "").strip() \
                    if isinstance(study.get("client"), str) else None
                if client_name:
                    account, _ = crm_service.get_or_create_account(
                        client_name, defaults={"account_type": "client",
                                               "metadata": {"source": "qre"}})
                    account_id = account["_id"]
                doc = crm_service.create("projects", {
                    "name": study.get("name") or sid,
                    "account_id": account_id,
                    "status": study.get("status") or "active",
                    "metadata": {"source": "qre", "source_id": sid,
                                 "study_type": study.get("type")},
                })
                crm_service.log_activity({
                    "type": "project_created",
                    "object_type": "project",
                    "object_id": doc["_id"],
                    "project_id": doc["_id"],
                    "account_id": account_id,
                    "summary": f"QRE study bridged: {doc.get('name')}",
                    "at": datetime.utcnow().isoformat(),
                })
                stats["qre_projects"] += 1
        except Exception as qre_err:
            logger.warning(f"[spine-reconcile] QRE bridge skipped: {qre_err}")

        # CRM notifications: overdue tasks and stale open opportunities.
        # dedupe_key keeps at most one UNREAD notification per record, so the
        # nightly run never piles up repeats.
        try:
            now = datetime.utcnow()
            for task_doc in crm_service._col("tasks").find(
                    {"status": {"$ne": "done"},
                     "due_date": {"$lt": now}}).limit(500):
                tid = str(task_doc["_id"])
                crm_service.notify(
                    "task_overdue",
                    f"Task overdue: {task_doc.get('title', tid)}",
                    link_object_type="task", link_object_id=tid,
                    owner=task_doc.get("owner_id"),
                    dedupe_key=f"task_overdue_{tid}")
                stats["notifications"] = stats.get("notifications", 0) + 1

            from datetime import timedelta as _td
            stale_cutoff = now - _td(days=14)
            for opp in crm_service._col("opportunities").find(
                    {"status": "open",
                     "updated_at": {"$lt": stale_cutoff}}).limit(500):
                oid = str(opp["_id"])
                crm_service.notify(
                    "opportunity_stale",
                    f"Opportunity idle 14+ days: {opp.get('title', oid)} "
                    f"(stage: {opp.get('stage')})",
                    link_object_type="opportunity", link_object_id=oid,
                    owner=opp.get("owner"),
                    dedupe_key=f"opp_stale_{oid}")
                stats["notifications"] = stats.get("notifications", 0) + 1
        except Exception as notif_err:
            logger.warning(f"[spine-reconcile] notifications skipped: {notif_err}")

        logger.info(f"[spine-reconcile] done: {stats}")
        return {"status": "ok", **stats}
    except Exception as e:
        logger.error(f"[spine-reconcile] failed: {e}", exc_info=True)
        raise self.retry(exc=e)
