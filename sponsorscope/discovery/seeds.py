"""Known ATS boards from public lists (both MIT-licensed; every slug is probed before use)."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from sponsorscope.http import Http

FEASHLIAA_URL = "https://raw.githubusercontent.com/Feashliaa/job-board-aggregator/main/data/{ats}_companies.json"
FEASHLIAA_ATS = ("greenhouse", "lever", "ashby")
CONORS_URL = "https://raw.githubusercontent.com/ConorsCode/open-jobs-data/main/companies.json"


@dataclass(frozen=True)
class Seed:
    ats: str
    slug: str
    name: str | None


def parse_feashliaa(ats: str, data: object) -> list[Seed]:
    return [Seed(ats, s.strip(), None) for s in data or [] if isinstance(s, str) and s.strip()]


def parse_conors(data: object, supported: set[str]) -> list[Seed]:
    seeds = []
    for entry in data or []:
        if isinstance(entry, dict) and entry.get("platform") in supported and entry.get("slug"):
            seeds.append(Seed(entry["platform"], str(entry["slug"]).strip(), entry.get("name")))
    return seeds


def load_manual(path: Path) -> list[Seed]:
    if not path.exists():
        return []
    return [Seed(e["ats"], e["slug"], e.get("name")) for e in yaml.safe_load(path.read_text()) or []]


async def fetch_remote_seeds(http: Http, supported: set[str]) -> tuple[list[Seed], list[str]]:
    seeds: list[Seed] = []
    errors: list[str] = []
    for ats in FEASHLIAA_ATS:
        if ats not in supported:
            continue
        try:
            resp = await http.get(FEASHLIAA_URL.format(ats=ats))
            resp.raise_for_status()
            seeds += parse_feashliaa(ats, resp.json())
        except Exception as exc:
            errors.append(f"feashliaa {ats}: {type(exc).__name__}: {exc}"[:200])
    try:
        resp = await http.get(CONORS_URL)
        resp.raise_for_status()
        seeds += parse_conors(resp.json(), supported)
    except Exception as exc:
        errors.append(f"open-jobs-data: {type(exc).__name__}: {exc}"[:200])
    return seeds, errors
