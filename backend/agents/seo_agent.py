"""
SEO AGENT  (Phase 5 — SEO intelligence; SCAFFOLD pending credentials)

Per the master plan: "SEO intelligence using AI + Google Analytics + website +
Google Search Console". The analysis logic (`seo_recommendations`) is fully
implemented and unit-tested, but the DATA SOURCE needs credentials:
  - Google Search Console API (impressions/clicks/CTR/position per page)
  - Google Analytics (sessions/conversions)
The `metrics_provider` is pluggable; the default returns None until
GSC_CREDENTIALS_JSON / GA_PROPERTY_ID (or similar) are configured — so the agent
runs as a graceful no-op rather than failing. Inject a provider (or real creds)
to activate it.

Usage:
    python -m backend.agents.seo_agent --dry-run
    # (needs GSC/GA credentials + a provider implementation to produce data)
"""

import os
import argparse
from typing import Optional, Dict, Any, List, Callable

try:
    from ..app.services import ai_engine
except ImportError:  # pragma: no cover - absolute import / CLI fallback
    from app.services import ai_engine

AGENT_NAME = "seo_agent"

LOW_CTR_THRESHOLD = 0.02   # < 2% CTR with real impressions = title/meta opportunity
MIN_IMPRESSIONS = 100


def seo_recommendations(pages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Pure analysis: turn per-page GSC metrics into SEO recommendations. No I/O."""
    recs: List[Dict[str, Any]] = []
    for p in pages or []:
        url = p.get("url") or p.get("page")
        impressions = float(p.get("impressions") or 0)
        clicks = float(p.get("clicks") or 0)
        ctr = p.get("ctr")
        if ctr is None:
            ctr = (clicks / impressions) if impressions else 0.0
        ctr = float(ctr)
        position = float(p.get("position") or 0)

        if impressions >= MIN_IMPRESSIONS and ctr < LOW_CTR_THRESHOLD:
            recs.append({
                "url": url, "issue": "low_ctr",
                "action": "Improve title tag & meta description to lift CTR",
                "impressions": impressions, "ctr": round(ctr, 4),
            })
        elif 10 < position <= 20 and impressions >= 50:
            recs.append({
                "url": url, "issue": "page_two",
                "action": "Strengthen content/internal links to reach page 1",
                "position": position,
            })
    return recs


def _default_provider() -> Optional[List[Dict[str, Any]]]:
    """Real GSC/GA fetch goes here. Returns None until credentials are configured."""
    if not (os.getenv("GSC_CREDENTIALS_JSON") or os.getenv("GA_PROPERTY_ID")):
        return None
    # TODO: implement Google Search Console / Analytics fetch using the creds.
    return None


def run(
    metrics_provider: Optional[Callable[[], Optional[List[Dict[str, Any]]]]] = None,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """Fetch SEO metrics (if available) and log recommendations. Graceful no-op without creds."""
    provider = metrics_provider or _default_provider
    pages = provider()

    stats = {"agent": AGENT_NAME, "dry_run": dry_run, "pages": 0,
             "recommendations": 0, "status": "ok", "decision_id": None}

    if not pages:
        stats["status"] = "no_data"  # no credentials/provider configured yet
        return stats

    stats["pages"] = len(pages)
    recs = seo_recommendations(pages)
    stats["recommendations"] = len(recs)

    if recs and not dry_run:
        out = ai_engine.submit_decision(
            AGENT_NAME,
            decision=f"{len(recs)} SEO opportunities identified across {len(pages)} pages",
            reason="Low-CTR and page-two pages from Search Console metrics.",
            autonomy_mode="observe",
            risk="low",
            input_summary={"recommendations": recs[:20]},
        )
        stats["decision_id"] = out["decision"]["_id"]
    return stats


def main():
    parser = argparse.ArgumentParser(description="SEO intelligence agent (needs GSC/GA credentials).")
    parser.add_argument("--execute", action="store_true", help="Log recommendations (default dry-run).")
    args = parser.parse_args()
    stats = run(dry_run=not args.execute)
    print("\n=== SEO agent ===")
    for k, v in stats.items():
        print(f"  {k}: {v}")
    if stats["status"] == "no_data":
        print("  (no GSC/GA credentials configured — agent is a no-op until set)")


if __name__ == "__main__":
    main()
