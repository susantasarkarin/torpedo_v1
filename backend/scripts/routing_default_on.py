"""Switch "Accept routed respondents and panel members" on for every project (2026-11-28).

New projects are created with it on; this brings existing ones in line. Projects
only receive traffic while Live (survey_routing.routable_projects), so turning it
on for closed / paused projects sends nobody there.

    cd backend && ./venv/bin/python scripts/routing_default_on.py           # dry run
    cd backend && ./venv/bin/python scripts/routing_default_on.py --apply
"""
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

import db  # noqa: E402
from database import DB_EMAIL_AUTOMATION  # noqa: E402


def main(apply: bool) -> None:
    projects = db.by_name(DB_EMAIL_AUTOMATION)["projects"]
    query = {"is_deleted": {"$ne": True}, "routingEnabled": {"$ne": True}}
    docs = list(projects.find(query, {"surveyNo": 1, "projectStatus": 1}))
    live = [d for d in docs if str(d.get("projectStatus") or "").strip().lower() == "live"]
    print(f"{len(docs)} projects have routing off or unset ({len(live)} of them Live): "
          + ", ".join(str(d.get("surveyNo")) for d in live))
    if not apply:
        print("Dry run. Add --apply to switch them on.")
        return
    res = projects.update_many(query, {"$set": {"routingEnabled": True,
                                                "routingDefaultOnAt": datetime.utcnow()}})
    print(f"Switched on: {res.modified_count}")


if __name__ == "__main__":
    main("--apply" in sys.argv)
