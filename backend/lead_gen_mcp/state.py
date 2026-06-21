"""
SQLite state store for the adaptive lead-generation pipeline.

Tables
------
icps             — ICP definitions (mirrors MongoDB icp_configs for pipeline use)
queries          — per-query yield log
profiles_seen    — dedup index (profile_url → first run)
leads            — full enriched records + status
coverage         — dimension coverage matrix per ICP
synonyms         — learned synonym pool per ICP
triggers         — incoming company-event queue
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional

# Default DB location: same dir as this file so it survives server restarts
_DEFAULT_DB = Path(__file__).parent / "pipeline.db"
DB_PATH = Path(os.getenv("LEAD_GEN_DB_PATH", str(_DEFAULT_DB)))


# ---------------------------------------------------------------------------
# Connection helper
# ---------------------------------------------------------------------------

@contextmanager
def get_conn() -> Generator[sqlite3.Connection, None, None]:
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Schema init
# ---------------------------------------------------------------------------

_DDL = """
CREATE TABLE IF NOT EXISTS icps (
    icp_id              TEXT PRIMARY KEY,
    name                TEXT NOT NULL,
    target_titles       TEXT NOT NULL DEFAULT '[]',   -- JSON array
    target_industries   TEXT NOT NULL DEFAULT '[]',
    target_geos         TEXT NOT NULL DEFAULT '[]',
    company_size_band   TEXT,
    exclusion_rules     TEXT NOT NULL DEFAULT '{}',   -- JSON object
    min_hunter_conf     INTEGER NOT NULL DEFAULT 70,
    daily_query_budget  INTEGER NOT NULL DEFAULT 100,
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS queries (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    icp_id          TEXT NOT NULL,
    query_text      TEXT NOT NULL,
    dimension_cell  TEXT NOT NULL DEFAULT '',
    run_ts          TEXT NOT NULL,
    result_count    INTEGER NOT NULL DEFAULT 0,
    novel_count     INTEGER NOT NULL DEFAULT 0,
    icp_passing     INTEGER NOT NULL DEFAULT 0,
    enriched_count  INTEGER NOT NULL DEFAULT 0,
    pushed_count    INTEGER NOT NULL DEFAULT 0,
    status          TEXT NOT NULL DEFAULT 'complete',  -- complete | error
    FOREIGN KEY(icp_id) REFERENCES icps(icp_id)
);

CREATE TABLE IF NOT EXISTS profiles_seen (
    profile_url_hash    TEXT PRIMARY KEY,
    profile_url         TEXT NOT NULL,
    icp_id              TEXT NOT NULL,
    first_seen_ts       TEXT NOT NULL,
    first_seen_query    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS leads (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    external_id         TEXT UNIQUE NOT NULL,   -- SHA-256 of normalised profile_url
    profile_url         TEXT NOT NULL,
    icp_id              TEXT NOT NULL,
    name                TEXT,
    title               TEXT,
    company             TEXT,
    location            TEXT,
    snippet             TEXT,
    source_query        TEXT,
    icp_score           REAL,
    email               TEXT,
    hunter_confidence   INTEGER,
    verification_status TEXT,
    domain              TEXT,
    status              TEXT NOT NULL DEFAULT 'scored',  -- scored|enriched|pushed|failed
    crm_contact_id      TEXT,
    run_ts              TEXT NOT NULL,
    updated_ts          TEXT NOT NULL,
    FOREIGN KEY(icp_id) REFERENCES icps(icp_id)
);

CREATE TABLE IF NOT EXISTS coverage (
    icp_id          TEXT NOT NULL,
    dimension_cell  TEXT NOT NULL,   -- "title|industry|geo"
    attempts        INTEGER NOT NULL DEFAULT 0,
    novel_total     INTEGER NOT NULL DEFAULT 0,
    exhausted       INTEGER NOT NULL DEFAULT 0,   -- boolean 0/1
    last_attempted  TEXT,
    PRIMARY KEY (icp_id, dimension_cell),
    FOREIGN KEY(icp_id) REFERENCES icps(icp_id)
);

CREATE TABLE IF NOT EXISTS synonyms (
    icp_id          TEXT NOT NULL,
    dimension       TEXT NOT NULL,   -- "title" | "industry" | "seniority"
    canonical       TEXT NOT NULL,   -- the original ICP term
    synonym         TEXT NOT NULL,
    discovered_at   TEXT NOT NULL,
    PRIMARY KEY (icp_id, dimension, synonym),
    FOREIGN KEY(icp_id) REFERENCES icps(icp_id)
);

CREATE TABLE IF NOT EXISTS triggers (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    icp_id          TEXT,
    company_name    TEXT NOT NULL,
    event_type      TEXT NOT NULL,
    description     TEXT,
    injected        INTEGER NOT NULL DEFAULT 0,   -- boolean
    created_at      TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_queries_icp     ON queries(icp_id, run_ts);
CREATE INDEX IF NOT EXISTS idx_leads_icp       ON leads(icp_id, status);
CREATE INDEX IF NOT EXISTS idx_leads_ext       ON leads(external_id);
CREATE INDEX IF NOT EXISTS idx_triggers_inj    ON triggers(injected, icp_id);
"""


def init_db() -> None:
    """Create all tables if they do not exist. Safe to call on every startup."""
    with get_conn() as conn:
        conn.executescript(_DDL)


# ---------------------------------------------------------------------------
# ICP helpers
# ---------------------------------------------------------------------------

def upsert_icp(
    icp_id: str,
    name: str,
    target_titles: List[str],
    target_industries: List[str],
    target_geos: List[str],
    company_size_band: Optional[str] = None,
    exclusion_rules: Optional[Dict[str, Any]] = None,
    min_hunter_conf: int = 70,
    daily_query_budget: int = 100,
) -> None:
    now = _now()
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO icps
                (icp_id, name, target_titles, target_industries, target_geos,
                 company_size_band, exclusion_rules, min_hunter_conf,
                 daily_query_budget, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(icp_id) DO UPDATE SET
                name              = excluded.name,
                target_titles     = excluded.target_titles,
                target_industries = excluded.target_industries,
                target_geos       = excluded.target_geos,
                company_size_band = excluded.company_size_band,
                exclusion_rules   = excluded.exclusion_rules,
                min_hunter_conf   = excluded.min_hunter_conf,
                daily_query_budget= excluded.daily_query_budget,
                updated_at        = excluded.updated_at
            """,
            (
                icp_id, name,
                json.dumps(target_titles),
                json.dumps(target_industries),
                json.dumps(target_geos),
                company_size_band,
                json.dumps(exclusion_rules or {}),
                min_hunter_conf,
                daily_query_budget,
                now, now,
            ),
        )


def get_icp(icp_id: str) -> Optional[Dict[str, Any]]:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM icps WHERE icp_id = ?", (icp_id,)).fetchone()
    if not row:
        return None
    return _deserialise_icp(row)


def list_icps() -> List[Dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM icps ORDER BY icp_id").fetchall()
    return [_deserialise_icp(r) for r in rows]


def _deserialise_icp(row: sqlite3.Row) -> Dict[str, Any]:
    d = dict(row)
    for f in ("target_titles", "target_industries", "target_geos", "exclusion_rules"):
        d[f] = json.loads(d[f])
    return d


# ---------------------------------------------------------------------------
# profiles_seen helpers
# ---------------------------------------------------------------------------

def profile_url_hash(url: str) -> str:
    return hashlib.sha256(url.strip().lower().encode()).hexdigest()


def is_profile_seen(url: str) -> bool:
    h = profile_url_hash(url)
    with get_conn() as conn:
        row = conn.execute(
            "SELECT 1 FROM profiles_seen WHERE profile_url_hash = ?", (h,)
        ).fetchone()
    return row is not None


def mark_profile_seen(url: str, icp_id: str, source_query: str) -> bool:
    """Returns True if newly inserted, False if already existed."""
    h = profile_url_hash(url)
    try:
        with get_conn() as conn:
            conn.execute(
                """
                INSERT INTO profiles_seen
                    (profile_url_hash, profile_url, icp_id, first_seen_ts, first_seen_query)
                VALUES (?, ?, ?, ?, ?)
                """,
                (h, url.strip().lower(), icp_id, _now(), source_query),
            )
        return True
    except sqlite3.IntegrityError:
        return False


def profiles_seen_count(icp_id: Optional[str] = None) -> int:
    with get_conn() as conn:
        if icp_id:
            return conn.execute(
                "SELECT COUNT(*) FROM profiles_seen WHERE icp_id = ?", (icp_id,)
            ).fetchone()[0]
        return conn.execute("SELECT COUNT(*) FROM profiles_seen").fetchone()[0]


# ---------------------------------------------------------------------------
# Leads helpers
# ---------------------------------------------------------------------------

def external_id(profile_url: str) -> str:
    return hashlib.sha256(profile_url.strip().lower().encode()).hexdigest()


def upsert_lead(data: Dict[str, Any]) -> str:
    """Upsert a lead by external_id. Returns the external_id."""
    eid = external_id(data["profile_url"])
    now = _now()
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO leads
                (external_id, profile_url, icp_id, name, title, company, location,
                 snippet, source_query, icp_score, email, hunter_confidence,
                 verification_status, domain, status, crm_contact_id, run_ts, updated_ts)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(external_id) DO UPDATE SET
                status              = excluded.status,
                email               = COALESCE(excluded.email, leads.email),
                hunter_confidence   = COALESCE(excluded.hunter_confidence, leads.hunter_confidence),
                verification_status = COALESCE(excluded.verification_status, leads.verification_status),
                domain              = COALESCE(excluded.domain, leads.domain),
                crm_contact_id      = COALESCE(excluded.crm_contact_id, leads.crm_contact_id),
                updated_ts          = excluded.updated_ts
            """,
            (
                eid,
                data["profile_url"],
                data.get("icp_id", ""),
                data.get("name"),
                data.get("title"),
                data.get("company"),
                data.get("location"),
                data.get("snippet"),
                data.get("source_query"),
                data.get("icp_score"),
                data.get("email"),
                data.get("hunter_confidence"),
                data.get("verification_status"),
                data.get("domain"),
                data.get("status", "scored"),
                data.get("crm_contact_id"),
                now,
                now,
            ),
        )
    return eid


def get_lead_counts(icp_id: str) -> Dict[str, int]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT status, COUNT(*) as n FROM leads WHERE icp_id = ? GROUP BY status",
            (icp_id,),
        ).fetchall()
    return {r["status"]: r["n"] for r in rows}


# ---------------------------------------------------------------------------
# Query log helpers
# ---------------------------------------------------------------------------

def log_query(
    icp_id: str,
    query_text: str,
    dimension_cell: str,
    result_count: int,
    novel_count: int,
    icp_passing: int,
    enriched_count: int,
    pushed_count: int,
    status: str = "complete",
) -> None:
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO queries
                (icp_id, query_text, dimension_cell, run_ts,
                 result_count, novel_count, icp_passing, enriched_count, pushed_count, status)
            VALUES (?,?,?,?,?,?,?,?,?,?)
            """,
            (
                icp_id, query_text, dimension_cell, _now(),
                result_count, novel_count, icp_passing, enriched_count, pushed_count, status,
            ),
        )


def get_query_history(icp_id: str, limit: int = 200) -> List[Dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT * FROM queries WHERE icp_id = ?
            ORDER BY run_ts DESC LIMIT ?
            """,
            (icp_id, limit),
        ).fetchall()
    return [dict(r) for r in rows]


def queries_run_count(icp_id: str) -> int:
    with get_conn() as conn:
        return conn.execute(
            "SELECT COUNT(*) FROM queries WHERE icp_id = ?", (icp_id,)
        ).fetchone()[0]


def daily_queries_used(icp_id: str) -> int:
    """Count queries run for this ICP today (UTC date)."""
    today = datetime.utcnow().strftime("%Y-%m-%d")
    with get_conn() as conn:
        return conn.execute(
            "SELECT COUNT(*) FROM queries WHERE icp_id = ? AND run_ts LIKE ?",
            (icp_id, f"{today}%"),
        ).fetchone()[0]


# ---------------------------------------------------------------------------
# Coverage matrix helpers
# ---------------------------------------------------------------------------

def record_coverage_attempt(
    icp_id: str,
    dimension_cell: str,
    novel_count: int,
    exhaustion_threshold: int = 3,
    min_yield: int = 1,
) -> None:
    """
    Increment attempt counter for a dimension cell.
    Mark exhausted if the last `exhaustion_threshold` attempts all yielded < min_yield novel leads.
    """
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO coverage (icp_id, dimension_cell, attempts, novel_total, last_attempted)
            VALUES (?, ?, 1, ?, ?)
            ON CONFLICT(icp_id, dimension_cell) DO UPDATE SET
                attempts       = attempts + 1,
                novel_total    = novel_total + ?,
                last_attempted = ?
            """,
            (icp_id, dimension_cell, novel_count, _now(), novel_count, _now()),
        )
        # Check recent attempts for this cell to decide exhaustion
        row = conn.execute(
            "SELECT attempts, novel_total FROM coverage WHERE icp_id=? AND dimension_cell=?",
            (icp_id, dimension_cell),
        ).fetchone()
        if row and row["attempts"] >= exhaustion_threshold:
            avg = row["novel_total"] / row["attempts"]
            if avg < min_yield:
                conn.execute(
                    "UPDATE coverage SET exhausted=1 WHERE icp_id=? AND dimension_cell=?",
                    (icp_id, dimension_cell),
                )


def get_coverage_matrix(icp_id: str) -> List[Dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM coverage WHERE icp_id = ? ORDER BY dimension_cell",
            (icp_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def get_exhausted_cells(icp_id: str) -> List[str]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT dimension_cell FROM coverage WHERE icp_id=? AND exhausted=1",
            (icp_id,),
        ).fetchall()
    return [r["dimension_cell"] for r in rows]


# ---------------------------------------------------------------------------
# Synonym helpers
# ---------------------------------------------------------------------------

def add_synonym(
    icp_id: str, dimension: str, canonical: str, synonym: str
) -> None:
    try:
        with get_conn() as conn:
            conn.execute(
                """
                INSERT INTO synonyms (icp_id, dimension, canonical, synonym, discovered_at)
                VALUES (?,?,?,?,?)
                """,
                (icp_id, dimension, canonical, synonym, _now()),
            )
    except sqlite3.IntegrityError:
        pass  # already recorded


def get_synonyms(icp_id: str, dimension: Optional[str] = None) -> List[Dict[str, Any]]:
    with get_conn() as conn:
        if dimension:
            rows = conn.execute(
                "SELECT * FROM synonyms WHERE icp_id=? AND dimension=?",
                (icp_id, dimension),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM synonyms WHERE icp_id=?", (icp_id,)
            ).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Trigger helpers
# ---------------------------------------------------------------------------

def ingest_trigger(
    company_name: str,
    event_type: str,
    description: Optional[str] = None,
    icp_id: Optional[str] = None,
) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            """
            INSERT INTO triggers (icp_id, company_name, event_type, description, created_at)
            VALUES (?,?,?,?,?)
            """,
            (icp_id, company_name, event_type, description, _now()),
        )
        return cur.lastrowid


def pop_pending_triggers(icp_id: Optional[str] = None, limit: int = 10) -> List[Dict[str, Any]]:
    """Return up to `limit` uninjected triggers and mark them as injected."""
    with get_conn() as conn:
        if icp_id:
            rows = conn.execute(
                """
                SELECT * FROM triggers
                WHERE injected=0 AND (icp_id=? OR icp_id IS NULL)
                ORDER BY created_at ASC LIMIT ?
                """,
                (icp_id, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM triggers WHERE injected=0 ORDER BY created_at ASC LIMIT ?",
                (limit,),
            ).fetchall()
        ids = [r["id"] for r in rows]
        if ids:
            conn.execute(
                f"UPDATE triggers SET injected=1 WHERE id IN ({','.join('?' * len(ids))})",
                ids,
            )
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Yield curve for stats
# ---------------------------------------------------------------------------

def get_yield_curve(icp_id: str, limit: int = 30) -> List[Dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT run_ts, SUM(novel_count) as novel_count, SUM(pushed_count) as pushed_count
            FROM queries WHERE icp_id=?
            GROUP BY DATE(run_ts)
            ORDER BY run_ts DESC LIMIT ?
            """,
            (icp_id, limit),
        ).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------

def _now() -> str:
    return datetime.utcnow().isoformat()


# Initialise tables on import so tools work out of the box
init_db()
