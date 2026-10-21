"""
Companies waiting for a person: the industry was found (website / LinkedIn)
but the AI did not confirm it, so nobody there is mailed (leads/company_fit.py).

    python scripts/company_review.py                      # list, most-needed first
    python scripts/company_review.py approve <id>          # accept the found type
    python scripts/company_review.py set <id> <type>       # mr_agency | brand | aec | other
    python scripts/company_review.py set-name "<name>" <type>   # any company, by name

Setting a type re-baskets that company's leads; the ICP job then moves and
mails them within 10 minutes.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))
from pymongo import MongoClient  # noqa: E402

from leads import company_fit as cf  # noqa: E402


def main(argv):
    client = MongoClient(os.getenv("MONGO_URI") or "mongodb://localhost:27017/")
    col = client["email_automation"][cf.COLLECTION]
    if not argv:
        for d in col.find({"status": "review"}).sort("priority", -1):
            print(f"{d['_id']:40} {d.get('name', '')[:30]:30} found {d.get('proposed_type'):9} "
                  f"| {(d.get('evidence') or '')[:50]}")
        return
    if argv[0] == "approve":
        d = col.find_one({"_id": argv[1]}) or sys.exit(f"no company {argv[1]}")
        print(cf.set_type(d.get("name") or "", d.get("domain") or "", d["proposed_type"], client=client))
    elif argv[0] == "set":
        d = col.find_one({"_id": argv[1]}) or sys.exit(f"no company {argv[1]}")
        print(cf.set_type(d.get("name") or "", d.get("domain") or "", argv[2], client=client))
    elif argv[0] == "set-name":
        print(cf.set_type(argv[1], "", argv[2], client=client))
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
