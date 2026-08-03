"""
BACKFILL & ENRICH EXISTING LEADS
=================================

Runs over every lead already in `leads_raw` and:

1. Re-scores it against the active ICPs using the corrected filter-based
   matching (title 3 / industry 2 / country 2 / seniority 1, threshold > 3,
   including the BIM title guard) — see icp_config.classify_lead_by_icp.
2. Enriches records missing company / title / industry / country by running a
   targeted Google CSE search and passing the results through the existing AI
   extraction path (ingestion.extract_leads_from_google_results), which is now
   Bedrock-backed. The existing 24-hour CSE quota back-off is respected.
3. Re-syncs the record to `leads_enriched`.

All existing safety rules are preserved by reusing canonical_ingestion:
  - AI-guessed emails are stripped unless the domain has a verified pattern
  - records with no name or no real LinkedIn URL are discarded
  - dedup by email first, then linkedin_url
  - merges into the existing record, never duplicates (never overwrites
    non-null with null)

Idempotent and resumable: progress is checkpointed to disk after every batch,
so re-running continues where it stopped. `--dry-run` (the default is live;
pass --dry-run explicitly) reports what would change without writing.

Usage:
    python -m leads.backfill_enrich --dry-run
    python -m leads.backfill_enrich --limit 500
    python -m leads.backfill_enrich --no-enrich          # re-score only
    python -m leads.backfill_enrich --reset              # discard checkpoint
"""

import argparse
import asyncio
import json
import logging
import os
import sys
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from bson import ObjectId
from pymongo import MongoClient

try:
    from .canonical_ingestion import (
        _strip_guessed_email_if_unverified,
        deduplicate_and_merge,
        determine_lead_bracket,
        is_unknown_company,
        needs_enrichment,
        sync_to_enriched,
    )
    from .icp_config import classify_lead_by_icp, get_active_icps, score_lead_against_icp
except ImportError:  # script context
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from leads.canonical_ingestion import (
        _strip_guessed_email_if_unverified,
        deduplicate_and_merge,
        determine_lead_bracket,
        is_unknown_company,
        needs_enrichment,
        sync_to_enriched,
    )
    from leads.icp_config import classify_lead_by_icp, get_active_icps, score_lead_against_icp

logger = logging.getLogger("backfill_enrich")

MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/")
_client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
_db = _client["email_automation"]
leads_raw = _db["leads_raw"]

DEFAULT_CHECKPOINT = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), ".backfill_checkpoint.json")

# Fields whose absence makes a lead worth an enrichment search.
ENRICHABLE_FIELDS = ("company", "title", "company_industry", "country")

# Pace CSE calls; the 24h 429 back-off in ingestion is respected on top of this.
ENRICH_DELAY_SECONDS = 3
BATCH_SIZE = 100


# ============================================================
# CHECKPOINT
# ============================================================

