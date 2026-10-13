from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta
from collections.abc import Iterable
from pathlib import Path

from sponsorscope.matching.names import normalize
from sponsorscope.models import Label, RawPosting, SponsorRecord

GONE_AFTER = 3

SCHEMA = """
CREATE TABLE IF NOT EXISTS sponsors (
  id INTEGER PRIMARY KEY,
  country TEXT NOT NULL,
  source TEXT NOT NULL,
  evidence TEXT NOT NULL,
  legal_name TEXT NOT NULL,
  norm_name TEXT NOT NULL,
  registry_id TEXT,
  city TEXT,
  route TEXT NOT NULL DEFAULT '',
  filings INTEGER,
  period TEXT,
  first_seen TEXT NOT NULL,
  last_seen TEXT NOT NULL,
  UNIQUE (source, norm_name, route)
);
CREATE INDEX IF NOT EXISTS sponsors_norm ON sponsors(norm_name);
CREATE TABLE IF NOT EXISTS source_versions (
  source TEXT PRIMARY KEY, version TEXT NOT NULL, fetched_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS companies (
  id INTEGER PRIMARY KEY, display_name TEXT NOT NULL, norm_name TEXT NOT NULL UNIQUE
);
CREATE TABLE IF NOT EXISTS boards (
  ats TEXT NOT NULL, slug TEXT NOT NULL, company_id INTEGER,
  status TEXT NOT NULL, origin TEXT NOT NULL,
  consecutive_failures INTEGER NOT NULL DEFAULT 0,
  last_probed TEXT, next_probe_at TEXT,
  PRIMARY KEY (ats, slug)
);
CREATE TABLE IF NOT EXISTS sponsor_matches (
  sponsor_id INTEGER NOT NULL, company_id INTEGER NOT NULL,
  method TEXT NOT NULL, score REAL NOT NULL,
  PRIMARY KEY (sponsor_id, company_id)
);
CREATE TABLE IF NOT EXISTS postings (
  id TEXT PRIMARY KEY, ats TEXT NOT NULL, slug TEXT NOT NULL, company_id INTEGER,
  title TEXT, url TEXT, location_raw TEXT, country TEXT, remote TEXT, posted_at TEXT,
  content_hash TEXT, lang TEXT, first_seen TEXT NOT NULL, last_seen TEXT NOT NULL,
  active INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS postings_board ON postings(ats, slug);
CREATE TABLE IF NOT EXISTS labels (
  posting_id TEXT NOT NULL, content_hash TEXT NOT NULL, classifier_version TEXT NOT NULL,
  sponsorship TEXT NOT NULL, mixed INTEGER NOT NULL DEFAULT 0,
  languages_required TEXT NOT NULL, evidence TEXT NOT NULL,
  PRIMARY KEY (posting_id, content_hash, classifier_version)
);
CREATE TABLE IF NOT EXISTS discovery_progress (
  sponsor_norm TEXT PRIMARY KEY, attempts INTEGER NOT NULL DEFAULT 0, next_try_at TEXT
);
"""


def connect(path: Path | str) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def _sponsor_rows(records: Iterable[SponsorRecord]) -> dict[tuple[str, str], SponsorRecord]:
    rows: dict[tuple[str, str], SponsorRecord] = {}
    for r in records:
        norm = normalize(r.legal_name)
        if norm:
            rows[(norm, r.route or "")] = r
    return rows


def count_sponsor_keys(records: Iterable[SponsorRecord]) -> int:
    return len(_sponsor_rows(records))


def upsert_sponsors(conn: sqlite3.Connection, source: str, records: Iterable[SponsorRecord],
                    version: str, now: str) -> int:
    rows = _sponsor_rows(records)
    conn.executemany(
        """
        INSERT INTO sponsors (country, source, evidence, legal_name, norm_name, registry_id, city,
                              route, filings, period, first_seen, last_seen)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT (source, norm_name, route) DO UPDATE SET
          country = excluded.country, evidence = excluded.evidence,
          legal_name = excluded.legal_name, registry_id = excluded.registry_id,
          city = excluded.city, filings = excluded.filings, period = excluded.period,
          last_seen = excluded.last_seen
        """,
        [
            (r.country, source, r.evidence, r.legal_name, norm, r.registry_id, r.city, route,
             r.filings, r.period, now, now)
            for (norm, route), r in rows.items()
        ],
    )
    conn.execute(
        """
        INSERT INTO source_versions (source, version, fetched_at) VALUES (?, ?, ?)
        ON CONFLICT (source) DO UPDATE SET version = excluded.version, fetched_at = excluded.fetched_at
        """,
        (source, version, now),
    )
    return len(rows)


def get_source_version(conn: sqlite3.Connection, source: str) -> str | None:
    row = conn.execute("SELECT version FROM source_versions WHERE source = ?", (source,)).fetchone()
    return row["version"] if row else None


