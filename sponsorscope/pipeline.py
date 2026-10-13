from __future__ import annotations

import asyncio
import sqlite3
from collections import Counter, defaultdict
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path

import yaml

from sponsorscope.ats.base import ATS, BoardNotFound
from sponsorscope.classify.base import Classifier
from sponsorscope.classify.lang_detect import is_english
from sponsorscope.export.shards import export_site
from sponsorscope.geo.country import resolve_country
from sponsorscope.http import Http
from sponsorscope.matching.names import Overrides, SponsorIndex, find_match
from sponsorscope.models import RawPosting, content_hash
from sponsorscope.registers.base import Register, RegisterBlocked
from sponsorscope.report import RunReport
from sponsorscope.store import db

SHRINK_GUARD = 0.8  # new register must have ≥ 80% of the previous row count
OUTAGE_RATIO = 0.5  # > 50% of an ATS's boards failing = outage, deactivate nothing
OUTAGE_MIN_BOARDS = 4


class ShrinkGuardError(Exception):
    pass


def seed_boards(conn: sqlite3.Connection, path: Path, now: str) -> int:
    entries = (yaml.safe_load(path.read_text()) or []) if path.exists() else []
    for e in entries:
        company_id = db.get_or_create_company(conn, e["name"])
        db.upsert_board(conn, e["ats"], e["slug"], company_id, status="hit", origin="seed", now=now)
    conn.commit()
    return len(entries)


async def run_registers(conn: sqlite3.Connection, http: Http, registers: Sequence[Register],
                        report: RunReport, now: str) -> None:
    for reg in registers:
        try:
            version = await reg.latest(http)
            if version == db.get_source_version(conn, reg.name):
                report.source(reg.name, "unchanged", version=version)
                continue
            records = await reg.fetch(http, version)
            previous = db.active_sponsor_count(conn, reg.name)
            rows = db.count_sponsor_keys(records)
            if previous and rows < previous * SHRINK_GUARD:
                raise ShrinkGuardError(f"shrink guard: {rows} rows vs {previous} previously")
            db.upsert_sponsors(conn, reg.name, records, version, now)
            conn.commit()
            report.source(reg.name, "ok", version=version, rows=rows)
        except RegisterBlocked as exc:
            conn.rollback()
            report.source(reg.name, "blocked", error=str(exc)[:300])
        except Exception as exc:  # one broken source must never stop the run
            conn.rollback()
            report.source(reg.name, "failed", error=f"{type(exc).__name__}: {exc}"[:300])


def run_match(conn: sqlite3.Connection, overrides: Overrides) -> int:
    index = SponsorIndex.build((r["id"], r["norm_name"]) for r in conn.execute("SELECT id, norm_name FROM sponsors"))
    matches: list[tuple[int, int, str, float]] = []
    for company in conn.execute("SELECT id, norm_name FROM companies").fetchall():
        norm = company["norm_name"]
        found = []
        hit = find_match(norm, index)
        if hit and (norm, hit[0]) not in overrides.forbid:
            found.append(hit)
        found += [(sponsor, "manual", 100.0) for c, sponsor in overrides.force if c == norm]
        for sponsor_norm, method, score in found:
            matches += [(sid, company["id"], method, score) for sid in index.by_norm.get(sponsor_norm, [])]
    db.replace_matches(conn, matches)
    conn.commit()
    return len(matches)


def _process_posting(conn: sqlite3.Connection, p: RawPosting, company_id: int, classifier: Classifier,
                     now: str, cities: Mapping[str, str] | None, detect: Callable[[str], bool]) -> None:
    text = f"{p.title}\n{p.description}"
    chash = content_hash(text)
    previous = db.get_posting_meta(conn, p.id)
    if previous is not None and previous["content_hash"] == chash:
        lang = previous["lang"]
    else:
        lang = "en" if detect(text) else "other"
    country = resolve_country(p.location_raw, p.country, cities)
    db.upsert_posting(conn, p, company_id=company_id, country=country, lang=lang, content_hash=chash, now=now)
    if lang == "en" and not db.has_label(conn, p.id, chash, classifier.version):
        db.save_label(conn, p.id, chash, classifier.version, classifier.classify(text))


async def run_crawl(conn: sqlite3.Connection, http: Http, adapters: Mapping[str, ATS], classifier: Classifier,
                    report: RunReport, now: str, cities: Mapping[str, str] | None = None,
                    detect: Callable[[str], bool] = is_english) -> None:
    by_ats: dict[str, list[sqlite3.Row]] = defaultdict(list)
    for board in db.boards_to_crawl(conn):
        by_ats[board["ats"]].append(board)

    for ats_name, boards in by_ats.items():
        adapter = adapters.get(ats_name)
        if adapter is None:
            continue

        async def fetch(board: sqlite3.Row, adapter: ATS = adapter):
            try:
                return board, "ok", await adapter.fetch(http, board["slug"])
            except BoardNotFound:
                return board, "not_found", None
            except Exception as exc:
                return board, "failed", exc

        outcomes: Counter[str] = Counter()
        seen: dict[str, set[str]] = {}
        not_found: list[str] = []
        errors: list[str] = []
        postings = 0
        for next_done in asyncio.as_completed([fetch(b) for b in boards]):
            board, outcome, result = await next_done
            if outcome == "ok":
                try:
                    for p in result:
                        _process_posting(conn, p, board["company_id"], classifier, now, cities, detect)
                    conn.commit()
                except Exception as exc:  # a bad posting fails its board, not the night
                    conn.rollback()
                    outcome, result = "failed", exc
            outcomes[outcome] += 1
            if outcome == "ok":
                seen[board["slug"]] = {p.id for p in result}
                postings += len(result)
            elif outcome == "not_found":
                not_found.append(board["slug"])
            else:
                errors.append(f"{board['slug']}: {type(result).__name__}: {result}"[:200])

        unhealthy = outcomes["failed"] + outcomes["not_found"]
        outage = len(boards) >= OUTAGE_MIN_BOARDS and unhealthy / len(boards) > OUTAGE_RATIO
        if not outage:
            for slug, ids in seen.items():
                db.record_board_result(conn, ats_name, slug, "ok")
                db.deactivate_missing(conn, ats_name, slug, ids)
            for slug in not_found:
                db.record_board_result(conn, ats_name, slug, "not_found")
        conn.commit()
        report.board_summary(ats_name, boards=len(boards), ok=outcomes["ok"], not_found=outcomes["not_found"],
                             failed=outcomes["failed"], postings=postings, outage=outage, errors=errors[:5])


async def nightly(conn: sqlite3.Connection, http: Http, *, registers: Sequence[Register],
                  adapters: Mapping[str, ATS], classifier: Classifier, seeds_path: Path | None,
                  overrides: Overrides, site_dir: Path, now: str,
                  cities: Mapping[str, str] | None = None) -> RunReport:
    report = RunReport(started_at=now)
    if seeds_path is not None:
        seed_boards(conn, seeds_path, now)
    await run_registers(conn, http, registers, report, now)
    run_match(conn, overrides)
    await run_crawl(conn, http, adapters, classifier, report, now, cities)
    report.finished_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    export_site(conn, site_dir, classifier.version, generated_at=report.finished_at, run_report=report.to_dict())
    return report
