from __future__ import annotations

import gzip
import json
import logging
import sqlite3
from collections import defaultdict
from pathlib import Path

from sponsorscope.classify.industry import BIOTECH, biotech_naics

log = logging.getLogger(__name__)

FIELDS = ["id", "title", "company", "url", "country", "remote", "posted_at", "first_seen",
          "sponsorship", "mixed", "langs", "evidence", "badges", "ats", "level", "industry", "industry_evidence"]
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
       p.posted_at, p.first_seen, p.ats, p.level, l.sponsorship, l.mixed, l.languages_required, l.evidence,
       l.industry, l.industry_evidence
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
_NAICS = """
SELECT DISTINCT m.company_id, s.naics
FROM sponsor_matches m
JOIN sponsors s ON s.id = m.sponsor_id
JOIN source_versions v ON v.source = s.source AND v.fetched_at = s.last_seen
WHERE s.naics IS NOT NULL AND m.method != 'unverified'
"""
_TAGGED_SHARE = """
SELECT p.company_id, SUM(l.industry IS 'biotech') AS tagged, COUNT(*) AS total
FROM postings p
JOIN labels l ON l.posting_id = p.id AND l.content_hash = p.content_hash AND l.classifier_version = ?
WHERE p.active = 1
GROUP BY p.company_id
"""
COMPANY_MIN_TAGGED = 2  # a company whose open postings are mostly biotech is a biotech company:
COMPANY_MIN_SHARE = 0.5  # its generic roles (finance, ML engineer, text-less ads) get the tag too


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


def _biotech_companies(conn: sqlite3.Connection, classifier_version: str) -> dict[int, str]:
    """company id → why the whole company counts as biotech / pharma: its sponsor-register industry code
    (name coincidences excluded), else most of its open postings being tagged."""
    out: dict[int, str] = {}
    for r in conn.execute(_NAICS):
        if name := biotech_naics(r["naics"]):
            out.setdefault(r["company_id"], f"US H-1B filings list this employer as {name} (NAICS {r['naics']})")
    for r in conn.execute(_TAGGED_SHARE, (classifier_version,)):
        if r["tagged"] >= COMPANY_MIN_TAGGED and r["tagged"] >= COMPANY_MIN_SHARE * r["total"]:
            share = f"{r['tagged']} of this employer's {r['total']} open postings"
            out.setdefault(r["company_id"], f"{share} describe biotech / pharma work")
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
    biotech = _biotech_companies(conn, classifier_version)
    shards: dict[str, list[list]] = defaultdict(list)
    companies: set[str] = set()
    ats_names: set[str] = set()
    for r in conn.execute(_POSTINGS, (classifier_version,)):
        country = r["country"]
        row_badges = badges.get(r["company_id"], {}).get(country, []) if country else []
        industry_evidence = json.loads(r["industry_evidence"] or "[]")
        if r["company_id"] in biotech:
            industry_evidence.insert(0, biotech[r["company_id"]])
        shards[country or UNKNOWN_COUNTRY].append([
            r["id"], r["title"], r["company"], r["url"], country, r["remote"], r["posted_at"],
            r["first_seen"], r["sponsorship"] or "unknown", bool(r["mixed"]),
            json.loads(r["languages_required"] or "[]"), json.loads(r["evidence"] or "[]"),
            row_badges, r["ats"], r["level"],
            BIOTECH if r["industry"] == BIOTECH or r["company_id"] in biotech else None, industry_evidence,
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
