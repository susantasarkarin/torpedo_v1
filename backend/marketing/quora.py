"""Quora Ads (MARKETING_PLAN 3.4.2): no API, so CSV exports dropped in a folder are imported.

Folder: Integrations > Quora > csv_folder, else QUORA_CSV_DIR, else /var/lib/crm/quora/<BU>/ ;
a file's BU is its sub-folder name (SFW / COGENTIX / BIM). Each processed file is moved to
done/ next to it, so nothing is imported twice; the rows are upserted anyway (idempotent).
Headers are matched loosely (Quora renames columns between exports).
"""
import csv
import io
import os
import re
import shutil
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

from marketing import ads_common, schema

ALIASES = {
    "date": ("date", "day", "start date", "reporting starts"),
    "campaign": ("campaign", "campaign name"),
    "campaign_id": ("campaign id",),
    "ad_set": ("ad set", "ad set name", "adset name"),
    "ad": ("ad", "ad name"),
    "impressions": ("impressions",),
    "clicks": ("clicks",),
    "spend": ("spend", "amount spent", "cost", "spend (usd)", "spend (inr)"),
    "conversions": ("conversions", "conversion", "total conversions", "lead conversions"),
    "currency": ("currency",),
}


def _key(h: str) -> Optional[str]:
    h = re.sub(r"\s+", " ", (h or "").strip().lower())
    return next((k for k, al in ALIASES.items() if h in al), None)


def _num(v) -> float:
    s = re.sub(r"[^\d.\-]", "", str(v or ""))
    try:
        return float(s) if s else 0.0
    except ValueError:
        return 0.0


def _date(v) -> Optional[str]:
    v = (v or "").strip()
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y", "%b %d, %Y", "%d %b %Y"):
        try:
            return datetime.strptime(v, fmt).strftime("%Y-%m-%d")
        except ValueError:
            pass
    return None


def parse(text: str, *, bu: Optional[str], rates: Dict[str, float], default_currency: str = "USD") -> List[Dict[str, Any]]:
    reader = csv.reader(io.StringIO(text))
    rows = list(reader)
    head_i = next((i for i, r in enumerate(rows[:10]) if sum(1 for c in r if _key(c)) >= 3), None)
    if head_i is None:
        raise ValueError("no recognisable header (need at least date / campaign / spend columns)")
    cols = [_key(c) for c in rows[head_i]]
    out = []
    for r in rows[head_i + 1:]:
        d = {cols[i]: v for i, v in enumerate(r) if i < len(cols) and cols[i]}
        day = _date(d.get("date"))
        if not day or not (d.get("campaign") or d.get("campaign_id")):
            continue                                          # totals / blank lines
        cur = (d.get("currency") or default_currency).upper()
        spend_inr = ads_common.to_inr(_num(d.get("spend")), cur, rates)
        cid = d.get("campaign_id") or re.sub(r"\W+", "-", d["campaign"].strip().lower())
        level, eid = ("ad", f"{cid}:{d['ad']}") if d.get("ad") else ("ad_group", f"{cid}:{d['ad_set']}") if d.get("ad_set") else ("campaign", cid)
        out.append({"level": level, "entity_id": eid, "campaign_id": cid, "date": day, "name": d.get("ad") or d.get("ad_set") or d.get("campaign"),
                    "bu": bu, "impressions": _num(d.get("impressions")), "clicks": _num(d.get("clicks")),
                    "spend": _num(d.get("spend")), "currency": cur, "spend_inr": spend_inr, "conversions": _num(d.get("conversions")),
                    "fx_missing": spend_inr is None})
    # campaign-level totals so the paid rules (campaign level) see Quora too
    camp: Dict[tuple, Dict[str, Any]] = {}
    for r in out:
        if r["level"] == "campaign":
            continue
        c = camp.setdefault((r["campaign_id"], r["date"]), {"level": "campaign", "entity_id": r["campaign_id"], "campaign_id": r["campaign_id"],
                                                            "date": r["date"], "name": r["campaign_id"], "bu": bu, "impressions": 0.0,
                                                            "clicks": 0.0, "spend_inr": 0.0, "conversions": 0.0})
        for f in ("impressions", "clicks", "conversions"):
            c[f] += r[f]
        c["spend_inr"] = (c["spend_inr"] or 0) + (r["spend_inr"] or 0)
    if not any(r["level"] == "campaign" for r in out):
        out += list(camp.values())
    return out


def run(gd: Optional[Callable] = None, *, root: Optional[str] = None, now: Optional[datetime] = None) -> Dict[str, Any]:
    if gd is None:
        from database import get_database as gd
    now = now or datetime.utcnow()
    if root is None:
        try:
            from marketing import credentials
            root = (credentials.secrets("quora", gd).get("settings") or {}).get("csv_folder")
        except Exception:
            root = None
        root = root or os.getenv("QUORA_CSV_DIR", "/var/lib/crm/quora")
    rep: Dict[str, Any] = {"root": root, "files": 0, "rows": 0, "errors": []}
    if not os.path.isdir(root):
        rep["skipped"] = "folder does not exist yet"
        return rep
    rates = ads_common.fx(gd)
    for bu in schema.BUS:
        d = os.path.join(root, bu)
        if not os.path.isdir(d):
            continue
        for name in sorted(os.listdir(d)):
            path = os.path.join(d, name)
            if not name.lower().endswith(".csv") or not os.path.isfile(path):
                continue
            try:
                with open(path, encoding="utf-8-sig", errors="replace") as fh:
                    rows = parse(fh.read(), bu=bu, rates=rates)
                rep["rows"] += ads_common.store_metrics(gd, "quora", rows, now=now)
                os.makedirs(os.path.join(d, "done"), exist_ok=True)
                shutil.move(path, os.path.join(d, "done", f"{now:%Y%m%d%H%M%S}-{name}"))
                rep["files"] += 1
            except Exception as e:
                rep["errors"].append(f"{bu}/{name}: {str(e)[:150]}")
    return rep
