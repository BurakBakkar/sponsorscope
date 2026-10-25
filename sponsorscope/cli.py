from __future__ import annotations

import asyncio
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated

import typer

from sponsorscope import pipeline
from sponsorscope.ats.ashby import Ashby
from sponsorscope.ats.breezy import Breezy
from sponsorscope.ats.greenhouse import Greenhouse
from sponsorscope.ats.jobtech import JobTech
from sponsorscope.ats.lever import Lever
from sponsorscope.ats.oracle import OracleRecruiting
from sponsorscope.ats.personio import Personio
from sponsorscope.ats.pinpoint import Pinpoint
from sponsorscope.ats.recruitee import Recruitee
from sponsorscope.ats.rippling import Rippling
from sponsorscope.ats.rss import UniversityRss
from sponsorscope.ats.smartrecruiters import SmartRecruiters
from sponsorscope.ats.successfactors import SuccessFactors
from sponsorscope.ats.teamtailor import Teamtailor
from sponsorscope.ats.workable import Workable
from sponsorscope.ats.workday import Workday
from sponsorscope.classify.rules import RulesClassifier
from sponsorscope.discovery.probe import run_discovery
from sponsorscope.discovery.seeds import fetch_remote_seeds, load_manual, one_site_per_tenant
from sponsorscope.export.shards import export_site
from sponsorscope.http import Http
from sponsorscope.matching.names import Overrides
from sponsorscope.registers.base import RegisterBlocked
from sponsorscope.registers.ca import CaRegister
from sponsorscope.registers.dk import DkRegister
from sponsorscope.registers.fi import FiRegister
from sponsorscope.registers.gb import UkRegister
from sponsorscope.registers.ie import IeRegister
from sponsorscope.registers.nl import NlRegister
from sponsorscope.registers.us import UsRegister
from sponsorscope.report import RunReport
from sponsorscope.store.db import connect

app = typer.Typer(no_args_is_help=True, add_completion=False, help="Visa-sponsorship job tracker pipeline.")

Db = Annotated[Path, typer.Option("--db", help="SQLite database path")]
Site = Annotated[Path, typer.Option("--site", help="Static site directory")]
Seeds = Annotated[Path, typer.Option("--seeds", help="Seed boards YAML")]
OverridesPath = Annotated[Path, typer.Option("--overrides", help="Match overrides YAML")]
AcceptShrink = Annotated[list[str], typer.Option("--accept-shrink", help="Skip the shrink guard for SOURCE this run")]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _registers():
    return [UkRegister(), NlRegister(), DkRegister(), FiRegister(), UsRegister(), CaRegister(), IeRegister()]


def _adapters():
    adapters = [Greenhouse(), Lever(), Ashby(), Workable(), SmartRecruiters(), Recruitee(), Personio(), Pinpoint(),
                Rippling(), Breezy(), Teamtailor()]
    return {a.name: a for a in adapters}


def _seed_only_adapters():
    """Career sites with host-specific addresses: found in seed lists, never slug-guessed."""
    return {a.name: a for a in [OracleRecruiting(), Workday(), SuccessFactors()]}


def _crawl_adapters():
    """Discovery adapters plus sources whose boards are only ever seeded (by hand or from public lists)."""
    manual = [UniversityRss(), JobTech()]
    return {**_adapters(), **_seed_only_adapters(), **{a.name: a for a in manual}}


def _run_with_http(make_coro):
    async def runner():
        http = Http()
        try:
            return await make_coro(http)
        finally:
            await http.aclose()

    return asyncio.run(runner())


def _print_warnings(report: RunReport) -> None:
    for warning in report.warnings():
        typer.echo(f"::warning::{warning}")


@app.command()
def seed(db: Db = Path("sponsorscope.db"), seeds: Seeds = Path("seeds/manual.yaml")) -> None:
    """Load known boards from the seeds file."""
    n = pipeline.seed_boards(connect(db), seeds, _now())
    typer.echo(f"seeded {n} boards")


@app.command("registers")
def registers_cmd(db: Db = Path("sponsorscope.db"), accept_shrink: AcceptShrink = []) -> None:
    """Refresh every sponsor register whose version changed."""
    conn, report = connect(db), RunReport(started_at=_now())
    _run_with_http(lambda http: pipeline.run_registers(conn, http, _registers(), report, report.started_at,
                                                       accept_shrink=frozenset(accept_shrink)))
    for name, info in report.sources.items():
        typer.echo(f"{name}: {info}")
    _print_warnings(report)


@app.command()
def match(db: Db = Path("sponsorscope.db"), overrides: OverridesPath = Path("overrides.yaml")) -> None:
    """Re-match sponsors to companies."""
    typer.echo(f"{pipeline.run_match(connect(db), Overrides.load(overrides))} matches")


