"""Read-only Gmail header probe for the deliverability audit (Phase 1.4a).

For each connected Workspace mailbox:
  * inbound mail from our OTHER domains -> Gmail's Authentication-Results
    (real spf / dkim header.d / dmarc verdicts for our own sending);
  * the 3 most recent SENT messages -> which headers we set
    (List-Unsubscribe, List-Unsubscribe-Post, multipart/html) and body features
    (links, images, tracking pixels, attachments). No body text is printed.
Uses the app's own service-account delegation, metadata/full GET only.
"""
import base64
import collections
import os
import re
import sys

sys.path.insert(0, os.getcwd())
from googleapiclient.discovery import build  # noqa: E402
from pymongo import MongoClient  # noqa: E402

from app.services.gmail_workspace_service import GmailWorkspaceService  # noqa: E402

OURS = ("surveyfieldwork.com", "cogentixresearch.com", "bimwavesolutions.com")


def mask(e):
    u, _, d = (e or "").partition("@")
    return f"{u[:2]}***@{d}" if d else e


def hdr(msg, name):
    return [h["value"] for h in msg["payload"].get("headers", []) if h["name"].lower() == name.lower()]


def walk(part, acc):
    mt = part.get("mimeType", "")
    acc["types"].add(mt)
    if part.get("filename"):
        acc["attachments"] += 1
    data = part.get("body", {}).get("data")
    if data and mt in ("text/html", "text/plain"):
        txt = base64.urlsafe_b64decode(data + "==").decode("utf-8", "ignore")
        if mt == "text/html":
            acc["links"] = max(acc["links"], len(re.findall(r"<a\s", txt, re.I)))
            acc["imgs"] += len(re.findall(r"<img\s", txt, re.I))
            acc["pixel"] |= bool(re.search(r"<img[^>]+(width=.?1\D|height=.?1\D|/track|/open|pixel)", txt, re.I))
        else:
            acc["plain_links"] = max(acc["plain_links"], len(re.findall(r"https?://", txt)))
    for p in part.get("parts", []) or []:
        walk(p, acc)


def main():
    mongo = os.environ["MONGO_URI"]
    svc = GmailWorkspaceService(mongo)
    boxes = [d.get("email") for d in MongoClient(mongo).torpedo_gmail.workspace_mailboxes.find({}, {"email": 1})]
    for box in sorted({b for b in boxes if b}):
        print(f"\n=== mailbox {mask(box)}")
        try:
            g = build("gmail", "v1", credentials=svc._get_credentials(box), cache_discovery=False)
        except Exception as e:
            print("  auth failed:", str(e)[:120])
            continue
        own = box.split("@")[1]
        others = " OR ".join(f"from:{d}" for d in OURS if d != own)
        for label, q in (("inbound-from-our-domains", f"({others}) newer_than:90d"),
                         ("inbound-same-domain", f"from:{own} -in:sent newer_than:90d")):
            ids = g.users().messages().list(userId="me", q=q, maxResults=3).execute().get("messages", [])
            for m in ids:
                msg = g.users().messages().get(userId="me", id=m["id"], format="metadata",
                                               metadataHeaders=["From", "Authentication-Results", "Date"]).execute()
                ar = " | ".join(hdr(msg, "Authentication-Results"))
                verdict = {k: (re.search(rf"{k}=(\w+)", ar) or [None, "-"])[1] for k in ("spf", "dkim", "dmarc")}
                dkim_d = re.findall(r"header\.(?:i|d)=@?([\w.-]+)", ar)
                print(f"  [{label}] from {mask(re.sub(r'.*<|>.*', '', hdr(msg, 'From')[0]))} {hdr(msg, 'Date')[0][:16]} "
                      f"spf={verdict['spf']} dkim={verdict['dkim']} dkim_d={sorted(set(dkim_d))} dmarc={verdict['dmarc']}")
        ids = g.users().messages().list(userId="me", q="in:sent newer_than:30d -to:" + own, maxResults=3).execute().get("messages", [])
        for m in ids:
            msg = g.users().messages().get(userId="me", id=m["id"], format="full").execute()
            acc = collections.defaultdict(int, types=set(), pixel=False)
            walk(msg["payload"], acc)
            print(f"  [sent] {hdr(msg, 'Date')[0][:16]} List-Unsubscribe={'yes' if hdr(msg, 'List-Unsubscribe') else 'NO'} "
                  f"One-Click={'yes' if hdr(msg, 'List-Unsubscribe-Post') else 'NO'} html={'text/html' in acc['types']} "
                  f"html_links={acc['links']} plain_links={acc['plain_links']} imgs={acc['imgs']} pixel={acc['pixel']} "
                  f"attachments={acc['attachments']} reply={'yes' if hdr(msg, 'In-Reply-To') else 'no'}")


if __name__ == "__main__":
    main()