class Checkpoint:
    """Resumable progress marker. Stores the last processed _id."""

    def __init__(self, path: str):
        self.path = path
        self.last_id: Optional[str] = None
        self.processed = 0
        self.started_at = datetime.utcnow().isoformat()
        self.load()

    def load(self) -> None:
        if not os.path.exists(self.path):
            return
        try:
            with open(self.path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            self.last_id = data.get("last_id")
            self.processed = int(data.get("processed", 0))
            self.started_at = data.get("started_at", self.started_at)
            logger.info("Resuming from checkpoint: %d already processed, last_id=%s",
                        self.processed, self.last_id)
        except Exception as e:
            logger.warning("Could not read checkpoint (%s) — starting fresh: %s",
                           self.path, e)

    def save(self, last_id: str, processed: int) -> None:
        self.last_id = last_id
        self.processed = processed
        tmp = self.path + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump({
                    "last_id": last_id,
                    "processed": processed,
                    "started_at": self.started_at,
                    "updated_at": datetime.utcnow().isoformat(),
                }, fh)
            os.replace(tmp, self.path)  # atomic
        except Exception as e:
            logger.warning("Could not write checkpoint: %s", e)

    def clear(self) -> None:
        try:
            if os.path.exists(self.path):
                os.remove(self.path)
                logger.info("Checkpoint cleared")
        except Exception as e:
            logger.warning("Could not clear checkpoint: %s", e)


# ============================================================
# SAFETY RULES
# ============================================================

def has_valid_identity(lead: Dict[str, Any]) -> bool:
    """
    Discard rule: a lead must have a name AND a real LinkedIn /in/ URL, or an
    email. Mirrors the ingestion-time guarantee.
    """
    has_name = bool(lead.get("first_name") or lead.get("name"))
    url = (lead.get("linkedin_url") or "").lower()
    has_real_linkedin = "linkedin.com/in/" in url
    has_email = bool(lead.get("email"))

    if has_email:
        return True
    return has_name and has_real_linkedin


def has_scoring_signal(lead: Dict[str, Any]) -> bool:
    """
    True when the lead carries at least one signal beyond job title.

    The ICP threshold is score > 3 and a title match is worth exactly 3, so a
    title-only record can never be classified. Re-scoring such a record would
    just stamp it 'unknown' and destroy any segment already on it, so callers
    skip the segment write instead.
    """
    return any(lead.get(f) for f in (
        "company_industry", "industry",
        "location", "country", "inferred_location", "company_headquarters",
        "seniority_level",
    ))


def derive_name_parts(lead: Dict[str, Any]) -> Dict[str, Any]:
    """
    Split `name` into first/last when they are missing. Free (no API call) and
    feeds determine_lead_bracket, which needs first_name to reach 'contact'.
    Titles and honorifics after a comma are dropped.
    """
    if lead.get("first_name"):
        return {}
    raw = (lead.get("name") or "").strip()
    if not raw:
        return {}

    # "Piyul Mukherjee, PhD" -> "Piyul Mukherjee"
    raw = raw.split(",")[0].strip()
    parts = [p for p in raw.split() if p]
    if not parts:
        return {}

    out: Dict[str, Any] = {"first_name": parts[0]}
    if len(parts) > 1:
        out["last_name"] = " ".join(parts[1:])
    return out


def scrub_enrichment(candidate: Dict[str, Any]) -> Dict[str, Any]:
    """
    Apply ingestion safety rules to freshly-extracted data before merging:
    drop guessed emails, drop placeholder companies, drop empty values.
    """
    cleaned: Dict[str, Any] = {}

    for key, value in candidate.items():
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        cleaned[key] = value.strip() if isinstance(value, str) else value

    # Never let an AI-guessed email through unverified.
    cleaned.pop("email_candidate", None)
    if cleaned.get("email"):
        _strip_guessed_email_if_unverified(cleaned)
        if not cleaned.get("email"):
            cleaned.pop("email", None)

    # Placeholder companies are worse than no company.
    if "company" in cleaned and is_unknown_company(cleaned["company"]):
        cleaned.pop("company")
    if "company_name" in cleaned and is_unknown_company(cleaned["company_name"]):
        cleaned.pop("company_name")

    return cleaned


# ============================================================
# RE-SCORING
# ============================================================

def rescore(lead: Dict[str, Any], active_icps: List[Dict[str, Any]]) -> Tuple[str, int]:
    """Re-run ICP classification. Returns (slug, best_score)."""
    slug = classify_lead_by_icp(lead, active_icps)
    best = 0
    for icp in active_icps:
        if icp.get("slug") == slug:
            best = score_lead_against_icp(lead, icp)
            break
    return slug, best


# ============================================================
# ENRICHMENT
# ============================================================

def missing_fields(lead: Dict[str, Any]) -> List[str]:
    return [f for f in ENRICHABLE_FIELDS if not lead.get(f)]


def build_enrichment_query(lead: Dict[str, Any]) -> Optional[str]:
    """
    Targeted query for one lead. Prefers the LinkedIn URL (exact profile),
    falling back to name + company.
    """
    url = (lead.get("linkedin_url") or "").strip()
    if "linkedin.com/in/" in url.lower():
        slug = url.rstrip("/").split("/")[-1]
        if slug:
            return f'site:linkedin.com/in/ "{slug}"'

    name = (lead.get("name")
            or " ".join(p for p in [lead.get("first_name"), lead.get("last_name")] if p)).strip()
    if not name:
        return None
    company = lead.get("company") or lead.get("company_name") or ""
    return f'site:linkedin.com/in/ "{name}" {company}'.strip()


async def enrich_one(lead: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Run one targeted search and extract fields via the Bedrock path.
    Returns scrubbed enrichment data, or None if nothing usable was found.
    Respects the 24-hour CSE quota back-off inside perform_google_search.
    """
    try:
        from .ingestion import (
            _is_cse_paused,
            extract_leads_from_google_results,
            perform_google_search,
        )
    except ImportError:
        from leads.ingestion import (
            _is_cse_paused,
            extract_leads_from_google_results,
            perform_google_search,
        )

    if _is_cse_paused():
        logger.info("CSE in 24h cooldown — skipping enrichment")
        return None

    query = build_enrichment_query(lead)
    if not query:
        return None

    results = await perform_google_search(query, num_results=3)
    if not results:
        return None

    extracted = await extract_leads_from_google_results(results, query)
    if not extracted:
        return None

    # Prefer the result whose LinkedIn URL matches this lead.
    target_url = (lead.get("linkedin_url") or "").rstrip("/").lower()
    best = None
    for candidate in extracted:
        cand_url = (candidate.get("linkedin_url") or "").rstrip("/").lower()
        if target_url and cand_url == target_url:
            best = candidate
            break
    if best is None:
        best = extracted[0]

    # Map extraction output onto the canonical field names, keeping only the
    # fields that were actually missing.
    field_map = {
        "company": best.get("company_name"),
        "title": best.get("title"),
        "company_industry": best.get("company_industry"),
        "country": best.get("location"),
        "company_domain": best.get("company_domain"),
        "seniority_level": best.get("seniority_level"),
    }
    wanted = {k: v for k, v in field_map.items() if v and not lead.get(k)}
    return scrub_enrichment(wanted) if wanted else None


# ============================================================
# BATCH MODE (Bedrock batch inference — 50% cheaper, not time-sensitive)
# ============================================================
# Three phases:
#   A. gather   — run the (CSE-limited) Google searches, write extraction
#                 prompts as JSONL records keyed by lead _id
#   B. submit   — hand the JSONL to bedrock_client (S3 + batch job), poll
#   C. ingest   — map results back to leads by record id, then apply the SAME
#                 scrub/merge/rescore path as on-demand mode
# On-demand mode remains the default and is right for small runs.

def _apply_enrichment_and_rescore(lead: Dict[str, Any],
                                  extracted: Optional[Dict[str, Any]],
                                  active_icps: List[Dict[str, Any]],
                                  dry_run: bool,
                                  stats: Dict[str, int]) -> None:
    """Shared tail of both modes: scrub -> merge -> rescore -> write -> sync."""
    lead_id = str(lead["_id"])
    updates: Dict[str, Any] = derive_name_parts(lead)
    if updates:
        stats["names_split"] += 1

    if extracted:
        field_map = {
            "company": extracted.get("company_name") or extracted.get("company"),
            "title": extracted.get("title"),
            "company_industry": extracted.get("company_industry"),
            "country": extracted.get("location") or extracted.get("country"),
            "company_domain": extracted.get("company_domain"),
            "seniority_level": extracted.get("seniority_level"),
        }
        wanted = {k: v for k, v in field_map.items() if v and not lead.get(k)}
        cleaned = scrub_enrichment(wanted) if wanted else {}
        if cleaned:
            merged = deduplicate_and_merge(lead, cleaned)
            for key, value in cleaned.items():
                if merged.get(key) == value and lead.get(key) != value:
                    updates[key] = value
            if updates:
                stats["enriched"] += 1

    view = dict(lead)
    view.update(updates)

    if has_scoring_signal(view):
        new_segment, score = rescore(view, active_icps)
        stats["rescored"] += 1
        if new_segment != lead.get("icp_segment"):
            stats["segment_changed"] += 1
        updates["icp_segment"] = new_segment
        updates["icp_score"] = score
    else:
        stats["skipped_no_signal"] += 1

    view.update(updates)
    updates["lead_bracket"] = determine_lead_bracket(view)
    updates["enrichment_status"] = "needed" if needs_enrichment(view) else "skipped"

    meaningful = {k: v for k, v in updates.items() if lead.get(k) != v}
    if not meaningful:
        stats["unchanged"] += 1
    elif dry_run:
        logger.info("lead=%s WOULD UPDATE %s", lead_id, sorted(meaningful.keys()))
    else:
        meaningful["updated_at"] = datetime.utcnow()
        meaningful["backfill_status"] = "done"
        leads_raw.update_one({"_id": lead["_id"]}, {"$set": meaningful})
        stats["written"] += 1
        view.update(meaningful)
        try:
            sync_to_enriched(view, lead_id)
        except Exception as e:
            logger.warning("lead=%s sync_to_enriched failed: %s", lead_id, e)


async def run_batch(dry_run: bool = False, limit: Optional[int] = None,
                    poll_interval: int = 300) -> Dict[str, int]:
    """Batch-inference variant of the enrichment pass."""
    try:
        from .bedrock_client import (
            build_batch_records, fetch_batch_results, poll_batch_job,
            submit_batch_job, validate_model_access)
        from .ingestion import (
            EXTRACTION_SYSTEM_PROMPT, _is_cse_paused, build_extraction_prompt,
            parse_extracted_leads, perform_google_search)
    except ImportError:
        from leads.bedrock_client import (
            build_batch_records, fetch_batch_results, poll_batch_job,
            submit_batch_job, validate_model_access)
        from leads.ingestion import (
            EXTRACTION_SYSTEM_PROMPT, _is_cse_paused, build_extraction_prompt,
            parse_extracted_leads, perform_google_search)

    validate_model_access(("cheap",))  # fail fast before burning CSE quota

    stats = {
        "scanned": 0, "discarded": 0, "rescored": 0, "segment_changed": 0,
        "enriched": 0, "enrich_attempted": 0, "unchanged": 0, "errors": 0,
        "written": 0, "names_split": 0, "skipped_no_signal": 0,
        "batch_records": 0, "batch_results": 0,
    }

    # --- Phase A: gather searches and build prompt records ---------------
    items: List[Tuple[str, str, str]] = []
    lead_by_id: Dict[str, Dict[str, Any]] = {}

    cursor = leads_raw.find({}).sort("_id", 1)
    if limit:
        cursor = cursor.limit(limit)

    for lead in cursor:
        stats["scanned"] += 1
        if not has_valid_identity(lead):
            stats["discarded"] += 1
            continue
        if not missing_fields(lead):
            # Nothing to enrich — still gets the free name-split/rescore pass.
            _apply_enrichment_and_rescore(lead, None, get_active_icps(),
                                          dry_run, stats)
            continue
        if _is_cse_paused():
            logger.warning("CSE in 24h cooldown — stopping gather phase")
            break

        query = build_enrichment_query(lead)
        if not query:
            continue
        results = await perform_google_search(query, num_results=3)
        stats["enrich_attempted"] += 1
        await asyncio.sleep(ENRICH_DELAY_SECONDS)
        if not results:
            continue

        lead_id = str(lead["_id"])
        items.append((lead_id, EXTRACTION_SYSTEM_PROMPT,
                      build_extraction_prompt(results, query)))
        lead_by_id[lead_id] = lead

    if not items:
        logger.info("batch mode: nothing to submit")
        return stats

    stats["batch_records"] = len(items)
    jsonl = build_batch_records(items, role="cheap")

    if dry_run:
        preview_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            ".backfill_batch_preview.jsonl")
        with open(preview_path, "w", encoding="utf-8") as fh:
            fh.write("\n".join(jsonl))
        logger.info("DRY RUN: %d batch records written to %s — no job submitted",
                    len(jsonl), preview_path)
        return stats

    # --- Phase B: submit and poll ----------------------------------------
    job = submit_batch_job(jsonl, role="cheap")
    status = poll_batch_job(job["job_arn"], interval_seconds=poll_interval)
    if status != "Completed":
        logger.error("batch job ended %s — nothing ingested", status)
        stats["errors"] += 1
        return stats

    # --- Phase C: ingest --------------------------------------------------
    results_by_id = fetch_batch_results(job["output_prefix"])
    active_icps = get_active_icps()

    for record_id, data in results_by_id.items():
        lead = lead_by_id.get(record_id)
        if lead is None:
            continue
        stats["batch_results"] += 1
        extracted_leads = parse_extracted_leads(data) if data else []
        # Prefer the record matching this lead's LinkedIn URL, like on-demand.
        target = (lead.get("linkedin_url") or "").rstrip("/").lower()
        best = None
        for candidate in extracted_leads:
            if (candidate.get("linkedin_url") or "").rstrip("/").lower() == target:
                best = candidate
                break
        if best is None and extracted_leads:
            best = extracted_leads[0]
        _apply_enrichment_and_rescore(lead, best, active_icps, False, stats)

    return stats


# ============================================================
# MAIN PASS
# ============================================================

async def run(dry_run: bool = False, limit: Optional[int] = None,
              do_enrich: bool = True, checkpoint_path: str = DEFAULT_CHECKPOINT,
              reset: bool = False) -> Dict[str, int]:

    checkpoint = Checkpoint(checkpoint_path)
    if reset:
        checkpoint.clear()
        checkpoint.last_id = None
        checkpoint.processed = 0

    active_icps = get_active_icps()
    if not active_icps:
        logger.error("No active ICPs configured — nothing to score against")
        return {}

    stats = {
        "scanned": 0, "discarded": 0, "rescored": 0, "segment_changed": 0,
        "enriched": 0, "enrich_attempted": 0, "unchanged": 0, "errors": 0,
        "written": 0, "names_split": 0, "skipped_no_signal": 0,
    }

    query: Dict[str, Any] = {}
    if checkpoint.last_id:
        query["_id"] = {"$gt": ObjectId(checkpoint.last_id)}

    cursor = leads_raw.find(query).sort("_id", 1)
    if limit:
        cursor = cursor.limit(limit)

    processed = checkpoint.processed
    last_id = checkpoint.last_id

    for lead in cursor:
        stats["scanned"] += 1
        lead_id = str(lead["_id"])
        last_id = lead_id
        processed += 1

        try:
            # --- Safety: discard identity-less records ------------------
            if not has_valid_identity(lead):
                stats["discarded"] += 1
                logger.info("lead=%s discarded: no name/linkedin and no email", lead_id)
                if not dry_run:
                    leads_raw.update_one(
                        {"_id": lead["_id"]},
                        {"$set": {"backfill_status": "discarded_no_identity",
                                  "updated_at": datetime.utcnow()}})
                continue

            # --- Free enrichment: split name into first/last --------------
            updates: Dict[str, Any] = derive_name_parts(lead)
            if updates:
                stats["names_split"] += 1

            # --- Enrichment ---------------------------------------------
            gaps = missing_fields(lead)
            if do_enrich and gaps:
                stats["enrich_attempted"] += 1
                enrichment = await enrich_one(lead)
                if enrichment:
                    # Merge semantics: never overwrite non-null with null.
                    merged = deduplicate_and_merge(lead, enrichment)
                    for key, value in enrichment.items():
                        if merged.get(key) == value and lead.get(key) != value:
                            updates[key] = value
                    if updates:
                        stats["enriched"] += 1
                        logger.info("lead=%s enriched fields=%s",
                                    lead_id, sorted(updates.keys()))
                await asyncio.sleep(ENRICH_DELAY_SECONDS)

            # --- Re-score on the post-enrichment view --------------------
            view = dict(lead)
            view.update(updates)

            if has_scoring_signal(view):
                new_segment, score = rescore(view, active_icps)
                old_segment = lead.get("icp_segment")
                stats["rescored"] += 1

                if new_segment != old_segment:
                    stats["segment_changed"] += 1
                    logger.info("lead=%s icp_segment %s -> %s (score=%d)",
                                lead_id, old_segment, new_segment, score)
                updates["icp_segment"] = new_segment
                updates["icp_score"] = score
            else:
                # Title-only record: cannot clear the >3 threshold, so scoring
                # it would only wipe any existing segment. Leave it alone.
                stats["skipped_no_signal"] += 1
                logger.info("lead=%s scoring skipped: no industry/country/"
                            "seniority signal (title-only)", lead_id)

            # --- Derived fields ------------------------------------------
            view.update(updates)
            updates["lead_bracket"] = determine_lead_bracket(view)
            updates["enrichment_status"] = "needed" if needs_enrichment(view) else "skipped"

            # Nothing meaningful changed?
            meaningful = {k: v for k, v in updates.items()
                          if lead.get(k) != v}
            if not meaningful:
                stats["unchanged"] += 1
            elif dry_run:
                logger.info("lead=%s WOULD UPDATE %s", lead_id, sorted(meaningful.keys()))
            else:
                meaningful["updated_at"] = datetime.utcnow()
                meaningful["backfill_status"] = "done"
                leads_raw.update_one({"_id": lead["_id"]}, {"$set": meaningful})
                stats["written"] += 1
                view.update(meaningful)
                try:
                    sync_to_enriched(view, lead_id)
                except Exception as e:
                    logger.warning("lead=%s sync_to_enriched failed: %s", lead_id, e)

        except Exception as e:
            stats["errors"] += 1
            logger.error("lead=%s backfill failed: %s", lead_id, e)

        # --- Checkpoint ------------------------------------------------
        if not dry_run and stats["scanned"] % BATCH_SIZE == 0:
            checkpoint.save(last_id, processed)
            logger.info("checkpoint saved at %d processed", processed)

    if not dry_run and last_id:
        checkpoint.save(last_id, processed)

    return stats


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill and enrich existing leads")
    parser.add_argument("--dry-run", action="store_true",
                        help="report what would change without writing")
    parser.add_argument("--limit", type=int, default=None,
                        help="process at most N leads")
    parser.add_argument("--no-enrich", action="store_true",
                        help="re-score only; make no search calls")
    parser.add_argument("--batch", action="store_true",
                        help="use Bedrock batch inference (50%% cheaper; "
                             "needs BEDROCK_BATCH_S3_BUCKET + _ROLE_ARN)")
    parser.add_argument("--checkpoint", default=DEFAULT_CHECKPOINT,
                        help="checkpoint file path")
    parser.add_argument("--reset", action="store_true",
                        help="discard the checkpoint and start from the beginning")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s")

    if args.dry_run:
        logger.info("DRY RUN — no writes will be made")

    if args.batch:
        if args.no_enrich:
            logger.error("--batch and --no-enrich are contradictory")
            return 2
        stats = asyncio.run(run_batch(dry_run=args.dry_run, limit=args.limit))
    else:
        stats = asyncio.run(run(
            dry_run=args.dry_run,
            limit=args.limit,
            do_enrich=not args.no_enrich,
            checkpoint_path=args.checkpoint,
            reset=args.reset,
        ))

    logger.info("=== backfill complete ===")
    for key in sorted(stats):
        logger.info("  %-18s %d", key, stats[key])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
