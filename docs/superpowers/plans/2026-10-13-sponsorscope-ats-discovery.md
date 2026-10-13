# sponsorscope ATS Adapters + Discovery (Plan 3 of 3) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the remaining five job-board adapters (Ashby, Workable,
SmartRecruiters, Recruitee and Personio) and weekly discovery. Discovery seeds
boards from public slug lists, guesses slugs from sponsor names, and probes them
with backoff. Also add the weekly-discover and smoke workflows.

**Architecture:**
- Each adapter implements the `ATS` protocol from Plan 1, extended with two
  things:
  - `probe(http, slug) -> ProbeResult`, which says whether a board exists and
    returns the company name when the ATS exposes one
  - a `known_ids` hint, so SmartRecruiters only makes detail calls for postings
    it hasn't seen before
- Discovery lives in `sponsorscope/discovery/` and only writes to the `boards`
  and `discovery_progress` tables. The nightly crawl picks up new `hit` boards
  without any other change.

**Tech Stack:** As in Plan 1, plus `defusedxml` for Personio's untrusted XML.

**Spec:** `docs/superpowers/specs/2026-10-13-sponsorscope-design.md` (§2.2 ATS
table, §5 slug guessing, §6.2 weekly discovery, §8 politeness, §10 live smoke)

**Builds on:**
- Plan 1: `docs/superpowers/plans/2026-10-13-sponsorscope-core-pipeline.md`
- Plan 2 (registers): uses `registers.base.RegisterBlocked` in the smoke command.

## Global Constraints

- Everything from Plan 1's Global Constraints still applies:
  - no `Co-Authored-By` or any Claude attribution in commits
  - no push until the user confirms
  - the same User-Agent and HTTP defaults
- **Rate limiting is per registrable domain**, the last two hostname labels.
  Recruitee (`{slug}.recruitee.com`) and Personio (`{slug}.jobs.personio.de`)
  put every company on its own subdomain. A per-hostname limiter would therefore
  not limit them at all.
- Missed probes back off **1 week → 4 weeks → 12 weeks** (spec §6.2).
- Discovery has a **probe budget per run**, 50,000 by default, configurable
  with `--budget`.
- **Guessed slugs must be safe.**
  - On ATSes that return a company name (Greenhouse, Workable), a guessed hit
    counts only if `normalize(board name) == sponsor norm`.
  - On ATSes without a name, a guess is made only when the compacted sponsor
    name is at least 8 characters long. First-token guesses are made only on
    name-returning ATSes.
- A guess is never made for a sponsor whose compacted name is 4 characters or
  fewer (spec §5, the short-name guard).
- Lever slugs are case-sensitive. Guesses are lowercase only.

### Interpretations of the spec (decided here)

1. **Slug guesses are not stored as board rows until they hit.** Progress is
   tracked per sponsor in a `discovery_progress` table. Storing every guessed
   miss would mean millions of rows a year, while per-sponsor progress stays
   bounded by the number of sponsors.
2. **Which sponsors get guessed first:**
   - those with the highest `filings` count (history sources, i.e. the employers
     that sponsor most)
   - then non-UK licence sponsors
   - then the UK register, which has about 120k organisations, many of them
     small, with lower odds of using one of these ATSes
3. **`RawPosting.description` may be `None`.** It means "known posting, not
   re-fetched", and is used by SmartRecruiters for IDs it has already seen. The
   pipeline then refreshes the metadata and `last_seen` and keeps the stored
   hash, language and label.
4. **Seed boards from lists without company names** (Feashliaa) get a display
   name derived from the probe (Greenhouse or Workable name) or from the slug.

## Review Focus

1. **Subdomain-per-company hosts go unthrottled.** Recruitee and Personio must
   share one limiter per domain. [Task 1]
2. **A false guessed hit attaches the wrong company to a sponsor.** For
   example, the Greenhouse board "atlas" named "Atlas" must not be linked to
   "Atlas Care Homes Ltd". [Task 12]
3. **SmartRecruiters "200 empty" for a non-existent company** must not register
   as a live board. [Task 6]
4. **Personio returns HTML for unknown slugs, and XML can be hostile.** It must
   be parsed safely, and a non-XML 200 response must not become a board.
   [Task 8]
5. **A transient probe error must not back off a sponsor or turn a seed into a
   miss.** [Task 12]

---

## File Map

```
sponsorscope/http.py                       # modify: limiter keyed by registrable domain
sponsorscope/geo/country.py                # modify: country_code(); split state names from country names
sponsorscope/models.py                     # modify: RawPosting.description may be None
sponsorscope/ats/base.py                   # modify: ProbeResult, probe(), provides_name, known_ids
sponsorscope/ats/greenhouse.py, lever.py   # modify: probe()
sponsorscope/ats/ashby.py, workable.py, smartrecruiters.py, recruitee.py, personio.py   # new
sponsorscope/store/db.py                   # modify: discovery tables/functions, active_posting_ids, touch_posting
sponsorscope/pipeline.py                   # modify: known_ids + description=None handling
sponsorscope/discovery/__init__.py, seeds.py, slugs.py, probe.py   # new
sponsorscope/cli.py                        # modify: all adapters, discover, smoke
.github/workflows/weekly-discover.yml, smoke.yml   # new
tests/test_ats_*.py, tests/test_discovery.py, tests/test_http.py, tests/test_geo.py, tests/test_pipeline.py
```

---

### Task 1: Rate-limit per registrable domain

**Files:**
- Modify: `sponsorscope/http.py`
- Test: `tests/test_http.py`

**Interfaces:**
- Produces: `rate_key(host: str) -> str`. `Http._limiter(host)` now groups hosts by `rate_key`.

- [ ] **Step 1: Write the failing test.** Append to `tests/test_http.py`:

```python
from sponsorscope.http import rate_key


def test_rate_key_groups_subdomains():
    assert rate_key("bunq.recruitee.com") == rate_key("picnic.recruitee.com") == "recruitee.com"
    assert rate_key("tado.jobs.personio.de") == "personio.de"
    assert rate_key("api.eu.lever.co") == rate_key("api.lever.co") == "lever.co"
    assert rate_key("localhost") == "localhost"


async def test_subdomains_share_one_limiter(http):
    assert http._limiter("a.recruitee.com") is http._limiter("b.recruitee.com")
    assert http._limiter("a.recruitee.com") is not http._limiter("api.ashbyhq.com")
```

- [ ] **Step 2: Run the tests**

Run: `uv run pytest tests/test_http.py -q`
Expected: FAIL with `ImportError: cannot import name 'rate_key'`

- [ ] **Step 3: Implement.** In `sponsorscope/http.py`, add this after `Sleep = ...`:

```python
def rate_key(host: str) -> str:
    """Hosts sharing a registrable domain share one limiter ({slug}.recruitee.com → recruitee.com)."""
    parts = host.split(".")
    return ".".join(parts[-2:]) if len(parts) > 2 else host
```

Then replace the body of `Http._limiter` with:

```python
    def _limiter(self, host: str) -> _HostLimiter:
        key = rate_key(host)
        if key not in self._limiters:
            self._limiters[key] = _HostLimiter(self._concurrency, self._rate, self._sleep)
        return self._limiters[key]
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/test_http.py -q`
Expected: 11 passed

- [ ] **Step 5: Commit**

```bash
git add sponsorscope/http.py tests/test_http.py
git commit -m "feat: rate-limit per registrable domain so per-company subdomains share a limiter"
```

---

### Task 2: `country_code()` for structured ATS country fields

**Files:**
- Modify: `sponsorscope/geo/country.py`
- Test: `tests/test_geo.py`

**Interfaces:**
- Produces: `country_code(value: str | None) -> str | None`. It accepts ISO-2 in any case, ISO-3, or an English country name. US state and Canadian province names are not treated as countries here.

- [ ] **Step 1: Write the failing test.** Append to `tests/test_geo.py`:

```python
from sponsorscope.geo.country import country_code


@pytest.mark.parametrize(
    "value, expected",
    [("ro", "RO"), ("NL", "NL"), ("United States", "US"), ("Netherlands", "NL"), ("GBR", "GB"),
     ("United Kingdom", "GB"), ("Georgia", "GE"), ("European Union", None), ("", None), (None, None)],
)
def test_country_code(value, expected):
    assert country_code(value) == expected
```

- [ ] **Step 2: Run the tests**

Run: `uv run pytest tests/test_geo.py -q`
Expected: FAIL with `ImportError: cannot import name 'country_code'`

- [ ] **Step 3: Implement.** In `sponsorscope/geo/country.py`:

1. Rename `_EXTRA` to `_ALIASES`, and remove the two `**{...}` state and province lines from it.
2. Add `_REGIONS = {**{s: "US" for s in _US_STATES}, **{p: "CA" for p in _CA_PROVINCES}}`. Its comment: state and province names; override the country Georgia in free-text locations only.
3. Replace `_country_names` with the code below.
4. In `resolve_country`, keep using `_country_names()`.

```python
@lru_cache(maxsize=1)
def _country_only_names() -> dict[str, str]:
    names: dict[str, str] = {}
    for c in pycountry.countries:
        for attr in ("name", "official_name", "common_name"):
            value = getattr(c, attr, None)
            if value:
                names[value.lower()] = c.alpha_2
    names.update(_ALIASES)
    return names


@lru_cache(maxsize=1)
def _country_names() -> dict[str, str]:
    """Names usable in free-text locations: countries plus US states / CA provinces."""
    return {**_country_only_names(), **_REGIONS}


def country_code(value: str | None) -> str | None:
    """ISO-2 for a structured country field: 'ro', 'NL', 'GBR', 'United States'."""
    if not value or not value.strip():
        return None
    v = value.strip()
    alpha2, alpha3 = _codes()
    if len(v) == 2 and v.upper() in alpha2:
        return v.upper()
    if len(v) == 3 and v.upper() in alpha3:
        return alpha3[v.upper()]
    return _country_only_names().get(v.lower())
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/test_geo.py -q`
Expected: all passed (38)

