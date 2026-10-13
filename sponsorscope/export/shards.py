from __future__ import annotations

import gzip
import json
import logging
import sqlite3
from collections import defaultdict
from pathlib import Path

log = logging.getLogger(__name__)

FIELDS = ["id", "title", "company", "url", "country", "remote", "posted_at", "first_seen",
          "sponsorship", "mixed", "langs", "evidence", "badges", "ats"]
UNKNOWN_COUNTRY = "XX"
SHARD_WARN_BYTES = 5 * 1024 * 1024

COUNTRY_LABELS = {"GB": "UK", "NL": "NL", "DK": "DK", "FI": "FI", "US": "US", "CA": "Canada", "IE": "Ireland"}
HISTORY_TEMPLATES = {
    "us": "Filed {n} certified H-1B LCAs ({period})",
    "ca": "{n} positive LMIAs ({period})",
    "ie": "{n} employment permits issued ({period})",
}

_POSTINGS = """
SELECT p.id, p.title, c.display_name AS company, p.company_id, p.url, p.country, p.remote,
       p.posted_at, p.first_seen, p.ats, l.sponsorship, l.mixed, l.languages_required, l.evidence
FROM postings p
JOIN companies c ON c.id = p.company_id
LEFT JOIN labels l ON l.posting_id = p.id AND l.content_hash = p.content_hash AND l.classifier_version = ?
WHERE p.active = 1 AND p.lang = 'en'
ORDER BY COALESCE(p.posted_at, substr(p.first_seen, 1, 10)) DESC, p.id
"""
_BADGES = """
SELECT m.company_id, s.source, s.evidence, s.country, SUM(s.filings) AS filings, MAX(s.period) AS period,
       MIN(m.method = 'unverified') AS weak
FROM sponsor_matches m
JOIN sponsors s ON s.id = m.sponsor_id
JOIN source_versions v ON v.source = s.source AND v.fetched_at = s.last_seen
GROUP BY m.company_id, s.source, s.evidence, s.country
"""


def badge_text(source: str, evidence: str, country: str, filings: int | None, period: str | None) -> str:
    if evidence == "licence":
        return f"Licensed sponsor ({COUNTRY_LABELS.get(country, country)})"
    return HISTORY_TEMPLATES[source].format(n=filings or 0, period=period or "")


def _badges_by_company(conn: sqlite3.Connection) -> dict[int, dict[str, list[list[str]]]]:
    out: dict[int, dict[str, list[list[str]]]] = defaultdict(lambda: defaultdict(list))
    for r in conn.execute(_BADGES):
        text = badge_text(r["source"], r["evidence"], r["country"], r["filings"], r["period"])
        weak = bool(r["weak"])  # every supporting match is a name coincidence only
        out[r["company_id"]][r["country"]].append([r["evidence"], f"Name match only: {text}" if weak else text, weak])
    return out


def _sources(conn: sqlite3.Connection, run_report: dict | None) -> dict[str, dict]:
    out = {r["source"]: {"status": "ok", "data_as_of": r["fetched_at"], "version": r["version"]}
           for r in conn.execute("SELECT source, version, fetched_at FROM source_versions")}
    for name, info in (run_report or {}).get("sources", {}).items():
        entry = out.setdefault(name, {"data_as_of": None, "version": None})
        entry.update({k: v for k, v in info.items() if k in ("status", "error")})
    return out


def export_site(conn: sqlite3.Connection, site_dir: Path, classifier_version: str, generated_at: str,
                run_report: dict | None = None) -> dict[str, int]:
    data_dir = site_dir / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    for stale in data_dir.glob("*.json.gz"):
        stale.unlink()

    badges = _badges_by_company(conn)
    shards: dict[str, list[list]] = defaultdict(list)
    companies: set[str] = set()
    ats_names: set[str] = set()
    for r in conn.execute(_POSTINGS, (classifier_version,)):
        country = r["country"]
        row_badges = badges.get(r["company_id"], {}).get(country, []) if country else []
        shards[country or UNKNOWN_COUNTRY].append([
            r["id"], r["title"], r["company"], r["url"], country, r["remote"], r["posted_at"],
            r["first_seen"], r["sponsorship"] or "unknown", bool(r["mixed"]),
            json.loads(r["languages_required"] or "[]"), json.loads(r["evidence"] or "[]"),
            row_badges, r["ats"],
        ])
        companies.add(r["company"])
        ats_names.add(r["ats"])

    counts: dict[str, int] = {}
    for cc, rows in sorted(shards.items()):
        payload = json.dumps(rows, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        blob = gzip.compress(payload, mtime=0)
        (data_dir / f"{cc.lower()}.json.gz").write_bytes(blob)
        if len(blob) > SHARD_WARN_BYTES:
            log.warning("shard %s is %.1f MB gzipped (budget 5 MB)", cc, len(blob) / 1e6)
        counts[cc] = len(rows)

    index = {"generated_at": generated_at, "fields": FIELDS, "countries": counts,
             "companies": sorted(companies), "ats": sorted(ats_names), "sources": _sources(conn, run_report)}
    (data_dir / "index.json").write_text(json.dumps(index, ensure_ascii=False), encoding="utf-8")
    if run_report is not None:
        (data_dir / "last_run.json").write_text(json.dumps(run_report, indent=2, ensure_ascii=False), encoding="utf-8")
    return counts
