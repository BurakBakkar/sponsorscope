from __future__ import annotations

import asyncio
import re
import sqlite3
from collections import Counter
from collections.abc import Collection, Iterable, Mapping

BROKEN_ERROR_RATIO = 0.5  # an ATS erroring on more than half its probes this run is treated as down
BROKEN_MIN_PROBES = 3

from sponsorscope.ats.base import ATS, ProbeResult
from sponsorscope.discovery.seeds import Seed
from sponsorscope.discovery.slugs import candidates
from sponsorscope.http import Http
from sponsorscope.matching.names import normalize
from sponsorscope.store import db


async def _probe_many(http: Http, adapters: Mapping[str, ATS], targets: Iterable[tuple[str, str]]):
    async def one(ats: str, slug: str):
        try:
            return (ats, slug), await adapters[ats].probe(http, slug)
        except Exception as exc:  # transient: caller must not count it as a miss
            return (ats, slug), exc

    unique = list(dict.fromkeys(targets))
    return dict(await asyncio.gather(*(one(a, s) for a, s in unique)))


def _slug_display(slug: str) -> str:
    return re.sub(r"[-_]+", " ", slug).strip().title() or slug


async def run_discovery(conn: sqlite3.Connection, http: Http, adapters: Mapping[str, ATS], *,
                        seeds: Iterable[Seed], now: str, budget: int,
                        guess_ats: Collection[str] | None = None) -> dict[str, int]:
    """guess_ats: adapters whose slugs can be guessed from a name (default all); the others only probe seeds."""
    summary: Counter[str] = Counter()

    for seed in seeds:
        if seed.ats in adapters and seed.slug:
            company_id = db.get_or_create_company(conn, seed.name) if seed.name else None
            summary["seeds_added"] += db.add_seed_board(conn, seed.ats, seed.slug, company_id, now)
    conn.commit()

    # 1. known boards: new seeds, misses whose backoff expired, gone boards
    due = [(b["ats"], b["slug"]) for b in db.due_boards(conn, now, budget) if b["ats"] in adapters]
    results = await _probe_many(http, adapters, due)
    summary["probes"] += len(results)
    for (ats, slug), result in results.items():
        if isinstance(result, Exception):
            summary["probe_errors"] += 1
            continue
        company_id = None
        if result.exists and db.board_company(conn, ats, slug) is None:
            company_id = db.get_or_create_company(conn, result.name or _slug_display(slug),
                                                  verified=result.name is not None)
        db.record_probe(conn, ats, slug, exists=result.exists, company_id=company_id, now=now)
        summary["boards_found" if result.exists else "boards_missed"] += 1
    conn.commit()

    # 2. guesses from unmatched sponsor names, within the remaining budget
    remaining = budget - len(results)
    planned: list[tuple[str, list[tuple[str, str]]]] = []
    guessable = {ats: a for ats, a in adapters.items() if guess_ats is None or ats in guess_ats}
    for row in db.sponsors_to_guess(conn, now, limit=max(remaining, 0)):
        norm = row["norm_name"]
        targets = [(ats, slug) for ats, adapter in guessable.items()
                   for slug in candidates(norm, verifiable=adapter.provides_name)
                   if not db.board_exists(conn, ats, slug)]
        if not targets:
            db.record_guess_attempt(conn, norm, found=False, now=now)
            continue
        if len(targets) > remaining:
            break
        remaining -= len(targets)
        planned.append((norm, targets))

    results = await _probe_many(http, adapters, [t for _, ts in planned for t in ts])
    summary["probes"] += len(results)
    tried: Counter[str] = Counter(ats for ats, _ in results)
    failed: Counter[str] = Counter(ats for (ats, _), r in results.items() if isinstance(r, Exception))
    broken = {ats for ats in tried if tried[ats] >= BROKEN_MIN_PROBES and failed[ats] / tried[ats] > BROKEN_ERROR_RATIO}
    summary["broken_ats"] = len(broken)
    for norm, targets in planned:
        found = errored = answered = False
        for ats, slug in targets:
            result: ProbeResult | Exception = results[(ats, slug)]
            if isinstance(result, Exception):
                summary["probe_errors"] += 1
                errored = errored or ats not in broken  # a down ATS must not stall every sponsor forever
                continue
            answered = True
            summary["guesses_probed"] += 1
            if not result.exists:
                continue
            adapter = adapters[ats]
            if adapter.provides_name and (result.name is None or normalize(result.name) != norm):
                summary["guesses_rejected"] += 1  # e.g. board "atlas" named "Atlas" ≠ "Atlas Care Homes"
                continue
            company_id = (db.get_or_create_company(conn, result.name) if adapter.provides_name
                          else db.get_or_create_company(conn, norm.title(), verified=False))
            db.upsert_board(conn, ats, slug, company_id, status="hit", origin="guess", now=now)
            summary["guesses_found"] += 1
            found = True
        if found or (answered and not errored):
            db.record_guess_attempt(conn, norm, found=found, now=now)
    conn.commit()
    return dict(summary)