- [ ] **Step 5: Commit**

```bash
git add sponsorscope/geo/country.py tests/test_geo.py
git commit -m "feat: country_code() for structured ATS country fields"
```

---

### Task 3: ATS protocol (`probe`, `provides_name`, `known_ids`), plus Greenhouse and Lever probes

**Files:**
- Modify: `sponsorscope/ats/base.py`, `sponsorscope/ats/greenhouse.py`, `sponsorscope/ats/lever.py`, `sponsorscope/models.py`
- Test: `tests/test_ats_greenhouse.py`, `tests/test_ats_lever.py`

**Interfaces:**
- Produces:
  - `ProbeResult(exists: bool, name: str | None = None)`, frozen
  - Updated `ATS` Protocol:
    - attributes `name: str` and `provides_name: bool`
    - `async fetch(http, slug, known_ids: frozenset[str] = frozenset()) -> list[RawPosting]`
    - `async probe(http, slug) -> ProbeResult`
  - Constant `SUBDOMAIN_SLUG` (a regex for slugs that are safe to use as a DNS label)
  - `RawPosting.description: str | None`

- [ ] **Step 1: Write the failing tests.** Append to `tests/test_ats_greenhouse.py`:

```python
async def test_probe_reports_board_name(http, respx_mock):
    respx_mock.get("https://boards-api.greenhouse.io/v1/boards/acme").mock(
        return_value=httpx.Response(200, json={"name": "Acme Widgets", "content": ""}))
    respx_mock.get("https://boards-api.greenhouse.io/v1/boards/nope").mock(return_value=httpx.Response(404))
    gh = Greenhouse()
    assert gh.provides_name is True
    assert (await gh.probe(http, "acme")).name == "Acme Widgets"
    assert (await gh.probe(http, "nope")).exists is False


async def test_probe_server_error_raises(http, respx_mock):
    respx_mock.get("https://boards-api.greenhouse.io/v1/boards/acme").mock(return_value=httpx.Response(500))
    with pytest.raises(httpx.HTTPStatusError):
        await Greenhouse().probe(http, "acme")
```

Append to `tests/test_ats_lever.py`:

```python
async def test_probe_checks_both_hosts(http, respx_mock):
    mock_host(respx_mock, "api.lever.co", "euco", httpx.Response(404))
    mock_host(respx_mock, "api.eu.lever.co", "euco", httpx.Response(200, json=[]))
    mock_host(respx_mock, "api.lever.co", "nope", httpx.Response(404))
    mock_host(respx_mock, "api.eu.lever.co", "nope", httpx.Response(404))
    lever = Lever()
    assert lever.provides_name is False
    assert (await lever.probe(http, "euco")).exists is True
    assert (await lever.probe(http, "nope")).exists is False
```

- [ ] **Step 2: Run the tests**

Run: `uv run pytest tests/test_ats_greenhouse.py tests/test_ats_lever.py -q`
Expected: FAIL with `AttributeError: 'Greenhouse' object has no attribute 'provides_name'`

- [ ] **Step 3: Implement.**

In `sponsorscope/models.py`, change the `RawPosting.description` line to:

```python
    description: str | None  # plain text; None = known posting not re-fetched (keep stored label)
```

Replace `sponsorscope/ats/base.py` with:

```python
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol

from sponsorscope.http import Http
from sponsorscope.models import RawPosting

SUBDOMAIN_SLUG = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?")


class BoardNotFound(Exception):
    """The ATS says this board/slug does not exist."""


@dataclass(frozen=True)
class ProbeResult:
    exists: bool
    name: str | None = None  # company name, for ATSes that expose one


class ATS(Protocol):
    name: str
    provides_name: bool  # probe() returns the company name → guessed hits can be verified

    async def fetch(self, http: Http, slug: str, known_ids: frozenset[str] = frozenset()) -> list[RawPosting]:
        """All current postings on a board. Raises BoardNotFound if the board doesn't exist.

        known_ids: posting ids already stored for this board; adapters with expensive
        per-posting detail calls may return description=None for these.
        """
        ...

    async def probe(self, http: Http, slug: str) -> ProbeResult: ...


def infer_remote(text: str | None) -> str | None:
    low = (text or "").lower()
    if "hybrid" in low:
        return "hybrid"
    if "remote" in low:
        return "remote"
    return None
```

In `sponsorscope/ats/greenhouse.py`:
- change the import to `from sponsorscope.ats.base import BoardNotFound, ProbeResult, infer_remote`
- add the class attribute `provides_name = True`
- change the signature to `async def fetch(self, http: Http, slug: str, known_ids: frozenset[str] = frozenset()) -> list[RawPosting]:`
- add the method below:

```python
    async def probe(self, http: Http, slug: str) -> ProbeResult:
        resp = await http.get(f"{BASE}/{slug}")
        if resp.status_code == 404:
            return ProbeResult(False)
        resp.raise_for_status()
        return ProbeResult(True, resp.json().get("name"))
```

In `sponsorscope/ats/lever.py`:
- change the import to `from sponsorscope.ats.base import BoardNotFound, ProbeResult, infer_remote`
- add `provides_name = False`
- give `fetch` the same new signature
- add the method below:

```python
    async def probe(self, http: Http, slug: str) -> ProbeResult:
        for host in HOSTS:
            resp = await http.get(f"{host}/v0/postings/{slug}", params={"mode": "json", "limit": 1})
            if resp.status_code == 404:
                continue
            resp.raise_for_status()
            return ProbeResult(True)
        return ProbeResult(False)
```

- [ ] **Step 4: Run all the tests**

Run: `uv run pytest -q`
Expected: all passed

- [ ] **Step 5: Commit**

```bash
git add sponsorscope/models.py sponsorscope/ats tests/test_ats_greenhouse.py tests/test_ats_lever.py
git commit -m "feat: ATS probe() and known_ids hint; Greenhouse and Lever probes"
```

---

### Task 4: Ashby adapter

**Files:**
- Create: `sponsorscope/ats/ashby.py`, `tests/test_ats_ashby.py`

**Interfaces:**
- Consumes: `ProbeResult`, `BoardNotFound` and `infer_remote` (Task 3), `country_code` (Task 2), `html_to_text`
- Produces: `Ashby` (`name="ashby"`, `provides_name=False`)

- [ ] **Step 1: Write the failing tests** in `tests/test_ats_ashby.py`

```python
import httpx
import pytest

from sponsorscope.ats.ashby import Ashby
from sponsorscope.ats.base import BoardNotFound

URL = "https://api.ashbyhq.com/posting-api/job-board/notion"
JOB = {
    "id": "0d1c-uuid", "title": "Software Engineer, Infrastructure ", "jobUrl": "https://jobs.ashbyhq.com/notion/0d1c-uuid",
    "descriptionPlain": "We can sponsor visas.\nBuild infra.", "descriptionHtml": "<p>ignored</p>",
    "location": "San Francisco, California", "isRemote": True, "workplaceType": "Hybrid", "isListed": True,
    "address": {"postalAddress": {"addressCountry": "United States", "addressLocality": "San Francisco"}},
    "publishedAt": "2024-03-04T14:29:08.532+00:00",
}


async def test_parses_and_prefers_workplace_type_over_is_remote(http, respx_mock):
    unlisted = {**JOB, "id": "hidden", "isListed": False}
    eu = {**JOB, "id": "eu", "workplaceType": None, "isRemote": None, "location": "Remote - European Union",
          "descriptionPlain": None, "descriptionHtml": "<p>Hello <b>EU</b></p>",
          "address": {"postalAddress": {"addressCountry": "European Union"}}}
    respx_mock.get(URL).mock(return_value=httpx.Response(200, json={"jobs": [JOB, unlisted, eu], "apiVersion": "1"}))
    postings = await Ashby().fetch(http, "notion")
    assert [p.id for p in postings] == ["ashby:notion:0d1c-uuid", "ashby:notion:eu"]
    p = postings[0]
    assert (p.title, p.url, p.country, p.remote, p.posted_at) == (
        "Software Engineer, Infrastructure", "https://jobs.ashbyhq.com/notion/0d1c-uuid", "US", "hybrid", "2024-03-04")
    assert p.description.startswith("We can sponsor visas.")
    assert postings[1].country is None and postings[1].remote == "remote" and postings[1].description == "Hello EU"


async def test_missing_board(http, respx_mock):
    respx_mock.get(URL).mock(return_value=httpx.Response(404, text="Not Found"))
    with pytest.raises(BoardNotFound):
        await Ashby().fetch(http, "notion")
    assert (await Ashby().probe(http, "notion")).exists is False


async def test_probe_existing(http, respx_mock):
    respx_mock.get(URL).mock(return_value=httpx.Response(200, json={"jobs": []}))
    assert (await Ashby().probe(http, "notion")).exists is True
```

- [ ] **Step 2: Run the tests**

Run: `uv run pytest tests/test_ats_ashby.py -q`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement `sponsorscope/ats/ashby.py`**

