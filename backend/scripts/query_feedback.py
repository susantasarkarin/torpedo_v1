"""Lead-search feedback cycle (see leads/query_feedback.py).

    venv/bin/python scripts/query_feedback.py            # dry run: what it would change per ICP
    venv/bin/python scripts/query_feedback.py --apply    # writes email_automation.icp_search_hints (additive; rollback = set enabled false)
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    from leads.query_feedback import run_cycle
    for row in run_cycle(apply=a.apply):
        print(("APPLIED" if a.apply else "DRY RUN"), row)


if __name__ == "__main__":
    main()
