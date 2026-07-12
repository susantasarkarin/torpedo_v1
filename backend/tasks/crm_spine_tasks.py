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
from datetime import datetime

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


def _reconcile_party_collection(collection, party, crm_service, spine_connector,
                                stats):
    """Backfill + rename-sync one finance party collection (customers/vendors)."""
    # 1. Backfill docs that never got a back-reference.
    for doc in collection.find({"crm_account_id": {"$exists": False},
                                "is_deleted": {"$ne": True}},
                               {"name": 1}).limit(2000):
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

        logger.info(f"[spine-reconcile] done: {stats}")
        return {"status": "ok", **stats}
    except Exception as e:
        logger.error(f"[spine-reconcile] failed: {e}", exc_info=True)
        raise self.retry(exc=e)