```python
from __future__ import annotations

from sponsorscope.ats.base import BoardNotFound, ProbeResult, infer_remote
from sponsorscope.geo.country import country_code
from sponsorscope.http import Http
from sponsorscope.models import RawPosting
from sponsorscope.text import html_to_text

BASE = "https://api.ashbyhq.com/posting-api/job-board"
WORKPLACE = {"remote": "remote", "hybrid": "hybrid", "onsite": "onsite", "on-site": "onsite"}


class Ashby:
    """Ashby public posting API. `isRemote` is unreliable (true on hybrid jobs); prefer workplaceType."""

    name = "ashby"
    provides_name = False

    async def fetch(self, http: Http, slug: str, known_ids: frozenset[str] = frozenset()) -> list[RawPosting]:
        resp = await http.get(f"{BASE}/{slug}")
        if resp.status_code == 404:
            raise BoardNotFound(f"ashby:{slug}")
        resp.raise_for_status()
        postings = []
        for job in resp.json().get("jobs", []):
            if job.get("isListed") is False:
                continue
            address = (job.get("address") or {}).get("postalAddress") or {}
            location = job.get("location")
            workplace = (job.get("workplaceType") or "").lower().replace(" ", "")
            remote = WORKPLACE.get(workplace) or ("remote" if job.get("isRemote") else None) or infer_remote(location)
            published = job.get("publishedAt")
            postings.append(RawPosting(
                ats=self.name, slug=slug, job_id=str(job["id"]), title=(job.get("title") or "").strip(),
                url=job.get("jobUrl") or "",
                description=(job.get("descriptionPlain") or html_to_text(job.get("descriptionHtml"))).strip(),
                location_raw=location, country=country_code(address.get("addressCountry")), remote=remote,
                posted_at=published[:10] if published else None,
            ))
        return postings

    async def probe(self, http: Http, slug: str) -> ProbeResult:
        resp = await http.get(f"{BASE}/{slug}")
        if resp.status_code == 404:
            return ProbeResult(False)
        resp.raise_for_status()
        return ProbeResult(True)
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/test_ats_ashby.py -q`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add sponsorscope/ats/ashby.py tests/test_ats_ashby.py
git commit -m "feat: Ashby ATS adapter"
```

---

### Task 5: Workable adapter

**Files:**
- Create: `sponsorscope/ats/workable.py`, `tests/test_ats_workable.py`

**Interfaces:**
- Produces: `Workable` (`name="workable"`, `provides_name=True`)

- [ ] **Step 1: Write the failing tests** in `tests/test_ats_workable.py`

```python
import httpx
import pytest

from sponsorscope.ats.base import BoardNotFound
from sponsorscope.ats.workable import Workable

URL = "https://apply.workable.com/api/v1/widget/accounts/huggingface"
JOB = {
    "title": "ML Engineer", "shortcode": "81B46579FE", "code": "", "url": "https://apply.workable.com/j/81B46579FE",
    "shortlink": "https://apply.workable.com/j/81B46579FE", "country": "France", "city": "Paris", "state": "Île-de-France",
    "telecommuting": True, "published_on": "2026-10-01", "created_at": "2026-09-30",
    "description": "<p>We offer <b>visa sponsorship</b>.</p>",
    "locations": [{"country": "France", "countryCode": "FR", "city": "Paris", "region": "Île-de-France", "hidden": False}],
}


async def test_parses_jobs_with_details(http, respx_mock):
    route = respx_mock.get(URL).mock(return_value=httpx.Response(200, json={"name": "Hugging Face", "jobs": [JOB]}))
    [p] = await Workable().fetch(http, "huggingface")
    assert route.calls.last.request.url.params["details"] == "true"
    assert (p.id, p.title, p.country, p.remote, p.posted_at) == (
        "workable:huggingface:81B46579FE", "ML Engineer", "FR", "remote", "2026-10-01")
    assert p.location_raw == "Paris, Île-de-France, France"
    assert p.description == "We offer visa sponsorship."


async def test_country_falls_back_to_country_name(http, respx_mock):
    job = {**JOB, "locations": [], "telecommuting": False, "country": "Netherlands"}
    respx_mock.get(URL).mock(return_value=httpx.Response(200, json={"name": "HF", "jobs": [job]}))
    [p] = await Workable().fetch(http, "huggingface")
    assert p.country == "NL" and p.remote is None


async def test_probe_and_missing(http, respx_mock):
    respx_mock.get(URL).mock(return_value=httpx.Response(200, json={"name": "Hugging Face", "jobs": []}))
    result = await Workable().probe(http, "huggingface")
    assert result.exists and result.name == "Hugging Face" and Workable.provides_name
    respx_mock.get("https://apply.workable.com/api/v1/widget/accounts/nope").mock(return_value=httpx.Response(404))
    assert (await Workable().probe(http, "nope")).exists is False
    with pytest.raises(BoardNotFound):
        await Workable().fetch(http, "nope")
```

- [ ] **Step 2: Run the tests**

Run: `uv run pytest tests/test_ats_workable.py -q`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement `sponsorscope/ats/workable.py`**

```python
from __future__ import annotations

from sponsorscope.ats.base import BoardNotFound, ProbeResult
from sponsorscope.geo.country import country_code
from sponsorscope.http import Http
from sponsorscope.models import RawPosting
from sponsorscope.text import html_to_text

BASE = "https://apply.workable.com/api/v1/widget/accounts"


class Workable:
    """Workable widget API (undocumented, behind Cloudflare; covered by the smoke workflow)."""

    name = "workable"
    provides_name = True

    async def fetch(self, http: Http, slug: str, known_ids: frozenset[str] = frozenset()) -> list[RawPosting]:
        resp = await http.get(f"{BASE}/{slug}", params={"details": "true"})
        if resp.status_code == 404:
            raise BoardNotFound(f"workable:{slug}")
        resp.raise_for_status()
        postings = []
        for job in resp.json().get("jobs", []):
            visible = [loc for loc in job.get("locations") or [] if not loc.get("hidden")]
            first = visible[0] if visible else {}
            parts = (job.get("city") or first.get("city"), job.get("state") or first.get("region"),
                     job.get("country") or first.get("country"))
            postings.append(RawPosting(
                ats=self.name, slug=slug, job_id=str(job["shortcode"]), title=(job.get("title") or "").strip(),
                url=job.get("url") or job.get("shortlink") or "", description=html_to_text(job.get("description")),
                location_raw=", ".join(p for p in parts if p) or None,
                country=country_code(first.get("countryCode")) or country_code(job.get("country")),
                remote="remote" if job.get("telecommuting") else None,
                posted_at=job.get("published_on") or job.get("created_at") or None,
            ))
        return postings

    async def probe(self, http: Http, slug: str) -> ProbeResult:
        resp = await http.get(f"{BASE}/{slug}")
        if resp.status_code == 404:
            return ProbeResult(False)
        resp.raise_for_status()
        return ProbeResult(True, resp.json().get("name"))
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/test_ats_workable.py -q`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add sponsorscope/ats/workable.py tests/test_ats_workable.py
git commit -m "feat: Workable ATS adapter"
```

---

### Task 6: SmartRecruiters adapter

**Files:**
- Create: `sponsorscope/ats/smartrecruiters.py`, `tests/test_ats_smartrecruiters.py`

**Interfaces:**
- Produces: `SmartRecruiters` (`name="smartrecruiters"`, `provides_name=False`), with constant `PAGE_SIZE = 100`

- [ ] **Step 1: Write the failing tests** in `tests/test_ats_smartrecruiters.py`

```python
import httpx
import pytest

from sponsorscope.ats.base import BoardNotFound
from sponsorscope.ats.smartrecruiters import PAGE_SIZE, SmartRecruiters

API = "https://api.smartrecruiters.com/v1/companies/Acme/postings"


def item(pid, ref, lang="en", country="ro"):
    return {"id": pid, "name": f"Job {pid}", "refNumber": ref, "releasedDate": "2026-10-13T10:52:12.447Z",
            "language": {"code": lang}, "location": {"city": "Bucharest", "country": country, "remote": False,
                                                      "hybrid": True, "fullLocation": "Bucharest, Romania"}}


def detail(text):
    return {"jobAd": {"sections": {"companyDescription": {"title": "About", "text": "<p>Acme&#xa0;Corp</p>"},
                                   "jobDescription": {"title": "Role", "text": f"<p>{text}</p>"},
                                   "qualifications": {"title": "You", "text": ""},
                                   "additionalInformation": {"title": "More", "text": "<p>We can sponsor visas.</p>"}}}}


async def test_paginates_dedupes_languages_and_fetches_details_for_new_ids_only(http, respx_mock):
    page1 = [item(str(i), f"REF{i}") for i in range(PAGE_SIZE)]
    page2 = [item("fr-copy", "REF0", lang="fr"), item("200", "REF200", lang="en-GB")]
    def listing(request):
        offset = int(request.url.params["offset"])
        content = page1 if offset == 0 else page2
        return httpx.Response(200, json={"offset": offset, "limit": PAGE_SIZE, "totalFound": PAGE_SIZE + 2, "content": content})
    respx_mock.get(API).mock(side_effect=listing)
    detail_route = respx_mock.get(url__regex=rf"{API}/\d+$").mock(return_value=httpx.Response(200, json=detail("Build things")))
    known = frozenset(f"smartrecruiters:Acme:{i}" for i in range(1, PAGE_SIZE))  # all but id 0 already stored
    postings = await SmartRecruiters().fetch(http, "Acme", known_ids=known)
    ids = [p.job_id for p in postings]
    assert len(ids) == PAGE_SIZE + 1 and "fr-copy" not in ids and "200" in ids
    assert detail_route.call_count == 2  # ids 0 and 200 are new
    first = next(p for p in postings if p.job_id == "0")
    assert first.description.startswith("Acme Corp") and "We can sponsor visas." in first.description
    assert (first.country, first.remote, first.posted_at, first.url) == (
        "RO", "hybrid", "2026-10-13", "https://jobs.smartrecruiters.com/Acme/0")
    assert next(p for p in postings if p.job_id == "5").description is None


async def test_empty_listing_for_unknown_company_is_board_not_found(http, respx_mock):
    respx_mock.get(API).mock(return_value=httpx.Response(200, json={"offset": 0, "limit": 100, "totalFound": 0, "content": []}))
    respx_mock.get("https://careers.smartrecruiters.com/Acme").mock(return_value=httpx.Response(302, headers={"Location": "https://jobs.smartrecruiters.com/"}))
    with pytest.raises(BoardNotFound):
        await SmartRecruiters().fetch(http, "Acme")


async def test_empty_listing_for_real_company_is_empty_board(http, respx_mock):
    respx_mock.get(API).mock(return_value=httpx.Response(200, json={"offset": 0, "limit": 100, "totalFound": 0, "content": []}))
    respx_mock.get("https://careers.smartrecruiters.com/Acme").mock(return_value=httpx.Response(200, text="<html>"))
    assert await SmartRecruiters().fetch(http, "Acme") == []
    assert (await SmartRecruiters().probe(http, "Acme")).exists is True


async def test_detail_404_gives_empty_description(http, respx_mock):
    respx_mock.get(API).mock(return_value=httpx.Response(200, json={"offset": 0, "limit": 100, "totalFound": 1, "content": [item("7", "R7")]}))
    respx_mock.get(f"{API}/7").mock(return_value=httpx.Response(404, json={"code": "RESOURCE_NOT_FOUND"}))
    [p] = await SmartRecruiters().fetch(http, "Acme")
    assert p.description == ""
```