@app.command()
def crawl(db: Db = Path("sponsorscope.db")) -> None:
    """Fetch all known boards, resolve countries, filter English, classify."""
    conn, report = connect(db), RunReport(started_at=_now())
    _run_with_http(lambda http: pipeline.run_crawl(conn, http, _crawl_adapters(), RulesClassifier(), report, report.started_at))
    for name, info in report.ats.items():
        typer.echo(f"{name}: {info}")
    _print_warnings(report)


@app.command()
def export(db: Db = Path("sponsorscope.db"), site: Site = Path("site")) -> None:
    """Write site/data shards and index from the database."""
    counts = export_site(connect(db), site, RulesClassifier.version, generated_at=_now())
    typer.echo(f"exported {sum(counts.values())} postings across {len(counts)} countries")


@app.command()
def nightly(db: Db = Path("sponsorscope.db"), site: Site = Path("site"),
            seeds: Seeds = Path("seeds/manual.yaml"), overrides: OverridesPath = Path("overrides.yaml")) -> None:
    """Full run: seed → registers → match → crawl → export."""
    conn = connect(db)
    report = _run_with_http(lambda http: pipeline.nightly(
        conn, http, registers=_registers(), adapters=_crawl_adapters(), classifier=RulesClassifier(),
        seeds_path=seeds, overrides=Overrides.load(overrides), site_dir=site, now=_now()))
    _print_warnings(report)
    total = sum(info["postings"] for info in report.ats.values())
    typer.echo(f"done: {total} postings crawled, {len(report.warnings())} warnings")


SMOKE_BOARDS = {"greenhouse": "airbnb", "lever": "palantir", "ashby": "notion", "workable": "huggingface",
                "smartrecruiters": "Ubisoft2", "recruitee": "bunq", "personio": "tado", "pinpoint": "twiningsovocareers",
                "rippling": "bamboo-health-careers", "breezy": "soko-glam",
                "teamtailor": "hirschbednerassociates"}


@app.command()
def discover(db: Db = Path("sponsorscope.db"), seeds: Seeds = Path("seeds/manual.yaml"),
             overrides: OverridesPath = Path("overrides.yaml"),
             budget: Annotated[int, typer.Option(help="Max probes this run")] = 50_000,
             remote_seeds: Annotated[bool, typer.Option(help="Fetch public seed lists")] = True) -> None:
    """Weekly: refresh registers, probe seed/known boards, guess slugs for unmatched sponsors."""
    conn, now = connect(db), _now()
    report = RunReport(started_at=now)
    adapters = {**_adapters(), **_seed_only_adapters()}

    async def run(http):
        await pipeline.run_registers(conn, http, _registers(), report, now)
        pipeline.run_match(conn, Overrides.load(overrides))
        all_seeds = load_manual(seeds)
        errors: list[str] = []
        if remote_seeds:
            remote, errors = await fetch_remote_seeds(http, set(adapters))
            all_seeds += remote
        summary = await run_discovery(conn, http, adapters, seeds=one_site_per_tenant(all_seeds), now=now,
                                      budget=budget, guess_ats=set(_adapters()))
        pipeline.run_match(conn, Overrides.load(overrides))
        return summary, errors

    summary, errors = _run_with_http(run)
    _print_warnings(report)
    for error in errors:
        typer.echo(f"::warning::seed source failed: {error}")
    typer.echo("discovery: " + ", ".join(f"{k}={v}" for k, v in sorted(summary.items())))


@app.command()
def smoke() -> None:
    """Live check: one real board per ATS and the version signal of each register."""
    async def run(http):
        failures = []
        for ats, adapter in _adapters().items():
            slug = SMOKE_BOARDS[ats]
            try:
                postings = await adapter.fetch(http, slug)
                typer.echo(f"ok      {ats}:{slug} → {len(postings)} postings")
            except Exception as exc:
                failures.append(ats)
                typer.echo(f"FAIL    {ats}:{slug} → {type(exc).__name__}: {exc}")
        for reg in _registers():
            try:
                typer.echo(f"ok      {reg.name} → {await reg.latest(http)}")
            except RegisterBlocked as exc:
                typer.echo(f"blocked {reg.name} → {exc}")
            except Exception as exc:
                failures.append(reg.name)
                typer.echo(f"FAIL    {reg.name} → {type(exc).__name__}: {exc}")
        return failures

    if _run_with_http(run):
        raise typer.Exit(1)


@app.command("check-db")
def check_db(db: Db = Path("sponsorscope.db")) -> None:
    """PRAGMA integrity_check; exits non-zero if the database is corrupt."""
    connect(db).close()
    result = sqlite3.connect(db).execute("PRAGMA integrity_check").fetchone()[0]
    if result != "ok":
        typer.echo(f"integrity_check failed: {result}", err=True)
        raise typer.Exit(1)
    typer.echo("ok")
