"""Daily: does the SFW respondent score predict client rejections? (quality.validation)

    venv/bin/python scripts/quality_validation.py [--days 180]

Read-only on traffic; stores one report in traffic_flow_db.quality_validation
and prints the summary. Cron: /opt/crm-ops (10:00 IST).
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=180)
    a = ap.parse_args()
    from database import DB_TRAFFIC, get_database
    from quality import validation
    rep = validation.run(get_database(DB_TRAFFIC), days=a.days)
    out = {k: rep[k] for k in ("at", "reconciled_surveys", "scored_completes_in_window", "completes", "rejected",
                               "baseline_rejection_rate", "note")}
    out["enforce_candidates"] = [f for f, r in rep["by_flag"].items() if r["enforce_candidate"]]
    out["by_band"] = rep["by_band"]
    print(json.dumps(out, default=str, indent=1))


if __name__ == "__main__":
    main()