- [ ] **Step 2: Run the tests**

Run: `uv run pytest tests/test_ats_smartrecruiters.py -q`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement `sponsorscope/ats/smartrecruiters.py`**

```python
from __future__ import annotations

from sponsorscope.ats.base import BoardNotFound, ProbeResult
from sponsorscope.geo.country import country_code
from sponsorscope.http import Http
from sponsorscope.models import RawPosting
from sponsorscope.text import html_to_text

API = "https://api.smartrecruiters.com/v1/companies"
CAREERS = "https://careers.smartrecruiters.com"
JOBS = "https://jobs.smartrecruiters.com"
PAGE_SIZE = 100
SECTIONS = ("companyDescription", "jobDescription", "qualifications", "additionalInformation")


def _dedupe_languages(items: list[dict]) -> list[dict]:
    """The same job is published once per language; keep one per refNumber, English preferred."""
    chosen: dict[str, dict] = {}
    for it in items:
        key = it.get("refNumber") or it["id"]
        is_en = ((it.get("language") or {}).get("code") or "").lower().startswith("en")
        if key not in chosen or (is_en and not chosen[key]["_en"]):
            chosen[key] = {**it, "_en": is_en}
    return list(chosen.values())


class SmartRecruiters:
    """Public Posting API. Unknown companies return 200 + empty list, so existence is checked separately."""

    name = "smartrecruiters"
    provides_name = False

    async def fetch(self, http: Http, slug: str, known_ids: frozenset[str] = frozenset()) -> list[RawPosting]:
        listing = await self._list(http, slug)
        if not listing and not (await self.probe(http, slug)).exists:
            raise BoardNotFound(f"smartrecruiters:{slug}")
        postings = []
        for it in _dedupe_languages(listing):
            pid = str(it["id"])
            new = f"{self.name}:{slug}:{pid}" not in known_ids
            loc = it.get("location") or {}
            released = it.get("releasedDate")
            postings.append(RawPosting(
                ats=self.name, slug=slug, job_id=pid, title=(it.get("name") or "").strip(),
                url=f"{JOBS}/{slug}/{pid}",
                description=await self._description(http, slug, pid) if new else None,
                location_raw=loc.get("fullLocation"), country=country_code(loc.get("country")),
                remote="remote" if loc.get("remote") else "hybrid" if loc.get("hybrid") else None,
                posted_at=released[:10] if released else None,
            ))
        return postings

    async def _list(self, http: Http, slug: str) -> list[dict]:
        items: list[dict] = []
        offset = 0
        while True:
            resp = await http.get(f"{API}/{slug}/postings", params={"limit": PAGE_SIZE, "offset": offset})
            resp.raise_for_status()
            data = resp.json()
            content = data.get("content") or []
            items += content
            offset += PAGE_SIZE
            if not content or offset >= (data.get("totalFound") or 0):
                return items

    async def _description(self, http: Http, slug: str, pid: str) -> str:
        resp = await http.get(f"{API}/{slug}/postings/{pid}")
        if resp.status_code == 404:
            return ""
        resp.raise_for_status()
        sections = ((resp.json().get("jobAd") or {}).get("sections")) or {}
        texts = [html_to_text((sections.get(key) or {}).get("text")) for key in SECTIONS]
        return "\n".join(t for t in texts if t)

    async def probe(self, http: Http, slug: str) -> ProbeResult:
        resp = await http.get(f"{CAREERS}/{slug}", follow_redirects=False)
        if resp.status_code == 200:
            return ProbeResult(True)
        if resp.is_redirect or resp.status_code == 404:
            return ProbeResult(False)
        resp.raise_for_status()
        return ProbeResult(False)
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/test_ats_smartrecruiters.py -q`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add sponsorscope/ats/smartrecruiters.py tests/test_ats_smartrecruiters.py
git commit -m "feat: SmartRecruiters adapter with pagination, language dedupe and new-id-only detail calls"
```

---

### Task 7: Recruitee adapter

**Files:**
- Create: `sponsorscope/ats/recruitee.py`, `tests/test_ats_recruitee.py`

**Interfaces:**
- Produces: `Recruitee` (`name="recruitee"`, `provides_name=False`)

- [ ] **Step 1: Write the failing tests** in `tests/test_ats_recruitee.py`

```python
import httpx
import pytest

from sponsorscope.ats.base import BoardNotFound
from sponsorscope.ats.recruitee import Recruitee

URL = "https://bunq.recruitee.com/api/offers/"
OFFER = {"id": 2781634, "title": "Senior Product Owner", "status": "published",
         "careers_url": "https://careers.bunq.com/o/senior-product-owner-1",
         "description": "<p>Join bunq.</p>", "requirements": "<ul><li>Fluent English</li></ul>",
         "location": "Amsterdam, Noord-Holland, Netherlands", "country_code": "NL",
         "remote": True, "hybrid": True, "on_site": False, "published_at": "2026-10-13 10:58:56 UTC"}


async def test_parses_offers(http, respx_mock):
    draft = {**OFFER, "id": 1, "status": "draft"}
    respx_mock.get(URL).mock(return_value=httpx.Response(200, json={"offers": [OFFER, draft]}))
    [p] = await Recruitee().fetch(http, "bunq")
    assert (p.id, p.url, p.country, p.remote, p.posted_at) == (
        "recruitee:bunq:2781634", "https://careers.bunq.com/o/senior-product-owner-1", "NL", "hybrid", "2026-10-13")
    assert p.description == "Join bunq.\nFluent English"


async def test_missing_and_unsafe_slugs(http, respx_mock):
    respx_mock.get("https://nope.recruitee.com/api/offers/").mock(return_value=httpx.Response(404, json={"error": "Not Found"}))
    with pytest.raises(BoardNotFound):
        await Recruitee().fetch(http, "nope")
    assert (await Recruitee().probe(http, "nope")).exists is False
    assert (await Recruitee().probe(http, "evil.example.com/x")).exists is False  # never builds a hostile host
    with pytest.raises(BoardNotFound):
        await Recruitee().fetch(http, "Bad_Slug")


async def test_probe_existing(http, respx_mock):
    respx_mock.get(URL).mock(return_value=httpx.Response(200, json={"offers": []}))
    assert (await Recruitee().probe(http, "bunq")).exists is True
```

- [ ] **Step 2: Run the tests**

Run: `uv run pytest tests/test_ats_recruitee.py -q`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement `sponsorscope/ats/recruitee.py`**

```python
from __future__ import annotations

from sponsorscope.ats.base import SUBDOMAIN_SLUG, BoardNotFound, ProbeResult
from sponsorscope.geo.country import country_code
from sponsorscope.http import Http
from sponsorscope.models import RawPosting
from sponsorscope.text import html_to_text


def _url(slug: str) -> str:
    return f"https://{slug}.recruitee.com/api/offers/"