def active_sponsor_count(conn: sqlite3.Connection, source: str) -> int:
    return conn.execute(
        """
        SELECT COUNT(*) FROM sponsors s
        JOIN source_versions v ON v.source = s.source AND s.last_seen = v.fetched_at
        WHERE s.source = ?
        """,
        (source,),
    ).fetchone()[0]


def get_or_create_company(conn: sqlite3.Connection, display_name: str) -> int:
    norm = normalize(display_name) or display_name.strip().lower()
    conn.execute(
        "INSERT INTO companies (display_name, norm_name) VALUES (?, ?) ON CONFLICT (norm_name) DO NOTHING",
        (display_name.strip(), norm),
    )
    return conn.execute("SELECT id FROM companies WHERE norm_name = ?", (norm,)).fetchone()[0]


def upsert_board(conn: sqlite3.Connection, ats: str, slug: str, company_id: int, *,
                 status: str, origin: str, now: str) -> None:
    conn.execute(
        """
        INSERT INTO boards (ats, slug, company_id, status, origin, last_probed)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT (ats, slug) DO UPDATE SET company_id = excluded.company_id
        """,
        (ats, slug, company_id, status, origin, now),
    )


def boards_to_crawl(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT ats, slug, company_id FROM boards WHERE status = 'hit' ORDER BY ats, slug"
    ).fetchall()


def record_board_result(conn: sqlite3.Connection, ats: str, slug: str, outcome: str) -> None:
    if outcome == "ok":
        conn.execute("UPDATE boards SET consecutive_failures = 0 WHERE ats = ? AND slug = ?", (ats, slug))
    elif outcome == "not_found":
        conn.execute(
            """
            UPDATE boards SET consecutive_failures = consecutive_failures + 1,
              status = CASE WHEN consecutive_failures + 1 >= ? THEN 'gone' ELSE status END
            WHERE ats = ? AND slug = ?
            """,
            (GONE_AFTER, ats, slug),
        )
    else:
        raise ValueError(f"unknown board outcome: {outcome}")


def get_posting_meta(conn: sqlite3.Connection, posting_id: str) -> sqlite3.Row | None:
    return conn.execute("SELECT content_hash, lang FROM postings WHERE id = ?", (posting_id,)).fetchone()


def upsert_posting(conn: sqlite3.Connection, p: RawPosting, *, company_id: int, country: str | None,
                   lang: str, content_hash: str, now: str) -> None:
    conn.execute(
        """
        INSERT INTO postings (id, ats, slug, company_id, title, url, location_raw, country, remote,
                              posted_at, content_hash, lang, first_seen, last_seen, active)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
        ON CONFLICT (id) DO UPDATE SET
          company_id = excluded.company_id, title = excluded.title, url = excluded.url,
          location_raw = excluded.location_raw, country = excluded.country, remote = excluded.remote,
          posted_at = excluded.posted_at, content_hash = excluded.content_hash, lang = excluded.lang,
          last_seen = excluded.last_seen, active = 1
        """,
        (p.id, p.ats, p.slug, company_id, p.title, p.url, p.location_raw, country, p.remote,
         p.posted_at, content_hash, lang, now, now),
    )


def deactivate_missing(conn: sqlite3.Connection, ats: str, slug: str, seen_ids: set[str]) -> int:
    active = [r[0] for r in conn.execute(
        "SELECT id FROM postings WHERE ats = ? AND slug = ? AND active = 1", (ats, slug))]
    missing = [pid for pid in active if pid not in seen_ids]
    conn.executemany("UPDATE postings SET active = 0 WHERE id = ?", [(pid,) for pid in missing])
    return len(missing)


def has_label(conn: sqlite3.Connection, posting_id: str, content_hash: str, version: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM labels WHERE posting_id = ? AND content_hash = ? AND classifier_version = ?",
        (posting_id, content_hash, version),
    ).fetchone() is not None


