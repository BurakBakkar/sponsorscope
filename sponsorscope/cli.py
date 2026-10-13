from __future__ import annotations

import asyncio
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated

import typer

from sponsorscope import pipeline
from sponsorscope.ats.ashby import Ashby
from sponsorscope.ats.greenhouse import Greenhouse
from sponsorscope.ats.lever import Lever
from sponsorscope.ats.personio import Personio
from sponsorscope.ats.recruitee import Recruitee
from sponsorscope.ats.smartrecruiters import SmartRecruiters
from sponsorscope.ats.workable import Workable
from sponsorscope.classify.rules import RulesClassifier
from sponsorscope.export.shards import export_site
from sponsorscope.http import Http
from sponsorscope.matching.names import Overrides
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
    adapters = [Greenhouse(), Lever(), Ashby(), Workable(), SmartRecruiters(), Recruitee(), Personio()]
    return {a.name: a for a in adapters}


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
    _run_with_http(lambda http: pipeline.run_crawl(conn, http, _adapters(), RulesClassifier(), report, report.started_at))
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
        conn, http, registers=_registers(), adapters=_adapters(), classifier=RulesClassifier(),
        seeds_path=seeds, overrides=Overrides.load(overrides), site_dir=site, now=_now()))
    _print_warnings(report)
    total = sum(info["postings"] for info in report.ats.values())
    typer.echo(f"done: {total} postings crawled, {len(report.warnings())} warnings")


@app.command("check-db")
def check_db(db: Db = Path("sponsorscope.db")) -> None:
    """PRAGMA integrity_check; exits non-zero if the database is corrupt."""
    connect(db).close()
    result = sqlite3.connect(db).execute("PRAGMA integrity_check").fetchone()[0]
    if result != "ok":
        typer.echo(f"integrity_check failed: {result}", err=True)
        raise typer.Exit(1)
    typer.echo("ok")
