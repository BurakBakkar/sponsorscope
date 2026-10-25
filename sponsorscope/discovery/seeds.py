"""Known ATS boards from public lists (all MIT-licensed; every slug is probed before use)."""
from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

import yaml

from sponsorscope.http import Http

# Feashliaa/job-board-aggregator moved to Riley-Dorrington/job-board-aggregator
FEASHLIAA_URL = "https://raw.githubusercontent.com/Riley-Dorrington/job-board-aggregator/main/data/{ats}_companies.json"
FEASHLIAA_ATS = ("greenhouse", "lever", "ashby", "workday")
CONORS_URL = "https://raw.githubusercontent.com/ConorsCode/open-jobs-data/main/companies.json"
OPENROLES_URL = "https://raw.githubusercontent.com/datascry/openroles/main/data/tenants/{ats}.json"
OPENROLES_NAMES = {"oracle": "oraclecloud", "pinpoint": "pinpointhq"}  # our adapter name → openroles file name
# Workday site names: public career sites vs internal boards, job-board mirrors and partial (student) lists.
WORKDAY_SITE_GOOD = ("external", "career", "job", "ext")
WORKDAY_SITE_BAD = ("internal", "broadbean", "equest", "linkedin", "indeed", "campus", "student", "university",
                    "early", "graduate", "staff", "employee", "private", "faculty")
WORKDAY_HOST = re.compile(r"[a-z0-9-]+\.wd\d+\.myworkdayjobs\.com")


@dataclass(frozen=True)
class Seed:
    ats: str
    slug: str
    name: str | None


def parse_feashliaa(ats: str, data: object) -> list[Seed]:
    """Flat slug lists; the workday list holds "tenant|wdN|site" strings."""
    seeds = []
    for s in data or []:
        if not isinstance(s, str) or not s.strip():
            continue
        if ats == "workday":
            tenant, _, rest = s.strip().partition("|")
            shard, _, site = rest.partition("|")
            slug = _workday_slug(f"{tenant}.{shard}.myworkdayjobs.com", site)
            if slug:
                seeds.append(Seed(ats, slug, None))
        else:
            seeds.append(Seed(ats, s.strip(), None))
    return seeds


def _workday_slug(host: str, site: str) -> str | None:
    host, site = host.strip().lower(), site.strip().lower()
    return f"{host}/{site}" if WORKDAY_HOST.fullmatch(host) and site and "/" not in site else None


def parse_conors(data: object, supported: set[str]) -> list[Seed]:
    seeds = []
    for entry in data or []:
        if isinstance(entry, dict) and entry.get("platform") in supported and entry.get("slug"):
            seeds.append(Seed(entry["platform"], str(entry["slug"]).strip(), entry.get("name")))
    return seeds


def parse_openroles(ats: str, data: object) -> list[Seed]:
    """openroles marks each tenant live/dead from its own probes; only live ones are worth our budget.

    Workday and Oracle tenants keep their career-site address in metadata {host, site}.
    """
    seeds = []
    for e in data or []:
        if not isinstance(e, dict) or e.get("status") != "live":
            continue
        meta = e.get("metadata") or {}
        if ats == "workday":
            slug = _workday_slug(meta.get("host") or "", meta.get("site") or "")
        elif ats == "oracle":
            host, site = (meta.get("host") or "").strip().lower(), (meta.get("site") or "").strip()
            slug = f"{host}/{site}" if host.endswith(".oraclecloud.com") and site and "/" not in site else None
        else:
            slug = str(e.get("slug") or "").strip()
        if slug:
            seeds.append(Seed(ats, slug, e.get("display_name")))
    return seeds


def pick_workday_site(sites: list[str]) -> str:
    """The one career site to crawl for a Workday tenant that lists several (e.g. ["external", "internal"]).

    Sites of one tenant usually repeat the same postings, so crawling them all would show duplicates.
    """
    return min(sites, key=lambda site: (-_site_score(site), len(site), site))  # ties: shortest, then alphabetical


def _site_score(site: str) -> int:
    score = sum(word in site for word in WORKDAY_SITE_GOOD) - 2 * sum(word in site for word in WORKDAY_SITE_BAD)
    return score - 2 * ("intern" in site.replace("international", "") and "external" not in site)


def one_site_per_tenant(seeds: list[Seed]) -> list[Seed]:
    """Workday seeds collapsed to one site per tenant; named (hand-seeded) sites are all kept and win."""
    by_host: dict[str, list[Seed]] = defaultdict(list)
    out = []
    for seed in seeds:
        if seed.ats == "workday":
            by_host[seed.slug.partition("/")[0].lower()].append(seed)
        else:
            out.append(seed)
    for group in by_host.values():
        named = [s for s in group if s.name]
        if named:
            out += list(dict.fromkeys(named))
            continue
        site = pick_workday_site(sorted({s.slug.partition("/")[2] for s in group}))
        out.append(next(s for s in group if s.slug.partition("/")[2] == site))
    return out


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
    for ats in sorted(supported):
        try:
            resp = await http.get(OPENROLES_URL.format(ats=OPENROLES_NAMES.get(ats, ats)))
            if resp.status_code == 404:  # openroles has no list for this ATS
                continue
            resp.raise_for_status()
            seeds += parse_openroles(ats, resp.json())
        except Exception as exc:
            errors.append(f"openroles {ats}: {type(exc).__name__}: {exc}"[:200])
    return seeds, errors
