"""
Everything the client told us about an RFQ, as text the local model can read.

The detail fill used to read one message -- the first client message the
segregator labelled rfq -- with the quoted history cut off, and only once.
Measured 2026-10-14 on the 50 RFQs of the last 60 days: deadline was found for
9, audience for 19, country for 24. The brief usually is somewhere else:
  * in the quoted history: the thread we index often starts at a later reply
    ("Please share your redirects") whose quote holds the original brief,
    sometimes under an older subject;
  * in later client messages of the thread (revised N, a new country);
  * in an attachment (13 of the 50 had one) -- an Excel or PDF brief.

sections() returns those pieces, oldest first, each tagged with where it came
from. Quoted text can contain our own replies, so callers must not take a
price from it (kind "quoted").
"""
import io
import logging
import re
import zipfile
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

ATTACHMENT_MAX_BYTES = 5 * 1024 * 1024
ATTACHMENT_TEXT_MAX = 12000
_TEXT_EXT = (".pdf", ".xlsx", ".xlsm", ".xls", ".docx", ".csv", ".txt")


def _quoted_part(body: str, own: str) -> str:
    """What follows the replier's own text (strip_quoted keeps a prefix)."""
    rest = re.sub(r"\n{3,}", "\n\n", (body or "").replace("\r\n", "\n").replace("\r", "\n"))
    i = rest.find(own) if own else -1
    if i >= 0:
        rest = rest[i + len(own):]
    rest = re.sub(r"(?m)^\s*>+ ?", "", rest)
    return re.sub(r"\n{3,}", "\n\n", rest).strip()


def thread_messages(client, rfq: Dict[str, Any]) -> List[Dict[str, Any]]:
    """The client's inbound messages of every thread this RFQ covers, oldest first."""
    from bson import ObjectId
    em = client["torpedo_gmail"]["email_metadata"]
    tids = [t for t in (rfq.get("gmail_thread_ids") or []) + [rfq.get("gmail_thread_id")] if t]
    ids = []
    for s in (rfq.get("source_emails") or []) + [rfq.get("source_email_id")]:
        try:
            ids.append(ObjectId(str(s)))
        except Exception:
            pass
    q: Dict[str, Any] = {"direction": "inbound"}
    ors = []
    if tids:
        ors.append({"gmail_thread_id": {"$in": list(set(tids))}})
    if ids:
        ors.append({"_id": {"$in": ids}})
    if not ors:
        return []
    q["$or"] = ors
    proj = {"subject": 1, "body_plain": 1, "snippet": 1, "timestamp": 1, "has_attachments": 1,
            "attachment_count": 1, "gmail_message_id": 1, "mailbox_id": 1, "attachment_text": 1,
            "attachment_text_at": 1}
    return sorted(em.find(q, proj), key=lambda d: d.get("timestamp") or datetime.min)


def latest_ts(client, rfq: Dict[str, Any]) -> Optional[datetime]:
    msgs = thread_messages(client, rfq)
    return max((m.get("timestamp") for m in msgs if m.get("timestamp")), default=None)


# ---------------------------------------------------------------------------
# attachments
# ---------------------------------------------------------------------------
def _pdf_text(data: bytes) -> str:
    from pypdf import PdfReader
    r = PdfReader(io.BytesIO(data))
    return "\n".join((p.extract_text() or "") for p in r.pages[:10])


def _xlsx_text(data: bytes) -> str:
    from openpyxl import load_workbook
    wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    lines = []
    for ws in wb.worksheets[:5]:
        lines.append(f"[{ws.title}]")
        for row in ws.iter_rows(max_row=200, values_only=True):
            cells = [str(c).strip() for c in row if c not in (None, "")]
            if cells:
                lines.append(" | ".join(cells))
    return "\n".join(lines)


def _xls_text(data: bytes) -> str:
    import xlrd
    book = xlrd.open_workbook(file_contents=data)
    lines = []
    for sh in book.sheets()[:5]:
        lines.append(f"[{sh.name}]")
        for i in range(min(sh.nrows, 200)):
            cells = [str(c).strip() for c in sh.row_values(i) if str(c).strip()]
            if cells:
                lines.append(" | ".join(cells))
    return "\n".join(lines)