class Recruitee:
    """Recruitee careers-site API. NOTE: requires X-Careers-Sites-Token from 2027-02-10 (spec §8)."""

    name = "recruitee"
    provides_name = False

    async def fetch(self, http: Http, slug: str, known_ids: frozenset[str] = frozenset()) -> list[RawPosting]:
        if not SUBDOMAIN_SLUG.fullmatch(slug):
            raise BoardNotFound(f"recruitee:{slug} (not a valid subdomain)")
        resp = await http.get(_url(slug))
        if resp.status_code == 404:
            raise BoardNotFound(f"recruitee:{slug}")
        resp.raise_for_status()
        postings = []
        for o in resp.json().get("offers", []):
            if o.get("status") not in (None, "published"):
                continue
            remote = "hybrid" if o.get("hybrid") else "remote" if o.get("remote") else "onsite" if o.get("on_site") else None
            published = o.get("published_at") or o.get("created_at")
            text = [html_to_text(o.get("description")), html_to_text(o.get("requirements"))]
            postings.append(RawPosting(
                ats=self.name, slug=slug, job_id=str(o["id"]), title=(o.get("title") or "").strip(),
                url=o.get("careers_url") or "", description="\n".join(t for t in text if t),
                location_raw=o.get("location"), country=country_code(o.get("country_code")), remote=remote,
                posted_at=published[:10] if published else None,
            ))
        return postings

    async def probe(self, http: Http, slug: str) -> ProbeResult:
        if not SUBDOMAIN_SLUG.fullmatch(slug):
            return ProbeResult(False)
        resp = await http.get(_url(slug))
        if resp.status_code == 404:
            return ProbeResult(False)
        resp.raise_for_status()
        return ProbeResult(True)
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/test_ats_recruitee.py -q`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add sponsorscope/ats/recruitee.py tests/test_ats_recruitee.py
git commit -m "feat: Recruitee ATS adapter"
```

---

### Task 8: Personio adapter (safe XML)

**Files:**
- Modify: `pyproject.toml` (add the `defusedxml>=0.7` dependency)
- Create: `sponsorscope/ats/personio.py`, `tests/test_ats_personio.py`

**Interfaces:**
- Produces: `Personio` (`name="personio"`, `provides_name=False`)

- [ ] **Step 1: Add the dependency**

Run: `uv add 'defusedxml>=0.7'`
Expected: `pyproject.toml` and `uv.lock` are updated.

- [ ] **Step 2: Write the failing tests** in `tests/test_ats_personio.py`

```python
import httpx
import pytest

from sponsorscope.ats.base import BoardNotFound
from sponsorscope.ats.personio import Personio

URL = "https://tado.jobs.personio.de/xml"
XML = """<?xml version="1.0" encoding="UTF-8"?>
<workzag-jobs>
  <position>
    <id>1234</id><name> Backend Engineer </name><office>Germany - Munich</office>
    <additionalOffices><office>Remote</office></additionalOffices>
    <jobDescriptions>
      <jobDescription><name>Your role</name><value><![CDATA[<p>Build <b>APIs</b>.</p>]]></value></jobDescription>
      <jobDescription><name>Perks</name><value><![CDATA[<p>We offer visa sponsorship.</p>]]></value></jobDescription>
    </jobDescriptions>
    <createdAt>2026-10-13T09:59:49+00:00</createdAt>
  </position>
  <position><id>99</id><name>Empty</name><office>Berlin</office><jobDescriptions/></position>
</workzag-jobs>"""
BOMB = """<?xml version="1.0"?><!DOCTYPE lolz [<!ENTITY lol "lol"><!ENTITY lol2 "&lol;&lol;&lol;">]>
<workzag-jobs><position><id>1</id><name>&lol2;</name></position></workzag-jobs>"""


async def test_parses_positions(http, respx_mock):
    respx_mock.get(URL).mock(return_value=httpx.Response(200, text=XML, headers={"Content-Type": "text/xml"}))
    first, second = await Personio().fetch(http, "tado")
    assert (first.id, first.title, first.url, first.posted_at) == (
        "personio:tado:1234", "Backend Engineer", "https://tado.jobs.personio.de/job/1234", "2026-10-13")
    assert first.location_raw == "Germany - Munich; Remote" and first.remote == "remote" and first.country is None
    assert first.description == "Your role\nBuild APIs.\nPerks\nWe offer visa sponsorship."
    assert second.description == "" and second.posted_at is None


async def test_html_404_and_non_xml_200_are_not_boards(http, respx_mock):
    respx_mock.get("https://nope.jobs.personio.de/xml").mock(return_value=httpx.Response(404, text="<html>Page Not Found</html>"))
    respx_mock.get("https://html.jobs.personio.de/xml").mock(
        return_value=httpx.Response(200, text="<html></html>", headers={"Content-Type": "text/html"}))
    with pytest.raises(BoardNotFound):
        await Personio().fetch(http, "nope")
    assert (await Personio().probe(http, "nope")).exists is False
    assert (await Personio().probe(http, "html")).exists is False
    with pytest.raises(BoardNotFound):
        await Personio().fetch(http, "html")


async def test_entity_expansion_is_rejected(http, respx_mock):
    respx_mock.get(URL).mock(return_value=httpx.Response(200, text=BOMB, headers={"Content-Type": "text/xml"}))
    with pytest.raises(Exception, match="(?i)entit"):
        await Personio().fetch(http, "tado")
```

- [ ] **Step 3: Run the tests**

Run: `uv run pytest tests/test_ats_personio.py -q`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 4: Implement `sponsorscope/ats/personio.py`**

```python
from __future__ import annotations

from defusedxml.ElementTree import fromstring

from sponsorscope.ats.base import SUBDOMAIN_SLUG, BoardNotFound, ProbeResult, infer_remote
from sponsorscope.http import Http
from sponsorscope.models import RawPosting
from sponsorscope.text import html_to_text


def _base(slug: str) -> str:
    return f"https://{slug}.jobs.personio.de"


def _text(node, path: str) -> str:
    found = node.find(path)
    return (found.text or "").strip() if found is not None else ""


def _is_xml(resp) -> bool:
    return "xml" in resp.headers.get("content-type", "").lower()


class Personio:
    """Personio public XML feed. Unknown slugs return an HTML 404 page; XML is parsed with defusedxml."""

    name = "personio"
    provides_name = False

    async def fetch(self, http: Http, slug: str, known_ids: frozenset[str] = frozenset()) -> list[RawPosting]:
        if not SUBDOMAIN_SLUG.fullmatch(slug):
            raise BoardNotFound(f"personio:{slug} (not a valid subdomain)")
        resp = await http.get(f"{_base(slug)}/xml")
        if resp.status_code == 404:
            raise BoardNotFound(f"personio:{slug}")
        resp.raise_for_status()
        if not _is_xml(resp):
            raise BoardNotFound(f"personio:{slug} (not an XML feed)")
        postings = []
        for pos in fromstring(resp.content).findall("position"):
            pid = _text(pos, "id")
            offices = [_text(pos, "office")] + [(o.text or "").strip() for o in pos.findall("additionalOffices/office")]
            location = "; ".join(o for o in offices if o) or None
            sections = []
            for d in pos.findall("jobDescriptions/jobDescription"):
                body = "\n".join(t for t in (_text(d, "name"), html_to_text(_text(d, "value"))) if t)
                if body:
                    sections.append(body)
            created = _text(pos, "createdAt")
            postings.append(RawPosting(
                ats=self.name, slug=slug, job_id=pid, title=_text(pos, "name"), url=f"{_base(slug)}/job/{pid}",
                description="\n".join(sections), location_raw=location, country=None,
                remote=infer_remote(location), posted_at=created[:10] or None,
            ))
        return postings

    async def probe(self, http: Http, slug: str) -> ProbeResult:
        if not SUBDOMAIN_SLUG.fullmatch(slug):
            return ProbeResult(False)
        resp = await http.get(f"{_base(slug)}/xml")
        if resp.status_code == 404:
            return ProbeResult(False)
        resp.raise_for_status()
        return ProbeResult(_is_xml(resp))
```

- [ ] **Step 5: Run the tests**

Run: `uv run pytest tests/test_ats_personio.py -q`
Expected: 3 passed

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml uv.lock sponsorscope/ats/personio.py tests/test_ats_personio.py
git commit -m "feat: Personio adapter with defusedxml parsing"
```

---

### Task 9: Pipeline: `known_ids`, `description=None`, all adapters in the CLI

**Files:**
- Modify: `sponsorscope/store/db.py`, `sponsorscope/pipeline.py`, `sponsorscope/cli.py`
- Test: `tests/test_pipeline.py`

**Interfaces:**
- Produces:
  - `db.active_posting_ids(conn, ats, slug) -> frozenset[str]`
  - `db.touch_posting(conn, p, *, company_id, country, now) -> None`, which updates metadata and `last_seen`, sets `active=1`, and keeps `content_hash` and `lang`
  - `cli._adapters()` returns all seven adapters

- [ ] **Step 1: Write the failing test.** Append to `tests/test_pipeline.py`:

```python
from sponsorscope.models import RawPosting
from sponsorscope.report import RunReport


class DetailOnceATS:
    """Mimics SmartRecruiters: description only for ids not in known_ids."""

    name = "fakeats"
    provides_name = False

    def __init__(self):
        self.seen_known = []

    async def fetch(self, http, slug, known_ids=frozenset()):
        self.seen_known.append(known_ids)
        pid = f"fakeats:{slug}:1"
        return [RawPosting(ats="fakeats", slug=slug, job_id="1", title="Backend Engineer", url="https://x/1",
                           description=None if pid in known_ids else "We offer visa sponsorship for this role." + LONG,
                           location_raw="London, UK", country=None, remote=None, posted_at="2026-10-01")]

    async def probe(self, http, slug):
        raise NotImplementedError


async def test_known_posting_without_description_keeps_label(conn, http):
    cid = db.get_or_create_company(conn, "Acme Widgets")
    db.upsert_board(conn, "fakeats", "acme", cid, status="hit", origin="seed", now=T[0])
    ats = DetailOnceATS()
    for now in T[:2]:
        await pipeline.run_crawl(conn, http, {"fakeats": ats}, RulesClassifier(), RunReport(started_at=now), now, CITIES)
    assert ats.seen_known == [frozenset(), frozenset({"fakeats:acme:1"})]
    row = conn.execute("SELECT active, last_seen, lang, content_hash FROM postings").fetchone()
    assert (row["active"], row["last_seen"], row["lang"]) == (1, T[1], "en") and row["content_hash"]
    assert conn.execute("SELECT sponsorship FROM labels").fetchone()[0] == "yes"