def save_label(conn: sqlite3.Connection, posting_id: str, content_hash: str, version: str,
               label: Label) -> None:
    conn.execute(
        """
        INSERT OR REPLACE INTO labels (posting_id, content_hash, classifier_version, sponsorship,
                                       mixed, languages_required, evidence)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (posting_id, content_hash, version, label.sponsorship, int(label.mixed),
         json.dumps(list(label.languages_required)), json.dumps(list(label.evidence), ensure_ascii=False)),
    )


def replace_matches(conn: sqlite3.Connection, matches: Iterable[tuple[int, int, str, float]]) -> None:
    conn.execute("DELETE FROM sponsor_matches")
    conn.executemany(
        "INSERT OR REPLACE INTO sponsor_matches (sponsor_id, company_id, method, score) VALUES (?, ?, ?, ?)",
        list(matches),
    )


def active_posting_ids(conn: sqlite3.Connection, ats: str, slug: str) -> frozenset[str]:
    return frozenset(r[0] for r in conn.execute(
        "SELECT id FROM postings WHERE ats = ? AND slug = ? AND active = 1", (ats, slug)))


def touch_posting(conn: sqlite3.Connection, p: RawPosting, *, company_id: int, country: str | None, now: str) -> None:
    """Known posting seen again without its description: refresh metadata, keep hash/lang/label."""
    conn.execute(
        """
        UPDATE postings SET company_id = ?, title = ?, url = ?, location_raw = ?, country = ?, remote = ?,
          posted_at = ?, last_seen = ?, active = 1
        WHERE id = ?
        """,
        (company_id, p.title, p.url, p.location_raw, country, p.remote, p.posted_at, now, p.id),
    )


BACKOFF_DAYS = (7, 28, 84)  # spec §6.2: misses back off 1w → 4w → 12w


def backoff_until(now: str, attempts: int) -> str:
    days = BACKOFF_DAYS[min(max(attempts, 1), len(BACKOFF_DAYS)) - 1]
    return (datetime.fromisoformat(now) + timedelta(days=days)).isoformat(timespec="seconds")


def add_seed_board(conn: sqlite3.Connection, ats: str, slug: str, company_id: int | None, now: str) -> bool:
    cur = conn.execute(
        "INSERT OR IGNORE INTO boards (ats, slug, company_id, status, origin, next_probe_at) "
        "VALUES (?, ?, ?, 'pending', 'seed', ?)",
        (ats, slug, company_id, now),
    )
    return cur.rowcount == 1


def board_exists(conn: sqlite3.Connection, ats: str, slug: str) -> bool:
    return conn.execute("SELECT 1 FROM boards WHERE ats = ? AND slug = ?", (ats, slug)).fetchone() is not None


def board_company(conn: sqlite3.Connection, ats: str, slug: str) -> int | None:
    row = conn.execute("SELECT company_id FROM boards WHERE ats = ? AND slug = ?", (ats, slug)).fetchone()
    return row["company_id"] if row else None


def due_boards(conn: sqlite3.Connection, now: str, limit: int) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT ats, slug, company_id, status FROM (
          SELECT ats, slug, company_id, status,
                 ROW_NUMBER() OVER (
                   PARTITION BY ats
                   ORDER BY CASE status WHEN 'pending' THEN 0 WHEN 'gone' THEN 1 ELSE 2 END, next_probe_at, slug
                 ) AS turn
          FROM boards
          WHERE status IN ('pending', 'miss', 'gone') AND (next_probe_at IS NULL OR next_probe_at <= ?)
        )
        ORDER BY turn, ats  -- round-robin across ATSes: each host has its own rate limit
        LIMIT ?
        """,
        (now, limit),
    ).fetchall()


def record_probe(conn: sqlite3.Connection, ats: str, slug: str, *, exists: bool, company_id: int | None,
                 now: str) -> None:
    if exists:
        conn.execute(
            """
            UPDATE boards SET status = 'hit', consecutive_failures = 0, company_id = COALESCE(?, company_id),
              last_probed = ?, next_probe_at = NULL
            WHERE ats = ? AND slug = ?
            """,
            (company_id, now, ats, slug),
        )
        return
    failures = conn.execute(
        "SELECT consecutive_failures FROM boards WHERE ats = ? AND slug = ?", (ats, slug)).fetchone()[0] + 1
    conn.execute(
        "UPDATE boards SET status = 'miss', consecutive_failures = ?, last_probed = ?, next_probe_at = ? "
        "WHERE ats = ? AND slug = ?",
        (failures, now, backoff_until(now, failures), ats, slug),
    )


def sponsors_to_guess(conn: sqlite3.Connection, now: str, limit: int) -> list[sqlite3.Row]:
    """Active, unmatched sponsor names due for slug guessing; heavy sponsors first, UK-only last."""
    return conn.execute(
        """
        SELECT s.norm_name, MAX(COALESCE(s.filings, 0)) AS weight, MIN(s.source = 'gb') AS uk_only
        FROM sponsors s
        JOIN source_versions v ON v.source = s.source AND v.fetched_at = s.last_seen
        LEFT JOIN discovery_progress d ON d.sponsor_norm = s.norm_name
        WHERE (d.next_try_at IS NULL OR d.next_try_at <= ?)
          AND NOT EXISTS (SELECT 1 FROM sponsor_matches m WHERE m.sponsor_id = s.id)
        GROUP BY s.norm_name
        ORDER BY weight DESC, uk_only ASC, s.norm_name
        LIMIT ?
        """,
        (now, limit),
    ).fetchall()


def record_guess_attempt(conn: sqlite3.Connection, norm: str, *, found: bool, now: str) -> None:
    row = conn.execute("SELECT attempts FROM discovery_progress WHERE sponsor_norm = ?", (norm,)).fetchone()
    attempts = (row["attempts"] if row else 0) + 1
    next_try = backoff_until(now, len(BACKOFF_DAYS) if found else attempts)
    conn.execute(
        """
        INSERT INTO discovery_progress (sponsor_norm, attempts, next_try_at) VALUES (?, ?, ?)
        ON CONFLICT (sponsor_norm) DO UPDATE SET attempts = excluded.attempts, next_try_at = excluded.next_try_at
        """,
        (norm, attempts, next_try),
    )