def _docx_text(data: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        xml = z.read("word/document.xml").decode("utf-8", "ignore")
    xml = re.sub(r"</w:p>", "\n", xml)
    xml = re.sub(r"<w:tab/>", "\t", xml)
    return re.sub(r"<[^>]+>", "", xml)


def file_text(filename: str, data: bytes) -> str:
    name = (filename or "").lower()
    try:
        if name.endswith(".pdf"):
            return _pdf_text(data)
        if name.endswith((".xlsx", ".xlsm")):
            return _xlsx_text(data)
        if name.endswith(".xls"):
            return _xls_text(data)
        if name.endswith(".docx"):
            return _docx_text(data)
        if name.endswith((".csv", ".txt")):
            return data.decode("utf-8", "ignore")
    except Exception as e:
        logger.info("rfq attachment %s unreadable: %s", filename, e)
    return ""


def _parts(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    out = []
    for p in payload.get("parts") or []:
        if p.get("filename"):
            out.append(p)
        out.extend(_parts(p))
    return out


def attachment_texts(client, msg: Dict[str, Any]) -> List[Dict[str, str]]:
    """Text of a message's attachments, fetched from Gmail once and cached on
    the message (attachment_text). [] when none or unreadable."""
    if msg.get("attachment_text_at"):
        return msg.get("attachment_text") or []
    if not (msg.get("has_attachments") or msg.get("attachment_count")):
        return []
    import base64
    from bson import ObjectId
    from app.services.reengagement import _mailbox
    texts: List[Dict[str, str]] = []
    mailbox = _mailbox(client, msg.get("mailbox_id")).get("email")
    if not mailbox or not msg.get("gmail_message_id"):
        return []
    try:
        import os
        from app.services.gmail_workspace_service import GmailWorkspaceService
        svc = GmailWorkspaceService(mongo_uri=os.getenv("MONGO_URI") or "mongodb://localhost:27017/",
                                    db_name="torpedo_gmail")
        gm = svc._get_service(mailbox).users().messages()
        full = gm.get(userId="me", id=msg["gmail_message_id"], format="full").execute()
        for p in _parts(full.get("payload") or {}):
            fn = p.get("filename") or ""
            body = p.get("body") or {}
            if not fn.lower().endswith(_TEXT_EXT) or (body.get("size") or 0) > ATTACHMENT_MAX_BYTES:
                continue
            raw = body.get("data")
            if not raw and body.get("attachmentId"):
                raw = gm.attachments().get(userId="me", messageId=msg["gmail_message_id"],
                                           id=body["attachmentId"]).execute().get("data")
            if not raw:
                continue
            t = re.sub(r"[ \t]+", " ", file_text(fn, base64.urlsafe_b64decode(raw))).strip()
            if t:
                texts.append({"filename": fn, "text": t[:ATTACHMENT_TEXT_MAX]})
    except Exception as e:
        # Not cached: a Gmail hiccup is retried on the next pass.
        logger.warning("rfq attachments for %s not fetched: %s", msg.get("_id"), e)
        return []
    client["torpedo_gmail"]["email_metadata"].update_one(
        {"_id": ObjectId(str(msg["_id"]))},
        {"$set": {"attachment_text": texts, "attachment_text_at": datetime.utcnow()}})
    return texts


# ---------------------------------------------------------------------------
# sections
# ---------------------------------------------------------------------------
# Study terms, not bare digits: every signature carries a phone number, which
# made "Please share your redirects" look like a brief.
_SIGNAL = re.compile(r"\b(loi|ir|incidence|sample|samples|n\s*=\s*\d|countr(y|ies)|markets?|cit(y|ies)|"
                     r"deadline|timelines?|target|audience|respondents?|completes?|online|cati|capi|cawi|"
                     r"f2f|b2b|b2c|budget|quote|specs?|quota|ages?|nccs|sec|males?|females?|"
                     r"\d+\s*(mins?|minutes|%))\b", re.I)


def windows(text: str, size: int) -> List[str]:
    """Split on paragraph boundaries into pieces of at most `size` chars."""
    out, cur = [], ""
    for para in re.split(r"\n\s*\n", text or ""):
        para = para.strip()
        if not para:
            continue
        while len(para) > size:
            out.append(para[:size])
            para = para[size:]
        if len(cur) + len(para) + 2 > size and cur:
            out.append(cur)
            cur = ""
        cur = f"{cur}\n\n{para}" if cur else para
    if cur:
        out.append(cur)
    return [w for w in out if _SIGNAL.search(w)]


def sections(client, rfq: Dict[str, Any], size: int = 2800,
             with_attachments: bool = True) -> List[Dict[str, Any]]:
    """[{kind: own|attachment|quoted, subject, text}] for the model: the
    client's own words and attachments oldest first, then the quoted history.

    Quoted history is taken once, from the message with the longest quote (it
    holds the oldest mail), so the same brief is not read several times. It
    comes last: a long reply's quote is ~10K chars and, read first, it used up
    the piece budget before the client's own brief was reached."""
    from sales.reply_triage import strip_quoted
    msgs = thread_messages(client, rfq)
    out: List[Dict[str, Any]] = []
    seen = set()
    newest_quote = ""
    for m in msgs:
        body = m.get("body_plain") or m.get("snippet") or ""
        own = strip_quoted(body)
        q = _quoted_part(body, own)
        if len(q) > len(newest_quote):
            newest_quote = q
        for w in windows(own, size):
            if w not in seen:
                seen.add(w)
                out.append({"kind": "own", "subject": m.get("subject") or "", "text": w})
        if with_attachments:
            for a in attachment_texts(client, m):
                for w in windows(a["text"], size):
                    out.append({"kind": "attachment", "subject": f"{m.get('subject') or ''} [{a['filename']}]",
                                "text": w})
    subject = msgs[0].get("subject") if msgs else ""
    quoted = [{"kind": "quoted", "subject": subject or "", "text": w}
              for w in windows(newest_quote, size) if w not in seen]
    return out + quoted