```

- [ ] **Step 2: Run the test**

Run: `uv run pytest tests/test_pipeline.py -q -k known_posting`
Expected: FAIL. The `seen_known` assertion gets `[frozenset(), frozenset()]`.

- [ ] **Step 3: Implement.**

Append to `sponsorscope/store/db.py`:

```python
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
```

In `sponsorscope/pipeline.py`, insert this at the top of `_process_posting`, before `text = ...`:

```python
    if p.description is None:  # adapter skipped the detail call for a known posting
        db.touch_posting(conn, p, company_id=company_id,
                         country=resolve_country(p.location_raw, p.country, cities), now=now)
        return
```

In `run_crawl`, replace the `fetch` closure with:

```python
        async def fetch(board: sqlite3.Row, adapter: ATS = adapter):
            try:
                known = db.active_posting_ids(conn, ats_name, board["slug"])
                return board, "ok", await adapter.fetch(http, board["slug"], known_ids=known)
            except BoardNotFound:
                return board, "not_found", None
            except Exception as exc:
                return board, "failed", exc
```

In `sponsorscope/cli.py`, add the imports and replace `_adapters`:

```python
from sponsorscope.ats.ashby import Ashby
from sponsorscope.ats.personio import Personio
from sponsorscope.ats.recruitee import Recruitee
from sponsorscope.ats.smartrecruiters import SmartRecruiters
from sponsorscope.ats.workable import Workable


def _adapters():
    adapters = [Greenhouse(), Lever(), Ashby(), Workable(), SmartRecruiters(), Recruitee(), Personio()]
    return {a.name: a for a in adapters}
```

- [ ] **Step 4: Run all the tests**

Run: `uv run pytest -q`
Expected: all passed

- [ ] **Step 5: Commit**

```bash
git add sponsorscope/store/db.py sponsorscope/pipeline.py sponsorscope/cli.py tests/test_pipeline.py
git commit -m "feat: crawl all seven ATSes; skip detail calls for known SmartRecruiters postings"
```

---

### Task 10: Store support for discovery

**Files:**
- Modify: `sponsorscope/store/db.py`
- Test: `tests/test_store.py`

**Interfaces:**
- Produces:
  - Table `discovery_progress(sponsor_norm PK, attempts, next_try_at)`
  - Constant `BACKOFF_DAYS = (7, 28, 84)`
  - `backoff_until(now: str, attempts: int) -> str`
  - `add_seed_board(conn, ats, slug, company_id: int | None, now) -> bool`, true if inserted
  - `board_exists(conn, ats, slug) -> bool`
  - `board_company(conn, ats, slug) -> int | None`
  - `due_boards(conn, now, limit) -> list[Row]` with columns `ats, slug, company_id, status`
  - `record_probe(conn, ats, slug, *, exists: bool, company_id: int | None, now) -> None`
  - `sponsors_to_guess(conn, now, limit) -> list[Row]` with column `norm_name`
  - `record_guess_attempt(conn, norm, *, found: bool, now) -> None`

- [ ] **Step 1: Write the failing tests.** Append to `tests/test_store.py`:

```python
def test_backoff_schedule():
    assert db.backoff_until(T1, 1) == "2026-10-20T03:00:00+00:00"
    assert db.backoff_until(T1, 2) == "2026-11-10T03:00:00+00:00"
    assert db.backoff_until(T1, 3) == db.backoff_until(T1, 9) == "2027-01-05T03:00:00+00:00"


def test_seed_boards_are_pending_until_probed(conn):
    assert db.add_seed_board(conn, "ashby", "notion", None, T1) is True
    assert db.add_seed_board(conn, "ashby", "notion", None, T1) is False
    assert [r["slug"] for r in db.due_boards(conn, T1, 10)] == ["notion"]
    assert db.boards_to_crawl(conn) == []
    cid = db.get_or_create_company(conn, "Notion")
    db.record_probe(conn, "ashby", "notion", exists=True, company_id=cid, now=T1)
    assert [tuple(r) for r in db.boards_to_crawl(conn)] == [("ashby", "notion", cid)]
    assert db.board_company(conn, "ashby", "notion") == cid and db.due_boards(conn, T2, 10) == []


def test_probe_miss_backs_off(conn):
    db.add_seed_board(conn, "lever", "ghost", None, T1)
    db.record_probe(conn, "lever", "ghost", exists=False, company_id=None, now=T1)
    assert db.due_boards(conn, T2, 10) == []  # next probe in 7 days
    assert len(db.due_boards(conn, "2026-10-21T00:00:00+00:00", 10)) == 1
    db.record_probe(conn, "lever", "ghost", exists=False, company_id=None, now="2026-10-21T00:00:00+00:00")
    row = conn.execute("SELECT status, consecutive_failures, next_probe_at FROM boards").fetchone()
    assert tuple(row) == ("miss", 2, "2026-11-18T00:00:00+00:00")


def test_gone_boards_are_due_for_reprobe(conn):
    cid = db.get_or_create_company(conn, "Acme")
    db.upsert_board(conn, "greenhouse", "acme", cid, status="hit", origin="seed", now=T1)
    for _ in range(db.GONE_AFTER):
        db.record_board_result(conn, "greenhouse", "acme", "not_found")
    assert [r["status"] for r in db.due_boards(conn, T1, 10)] == ["gone"]


def test_sponsors_to_guess_priority_and_exclusions(conn):
    db.upsert_sponsors(conn, "gb", [rec("Uk Only Widgets Ltd"), rec("Matched Co Ltd")], "v1", T1)
    db.upsert_sponsors(conn, "us", [SponsorRecord("US", "us", "history", "Big Filer Inc", filings=500),
                                    SponsorRecord("US", "us", "history", "Small Filer Inc", filings=3)], "v1", T1)
    matched = conn.execute("SELECT id FROM sponsors WHERE norm_name = 'matched'").fetchone()[0]
    db.replace_matches(conn, [(matched, db.get_or_create_company(conn, "Matched"), "exact", 100.0)])
    assert [r["norm_name"] for r in db.sponsors_to_guess(conn, T1, 10)] == ["big filer", "small filer", "uk only widgets"]
    db.record_guess_attempt(conn, "big filer", found=False, now=T1)
    assert [r["norm_name"] for r in db.sponsors_to_guess(conn, T2, 10)] == ["small filer", "uk only widgets"]
    assert [r["norm_name"] for r in db.sponsors_to_guess(conn, T2, 1)] == ["small filer"]
```

- [ ] **Step 2: Run the tests**

Run: `uv run pytest tests/test_store.py -q`
Expected: FAIL with `AttributeError: module 'sponsorscope.store.db' has no attribute 'backoff_until'`

- [ ] **Step 3: Implement.**

In `sponsorscope/store/db.py`:
- add `from datetime import datetime, timedelta` to the imports
- append this table to `SCHEMA`, before the closing `"""`:

```sql
CREATE TABLE IF NOT EXISTS discovery_progress (
  sponsor_norm TEXT PRIMARY KEY, attempts INTEGER NOT NULL DEFAULT 0, next_try_at TEXT
);
```

Then append these functions:

```python
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
        SELECT ats, slug, company_id, status FROM boards
        WHERE status IN ('pending', 'miss', 'gone') AND (next_probe_at IS NULL OR next_probe_at <= ?)
        ORDER BY CASE status WHEN 'pending' THEN 0 WHEN 'gone' THEN 1 ELSE 2 END, next_probe_at, ats, slug
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
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/test_store.py -q`
Expected: all passed (15)

- [ ] **Step 5: Commit**

```bash
git add sponsorscope/store/db.py tests/test_store.py
git commit -m "feat: store support for discovery (pending boards, probe backoff, guess progress)"
```

---

### Task 11: Discovery seeds

**Files:**
- Create: `sponsorscope/discovery/__init__.py` (empty), `sponsorscope/discovery/seeds.py`, `tests/test_discovery_seeds.py`

**Interfaces:**
- Produces:
  - `Seed(ats: str, slug: str, name: str | None)`, frozen
  - `parse_feashliaa(ats, data) -> list[Seed]`
  - `parse_conors(data, supported: set[str]) -> list[Seed]`
  - `load_manual(path: Path) -> list[Seed]`
  - `async fetch_remote_seeds(http, supported: set[str]) -> tuple[list[Seed], list[str]]`, returning the seeds plus error strings
  - Constants `FEASHLIAA_URL` (with an `{ats}` placeholder), `FEASHLIAA_ATS = ("greenhouse", "lever", "ashby")`, `CONORS_URL`

- [ ] **Step 1: Write the failing tests** in `tests/test_discovery_seeds.py`

```python
import httpx

from sponsorscope.discovery.seeds import (
    CONORS_URL, FEASHLIAA_URL, Seed, fetch_remote_seeds, load_manual, parse_conors, parse_feashliaa,
)


def test_parse_feashliaa_flat_slug_list():
    assert parse_feashliaa("lever", ["15five", " 10up-2 ", "", 7, None]) == [
        Seed("lever", "15five", None), Seed("lever", "10up-2", None)]


def test_parse_conors_filters_platforms_and_shapes():
    data = [{"name": "Stripe", "platform": "greenhouse", "slug": "stripe"},
            {"name": "Acme", "platform": "workday", "workday": {"tenant": "acme"}},
            {"name": "bunq", "platform": "recruitee", "slug": "bunq"},
            {"platform": "lever"}]
    assert parse_conors(data, {"greenhouse", "recruitee"}) == [
        Seed("greenhouse", "stripe", "Stripe"), Seed("recruitee", "bunq", "bunq")]


def test_load_manual(tmp_path):
    path = tmp_path / "m.yaml"
    path.write_text("- {ats: lever, slug: palantir, name: Palantir}\n")
    assert load_manual(path) == [Seed("lever", "palantir", "Palantir")]
    assert load_manual(tmp_path / "missing.yaml") == []


async def test_fetch_remote_seeds_tolerates_one_failing_source(http, respx_mock):
    respx_mock.get(FEASHLIAA_URL.format(ats="greenhouse")).mock(return_value=httpx.Response(200, json=["airbnb"]))
    respx_mock.get(FEASHLIAA_URL.format(ats="lever")).mock(return_value=httpx.Response(500))
    respx_mock.get(FEASHLIAA_URL.format(ats="ashby")).mock(return_value=httpx.Response(200, json=["notion"]))
    respx_mock.get(CONORS_URL).mock(return_value=httpx.Response(200, json=[{"name": "bunq", "platform": "recruitee", "slug": "bunq"}]))
    seeds, errors = await fetch_remote_seeds(http, {"greenhouse", "lever", "ashby", "recruitee"})
    assert set(seeds) == {Seed("greenhouse", "airbnb", None), Seed("ashby", "notion", None), Seed("recruitee", "bunq", "bunq")}
    assert len(errors) == 1 and "lever" in errors[0]
```

- [ ] **Step 2: Run the tests**

Run: `uv run pytest tests/test_discovery_seeds.py -q`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement `sponsorscope/discovery/seeds.py`**

```python
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
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/test_discovery_seeds.py -q`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add sponsorscope/discovery tests/test_discovery_seeds.py
git commit -m "feat: discovery seed loaders for public ATS slug lists"
```

---

### Task 12: Slug guessing and the discovery run

**Files:**
- Create: `sponsorscope/discovery/slugs.py`, `sponsorscope/discovery/probe.py`, `tests/test_discovery.py`

**Interfaces:**
- Consumes: the Task 10 store functions, `Seed` (Task 11), `ProbeResult` (Task 3), `normalize` and `SHORT_NAME_MAX` (Plan 1)
- Produces:
  - `candidates(norm: str, *, verifiable: bool) -> list[str]`
  - Constant `MIN_UNVERIFIED_SLUG = 8`
  - `async run_discovery(conn, http, adapters, *, seeds, now, budget) -> dict[str, int]`. It returns counters: `seeds_added, boards_found, boards_missed, guesses_probed, guesses_found, guesses_rejected, probe_errors, probes`.

- [ ] **Step 1: Write the failing tests** in `tests/test_discovery.py`

```python
import pytest

from sponsorscope.ats.base import ProbeResult
from sponsorscope.discovery.probe import run_discovery
from sponsorscope.discovery.seeds import Seed
from sponsorscope.discovery.slugs import candidates
from sponsorscope.models import SponsorRecord
from sponsorscope.store import db

T1, T2 = "2026-10-13T03:00:00+00:00", "2026-10-21T03:00:00+00:00"


class FakeATS:
    def __init__(self, name, provides_name, boards, errors=()):
        self.name, self.provides_name, self.boards, self.errors = name, provides_name, boards, set(errors)
        self.probed = []

    async def probe(self, http, slug):
        self.probed.append(slug)
        if slug in self.errors:
            raise RuntimeError("HTTP 502")
        return ProbeResult(slug in self.boards, self.boards.get(slug))


@pytest.fixture
def conn(tmp_path):
    c = db.connect(tmp_path / "t.db")
    yield c
    c.close()


def sponsors(conn, *names, source="gb"):
    db.upsert_sponsors(conn, source, [SponsorRecord("GB", source, "licence", n) for n in names], "v1", T1)


def boards(conn):
    return {(r["ats"], r["slug"]): (r["status"], r["origin"]) for r in conn.execute("SELECT * FROM boards")}


def test_candidates():
    assert candidates("monzo bank", verifiable=True) == ["monzobank", "monzo-bank", "monzo"]
    assert candidates("monzo bank", verifiable=False) == ["monzobank", "monzo-bank"]
    assert candidates("acme data", verifiable=False) == ["acmedata", "acme-data"]  # compact length 8 → allowed
    assert candidates("acme dat", verifiable=False) == []  # compact length 7 → too collision-prone without a name check
    assert candidates("northwind trading", verifiable=False) == ["northwindtrading", "northwind-trading"]
    assert candidates("ibm", verifiable=True) == []  # short-name guard
    assert candidates("deliveroo", verifiable=True) == ["deliveroo"]
    assert candidates("", verifiable=True) == []


async def test_seeds_are_probed_and_named(conn):
    gh = FakeATS("greenhouse", True, {"airbnb": "Airbnb"})
    lever = FakeATS("lever", False, {"15five": None})
    seeds = [Seed("greenhouse", "airbnb", None), Seed("greenhouse", "deadco", None),
             Seed("lever", "15five", None), Seed("workday", "x", None)]
    summary = await run_discovery(conn, None, {"greenhouse": gh, "lever": lever}, seeds=seeds, now=T1, budget=100)
    assert summary["seeds_added"] == 3 and summary["boards_found"] == 2 and summary["boards_missed"] == 1
    assert boards(conn) == {("greenhouse", "airbnb"): ("hit", "seed"), ("greenhouse", "deadco"): ("miss", "seed"),
                            ("lever", "15five"): ("hit", "seed")}
    names = {r["slug"]: r["display_name"] for r in conn.execute(
        "SELECT b.slug, c.display_name FROM boards b JOIN companies c ON c.id = b.company_id")}
    assert names == {"airbnb": "Airbnb", "15five": "15Five"}


async def test_verified_guess_creates_board_and_wrong_name_is_rejected(conn):
    sponsors(conn, "Monzo Bank Ltd", "Atlas Care Homes Ltd")
    gh = FakeATS("greenhouse", True, {"monzo": "Monzo Bank", "atlas": "Atlas"})
    summary = await run_discovery(conn, None, {"greenhouse": gh}, seeds=[], now=T1, budget=100)
    assert summary["guesses_found"] == 1 and summary["guesses_rejected"] == 1
    assert boards(conn) == {("greenhouse", "monzo"): ("hit", "guess")}
    company = conn.execute("SELECT display_name, norm_name FROM companies").fetchone()
    assert tuple(company) == ("Monzo Bank", "monzo bank")  # will exact-match the sponsor
    progress = {r[0]: r[1] for r in conn.execute("SELECT sponsor_norm, attempts FROM discovery_progress")}
    assert progress == {"monzo bank": 1, "atlas care homes": 1}


async def test_unverifiable_ats_only_gets_long_full_name_guesses(conn):
    sponsors(conn, "Northwind Trading Ltd", "Zeta Ltd")
    lever = FakeATS("lever", False, {"northwindtrading": None, "zeta": None})
    await run_discovery(conn, None, {"lever": lever}, seeds=[], now=T1, budget=100)
    assert "zeta" not in lever.probed and boards(conn) == {("lever", "northwindtrading"): ("hit", "guess")}
    assert conn.execute("SELECT display_name FROM companies").fetchone()[0] == "Northwind Trading"


async def test_budget_caps_probes_and_matched_sponsors_are_skipped(conn):
    sponsors(conn, "Alpha Widgets Ltd", "Bravo Widgets Ltd", "Charlie Widgets Ltd")
    sid = conn.execute("SELECT id FROM sponsors WHERE norm_name = 'alpha widgets'").fetchone()[0]
    db.replace_matches(conn, [(sid, db.get_or_create_company(conn, "Alpha Widgets"), "exact", 100.0)])
    gh = FakeATS("greenhouse", True, {})
    summary = await run_discovery(conn, None, {"greenhouse": gh}, seeds=[], now=T1, budget=3)
    assert summary["probes"] <= 3 and len(gh.probed) == 3
    assert not any(s.startswith("alpha") for s in gh.probed)


async def test_probe_errors_do_not_back_off_or_mark_miss(conn):
    sponsors(conn, "Monzo Bank Ltd")
    gh = FakeATS("greenhouse", True, {}, errors={"monzobank", "monzo-bank", "monzo", "flaky"})
    summary = await run_discovery(conn, None, {"greenhouse": gh}, seeds=[Seed("greenhouse", "flaky", None)], now=T1, budget=100)
    assert summary["probe_errors"] == 4
    assert boards(conn) == {("greenhouse", "flaky"): ("pending", "seed")}
    assert conn.execute("SELECT COUNT(*) FROM discovery_progress").fetchone()[0] == 0


async def test_missed_sponsor_waits_for_backoff(conn):
    sponsors(conn, "Monzo Bank Ltd")
    gh = FakeATS("greenhouse", True, {})
    await run_discovery(conn, None, {"greenhouse": gh}, seeds=[], now=T1, budget=100)
    gh.probed.clear()
    await run_discovery(conn, None, {"greenhouse": gh}, seeds=[], now="2026-10-15T03:00:00+00:00", budget=100)
    assert gh.probed == []
    await run_discovery(conn, None, {"greenhouse": gh}, seeds=[], now=T2, budget=100)
    assert gh.probed == ["monzobank", "monzo-bank", "monzo"]
```

- [ ] **Step 2: Run the tests**

Run: `uv run pytest tests/test_discovery.py -q`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement `sponsorscope/discovery/slugs.py`**

```python
from __future__ import annotations

from sponsorscope.matching.names import SHORT_NAME_MAX

MIN_UNVERIFIED_SLUG = 8  # without a company name to check, only long full-name slugs are distinctive


def candidates(norm: str, *, verifiable: bool) -> list[str]:
    """Slugs to probe for a normalised sponsor name (tokens are already [a-z0-9])."""
    tokens = norm.split()
    joined = "".join(tokens)
    if len(joined) <= SHORT_NAME_MAX:
        return []
    out = [joined, "-".join(tokens)]
    if verifiable:
        if len(tokens) > 1 and len(tokens[0]) > SHORT_NAME_MAX:
            out.append(tokens[0])
    elif len(joined) < MIN_UNVERIFIED_SLUG:
        return []
    return list(dict.fromkeys(out))
```

- [ ] **Step 4: Implement `sponsorscope/discovery/probe.py`**

```python
from __future__ import annotations

import asyncio
import re
import sqlite3
from collections import Counter
from collections.abc import Iterable, Mapping

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
                        seeds: Iterable[Seed], now: str, budget: int) -> dict[str, int]:
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
            company_id = db.get_or_create_company(conn, result.name or _slug_display(slug))
        db.record_probe(conn, ats, slug, exists=result.exists, company_id=company_id, now=now)
        summary["boards_found" if result.exists else "boards_missed"] += 1
    conn.commit()

    # 2. guesses from unmatched sponsor names, within the remaining budget
    remaining = budget - len(results)
    planned: list[tuple[str, list[tuple[str, str]]]] = []
    for row in db.sponsors_to_guess(conn, now, limit=max(remaining, 0)):
        norm = row["norm_name"]
        targets = [(ats, slug) for ats, adapter in adapters.items()
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
    for norm, targets in planned:
        found = errored = False
        for ats, slug in targets:
            result: ProbeResult | Exception = results[(ats, slug)]
            if isinstance(result, Exception):
                summary["probe_errors"] += 1
                errored = True
                continue
            summary["guesses_probed"] += 1
            if not result.exists:
                continue
            adapter = adapters[ats]
            if adapter.provides_name and (result.name is None or normalize(result.name) != norm):
                summary["guesses_rejected"] += 1  # e.g. board "atlas" named "Atlas" ≠ "Atlas Care Homes"
                continue
            company_id = db.get_or_create_company(conn, result.name if adapter.provides_name else norm.title())
            db.upsert_board(conn, ats, slug, company_id, status="hit", origin="guess", now=now)
            summary["guesses_found"] += 1
            found = True
        if found or not errored:
            db.record_guess_attempt(conn, norm, found=found, now=now)
    conn.commit()
    return dict(summary)
```

- [ ] **Step 5: Run the tests**

Run: `uv run pytest tests/test_discovery.py -q`
Expected: 7 passed

- [ ] **Step 6: Commit**

```bash
git add sponsorscope/discovery tests/test_discovery.py
git commit -m "feat: weekly discovery with seed probing, verified slug guesses, budget and backoff"
```

---

### Task 13: CLI `discover` and `smoke`, weekly and smoke workflows, README

**Files:**
- Modify: `sponsorscope/cli.py`, `README.md`
- Create: `.github/workflows/weekly-discover.yml`, `.github/workflows/smoke.yml`
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: `run_discovery`, `fetch_remote_seeds`, `load_manual`, `pipeline.run_registers` and `run_match`, `RegisterBlocked` (Plan 2)
- Produces:
  - CLI `discover --db --seeds --overrides --budget --remote-seeds/--no-remote-seeds`
  - CLI `smoke`
  - Constant `SMOKE_BOARDS`

- [ ] **Step 1: Write the failing test.** Append to `tests/test_cli.py`:

```python
from sponsorscope import cli


def test_smoke_boards_cover_every_adapter():
    assert set(cli.SMOKE_BOARDS) == set(cli._adapters())


def test_discover_without_remote_seeds_on_empty_db(tmp_path, monkeypatch):
    async def no_registers(conn, http, registers, report, now):
        return None

    monkeypatch.setattr(cli.pipeline, "run_registers", no_registers)
    seeds = tmp_path / "s.yaml"
    seeds.write_text("")
    result = runner.invoke(app, ["discover", "--db", str(tmp_path / "x.db"), "--seeds", str(seeds),
                                 "--no-remote-seeds", "--budget", "10"])
    assert result.exit_code == 0, result.output
    assert "discovery:" in result.output
```

- [ ] **Step 2: Run the tests**

Run: `uv run pytest tests/test_cli.py -q`
Expected: FAIL with `AttributeError: module 'sponsorscope.cli' has no attribute 'SMOKE_BOARDS'`

- [ ] **Step 3: Implement.** In `sponsorscope/cli.py`, add these imports:

```python
from sponsorscope.discovery.probe import run_discovery
from sponsorscope.discovery.seeds import fetch_remote_seeds, load_manual
from sponsorscope.registers.base import RegisterBlocked
```

Then add:

```python
SMOKE_BOARDS = {"greenhouse": "airbnb", "lever": "palantir", "ashby": "notion", "workable": "huggingface",
                "smartrecruiters": "Ubisoft2", "recruitee": "bunq", "personio": "tado"}


@app.command()
def discover(db: Db = Path("sponsorscope.db"), seeds: Seeds = Path("seeds/manual.yaml"),
             overrides: OverridesPath = Path("overrides.yaml"),
             budget: Annotated[int, typer.Option(help="Max probes this run")] = 50_000,
             remote_seeds: Annotated[bool, typer.Option(help="Fetch public seed lists")] = True) -> None:
    """Weekly: refresh registers, probe seed/known boards, guess slugs for unmatched sponsors."""
    conn, now = connect(db), _now()
    report = RunReport(started_at=now)
    adapters = _adapters()

    async def run(http):
        await pipeline.run_registers(conn, http, _registers(), report, now)
        pipeline.run_match(conn, Overrides.load(overrides))
        all_seeds = load_manual(seeds)
        errors: list[str] = []
        if remote_seeds:
            remote, errors = await fetch_remote_seeds(http, set(adapters))
            all_seeds += remote
        summary = await run_discovery(conn, http, adapters, seeds=all_seeds, now=now, budget=budget)
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
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/test_cli.py -q`
Expected: 5 passed

- [ ] **Step 5: Write the workflows.**

`.github/workflows/weekly-discover.yml`:

```yaml
name: weekly-discover

on:
  schedule:
    - cron: "0 4 * * 0"
  workflow_dispatch:
    inputs:
      budget:
        description: "Max probes this run"
        default: "50000"

permissions:
  contents: write

concurrency:
  group: sponsorscope-db
  cancel-in-progress: false

jobs:
  discover:
    runs-on: ubuntu-latest
    timeout-minutes: 300
    env:
      GH_TOKEN: ${{ github.token }}
    steps:
      - uses: actions/checkout@v5
      - uses: astral-sh/setup-uv@v6
      - run: uv sync --frozen
      - name: Download previous database
        run: scripts/fetch_db.sh
      - name: Discover boards
        run: uv run sponsorscope discover --db sponsorscope.db --budget "${{ inputs.budget || '50000' }}"
      - name: Publish database
        run: scripts/publish_db.sh sponsorscope.db
```

`.github/workflows/smoke.yml`:

```yaml
name: smoke

on:
  workflow_dispatch:

permissions:
  contents: read

jobs:
  smoke:
    runs-on: ubuntu-latest
    timeout-minutes: 30
    steps:
      - uses: actions/checkout@v5
      - uses: astral-sh/setup-uv@v6
      - run: uv sync --frozen
      - run: uv run sponsorscope smoke
```

- [ ] **Step 6: Update `README.md`.**

1. In the first bullet list, replace the **Postings** bullet with:

```markdown
- **Postings:** public ATS job-board APIs: Greenhouse, Lever, Ashby, Workable,
  SmartRecruiters, Recruitee and Personio.
```

2. Under "How it works", add:

```markdown
- `weekly-discover` finds new boards. It probes public slug lists
  ([Feashliaa/job-board-aggregator](https://github.com/Feashliaa/job-board-aggregator)
  and [ConorsCode/open-jobs-data](https://github.com/ConorsCode/open-jobs-data),
  both MIT) and guesses slugs from sponsor names. Misses back off from 1 week
  to 4 weeks to 12 weeks.
- `smoke` (run manually) hits one real board per ATS, to catch upstream API
  changes.
```

3. Add a section:

```markdown
## One-time setup

Set **Settings → Pages → Source** to "GitHub Actions" before the first nightly
run.
```

- [ ] **Step 7: Run every check and a live smoke**

Run: `uv run pytest -q && node --test 'site/*.test.js' && uv run sponsorscope smoke`
Expected:
- all tests pass
- `smoke` prints `ok` for all 7 ATSes and each register (FI may print `blocked`)
- the exit code is 0

If an ATS fails because its smoke board went away, change that entry in `SMOKE_BOARDS` to another live board. The ATS research notes list alternatives: Ashby `ashby`, SmartRecruiters `BoschGroup`, Personio `personio`.

- [ ] **Step 8: Commit**

```bash
git add sponsorscope/cli.py tests/test_cli.py .github/workflows/weekly-discover.yml .github/workflows/smoke.yml README.md
git commit -m "feat: discover and smoke commands with weekly-discover and smoke workflows"
```
