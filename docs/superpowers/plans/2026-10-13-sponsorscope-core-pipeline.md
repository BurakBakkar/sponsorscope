# sponsorscope Core Pipeline (Plan 1 of 3) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a working end-to-end pipeline: the UK sponsor register plus the
Greenhouse and Lever boards go in, rule-labelled postings come out, a static
filterable page is published, and it all runs nightly on GitHub Actions.

**Architecture:**
- A Python package `sponsorscope/` with one module per pipeline stage:
  registers → match → crawl (geo, language, classify) → export.
- SQLite is the single source of truth. It persists between runs as a GitHub
  Release asset.
- The site is vanilla JS. It reads gzipped JSON shards, one per country.
- Plans 2 and 3 add the remaining registers, the remaining ATSes and discovery,
  using the interfaces defined here.

**Tech Stack:**
- Python 3.12 with `uv`, `httpx`, `selectolax`, `rapidfuzz`,
  `lingua-language-detector`, `pycountry`, `typer` and `pyyaml`.
- Tests: `pytest`, `pytest-asyncio` and `respx`.
- Frontend: vanilla ES modules, tested with `node --test`.
- GitHub Actions and GitHub Pages.

**Spec:** `docs/superpowers/specs/2026-10-13-sponsorscope-design.md`

**Roadmap:**
- Plan 2 (registers NL, DK, FI, US, CA, IE) and Plan 3 (the Ashby, Workable,
  SmartRecruiters, Recruitee and Personio adapters, discovery, and the weekly
  and smoke workflows) are written after this plan has been executed.
- All work happens in this local checkout, with one push at the end.

## Global Constraints

- Python `>=3.12`. Package manager: `uv`. Commit `uv.lock`.
- **Commit messages must never contain a `Co-Authored-By` trailer or any
  Claude attribution.**
- Work stays local. **Do not push** until the final task, and push only after
  the user confirms.
- User-Agent: `sponsorscope/0.1 (+https://github.com/BurakBakkar/sponsorscope)`.
- HTTP defaults:
  - 4 concurrent requests per host
  - 5 req/s per host
  - 4 retries on 429/5xx, with exponential backoff plus jitter, honouring
    `Retry-After`
  - 30 s timeout
- English filter: keep a posting when lingua's English confidence is ≥ 0.8.
- Classifier thresholds on the labelled corpus:
  - `no` precision ≥ 0.98
  - `yes` precision ≥ 0.95
  - recall ≥ 0.80 for both
- Sponsorship conflicts (a yes-rule and a no-rule both match) →
  `sponsorship="unknown"`, `mixed=True`.
- Register shrink guard: if the row count drops below 80% of the previous
  version, fail the plugin and keep the old data.
- ATS outage: when more than 50% of an ATS's boards fail in one run, nothing
  from that ATS is deactivated.
- A board is marked `gone` after 3 consecutive 404s.
- Shard size warning: more than 5 MB gzipped.
- Keep 7 dated DB snapshots. Nightly cron: `0 3 * * *` UTC.
- Badge wording:
  - licence → `Licensed sponsor (<COUNTRY>)`
  - history → source-specific counts (templates in Task 10)
- Untrusted text (posting titles, evidence, company names) is rendered with
  `textContent` only. Links are http(s) only.

### Interpretations of the spec (decided here)

1. **No `classify` subcommand.** Descriptions are not stored (spec §4), so
   classification runs inside `crawl` while the text is in memory.
2. **New `seed` subcommand.** It loads `seeds/manual.yaml` into `boards`. It
   stands in for discovery until Plan 3.
3. **`sponsors.period` column (TEXT) added.** The history badge wording in
   spec §2.1 needs a period, such as "FY2026".
4. **`sponsors.route` is `NOT NULL DEFAULT ''`.** SQLite treats NULLs as
   distinct inside UNIQUE constraints, so a nullable column would allow
   duplicate rows.
5. **The ATS-outage rule only applies to ATSes with ≥ 4 crawled boards.**
   Otherwise a single-board ATS returning 404 would count as an "outage"
   forever and never be marked `gone`.
6. **Matching re-runs in full every night** (not incrementally). That's fine
   at v1 volumes; revisit if it gets slow.

## Review Focus

These are inputs the spec implies but no feature test would naturally cover.
Each one has a test in the task named in brackets.

1. **UK CSV encoding drift.** The CSV may arrive with a BOM, as cp1252, or
   with padded header names. It must still parse, with names stripped.
   [Task 7]
2. **Bad Greenhouse `content`.** The field may be `null` or HTML-escaped. The
   posting must still be ingested, with plain-text description and no tags or
   entities. [Task 8]
3. **US state abbreviations.** `"San Francisco, CA"` must resolve to US, not
   Canada, and `"Atlanta, Georgia"` to US, not the country Georgia. [Task 5]
4. **Very short postings** (title only, a one-line description) must not be
   silently dropped as "non-English". [Task 6]
5. **First run on an empty DB.** `export` must produce a valid empty
   `index.json`, and the page must show "0 postings" instead of crashing.
   [Tasks 11 and 12]

---

## File Map

```
pyproject.toml, uv.lock, .gitignore, package.json, README.md
overrides.yaml                      # manual match / non-match overrides
seeds/manual.yaml                   # known boards (until Plan 3 discovery)
scripts/build_cities.py             # one-off: GeoNames → sponsorscope/geo/data/cities.tsv
scripts/publish_db.sh               # CI: upload DB to Release, prune snapshots
sponsorscope/
  __init__.py
  models.py                         # SponsorRecord, RawPosting, Label, content_hash
  text.py                           # html_to_text
  http.py                           # Http: per-host limits, retries, UA
  report.py                         # RunReport
  pipeline.py                       # seed_boards, run_registers, run_match, run_crawl, nightly
  cli.py                            # typer app
  store/__init__.py, store/db.py    # schema + all SQL
  matching/__init__.py, matching/names.py
  geo/__init__.py, geo/country.py, geo/data/cities.tsv
  classify/__init__.py, classify/base.py, classify/lang_detect.py, classify/rules.py
  registers/__init__.py, registers/base.py, registers/gb.py
  ats/__init__.py, ats/base.py, ats/greenhouse.py, ats/lever.py
  export/__init__.py, export/shards.py
site/index.html, site/style.css, site/app.js, site/filters.js, site/filters.test.js
.github/workflows/nightly.yml
tests/conftest.py, tests/test_*.py, tests/fixtures/labels.yaml
```

---

### Task 1: Project scaffold, models, text utilities

**Files:**
- Create: `pyproject.toml`, `.gitignore`, `sponsorscope/__init__.py`, `sponsorscope/models.py`, `sponsorscope/text.py`, `tests/__init__.py`, `tests/test_models.py`

**Interfaces:**
- Produces:
  - `SponsorRecord(country, source, evidence, legal_name, registry_id=None, city=None, route=None, filings=None, period=None)`, frozen
  - `RawPosting(ats, slug, job_id, title, url, description, location_raw, country, remote, posted_at)` with property `.id -> "{ats}:{slug}:{job_id}"`
  - `Label(sponsorship: str, mixed: bool, languages_required: tuple[str, ...], evidence: tuple[str, ...])`
  - `content_hash(text: str) -> str`
  - `html_to_text(markup: str | None) -> str`

- [ ] **Step 1: Write `pyproject.toml` and `.gitignore`**

```toml
[project]
name = "sponsorscope"
version = "0.1.0"
description = "Visa-sponsorship job tracker: official sponsor registers joined with public ATS postings"
requires-python = ">=3.12"
dependencies = [
  "httpx>=0.27",
  "selectolax>=0.3.21",
  "rapidfuzz>=3.9",
  "lingua-language-detector>=2.0",
  "pycountry>=24.6",
  "typer>=0.12",
  "pyyaml>=6.0",
]

[project.scripts]
sponsorscope = "sponsorscope.cli:app"

[dependency-groups]
dev = ["pytest>=8", "pytest-asyncio>=0.24", "respx>=0.21"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["sponsorscope"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
asyncio_default_fixture_loop_scope = "function"
testpaths = ["tests"]
```

`.gitignore`:

```
.venv/
__pycache__/
*.pyc
.pytest_cache/
*.db
site/data/
node_modules/
```

- [ ] **Step 2: Install**

Run: `uv sync`
Expected: creates `.venv` and `uv.lock` with no errors.

- [ ] **Step 3: Write the failing tests** in `tests/test_models.py` (also create an empty `tests/__init__.py` and `sponsorscope/__init__.py`)

```python
from sponsorscope.models import Label, RawPosting, SponsorRecord, content_hash
from sponsorscope.text import html_to_text


def test_posting_id_combines_ats_slug_and_job():
    p = RawPosting(ats="lever", slug="acme", job_id="abc", title="t", url="u",
                   description="d", location_raw=None, country=None, remote=None, posted_at=None)
    assert p.id == "lever:acme:abc"


def test_content_hash_ignores_whitespace_and_case():
    assert content_hash("Hello   World\n") == content_hash("hello world")
    assert content_hash("hello world") != content_hash("hello there")


def test_sponsor_record_defaults():
    r = SponsorRecord(country="GB", source="gb", evidence="licence", legal_name="Acme Ltd")
    assert r.route is None and r.filings is None and r.period is None


def test_label_is_hashable_value():
    assert Label("yes", False, ("nl",), ("x",)) == Label("yes", False, ("nl",), ("x",))


def test_html_to_text_keeps_inline_words_together_and_breaks_blocks():
    html = "<p>We <strong>offer</strong> visa sponsorship.</p><ul><li>Fluent Dutch</li><li>German is a plus</li></ul>"
    assert html_to_text(html) == "We offer visa sponsorship.\nFluent Dutch\nGerman is a plus"


def test_html_to_text_handles_empty():
    assert html_to_text(None) == ""
    assert html_to_text("") == ""
```

- [ ] **Step 4: Run the tests to verify they fail**

Run: `uv run pytest tests/test_models.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'sponsorscope.models'`

- [ ] **Step 5: Implement `sponsorscope/models.py`**

```python
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass


@dataclass(frozen=True)
class SponsorRecord:
    """One entry from an official sponsor register or sponsorship-history dataset."""

    country: str  # ISO-3166 alpha-2, e.g. "GB"
    source: str  # register plugin name, e.g. "gb"
    evidence: str  # "licence" | "history"
    legal_name: str
    registry_id: str | None = None  # KVK / CVR / business ID when present
    city: str | None = None
    route: str | None = None  # e.g. "Skilled Worker", "H-1B"
    filings: int | None = None  # history sources: certified filings / permits
    period: str | None = None  # history sources: e.g. "FY2026", "2026 Q1"


@dataclass(frozen=True)
class RawPosting:
    """A job posting as returned by an ATS adapter, before enrichment."""

    ats: str
    slug: str
    job_id: str
    title: str
    url: str
    description: str  # plain text
    location_raw: str | None
    country: str | None  # ISO-2 from structured ATS fields, if the ATS provides one
    remote: str | None  # "remote" | "hybrid" | "onsite" | None
    posted_at: str | None  # ISO date "YYYY-MM-DD"

    @property
    def id(self) -> str:
        return f"{self.ats}:{self.slug}:{self.job_id}"


@dataclass(frozen=True)
class Label:
    sponsorship: str  # "yes" | "no" | "unknown"
    mixed: bool  # True when yes- and no-rules both matched
    languages_required: tuple[str, ...]  # ISO-639-1 codes
    evidence: tuple[str, ...]  # matched phrases with context


def content_hash(text: str) -> str:
    normalised = re.sub(r"\s+", " ", text).strip().lower()
    return hashlib.sha256(normalised.encode("utf-8")).hexdigest()
```

- [ ] **Step 6: Implement `sponsorscope/text.py`**

```python
from __future__ import annotations

import re

from selectolax.parser import HTMLParser

_BLOCK_END = re.compile(r"(?i)<(?:br\s*/?|/p|/li|/div|/h[1-6]|/tr|/ul|/ol)>")


def html_to_text(markup: str | None) -> str:
    """Convert HTML to plain text: inline tags joined, block ends become newlines."""
    if not markup:
        return ""
    root = HTMLParser(_BLOCK_END.sub("\n", markup)).root
    if root is None:
        return ""
    text = root.text(separator="")
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\s*\n\s*", "\n", text)
    return text.strip()
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `uv run pytest tests/test_models.py -v`
Expected: 6 passed

- [ ] **Step 8: Commit**

```bash
git add pyproject.toml uv.lock .gitignore sponsorscope tests
git commit -m "feat: project scaffold, core models and html_to_text"
```

---

### Task 2: Shared HTTP client

**Files:**
- Create: `sponsorscope/http.py`, `tests/conftest.py`, `tests/test_http.py`

**Interfaces:**
- Produces:
  - `Http(*, concurrency=4, rate=5.0, retries=4, backoff=0.5, timeout=30.0, sleep=asyncio.sleep)`
  - `await Http.get(url, **httpx_kwargs) -> httpx.Response`. Returns the final response, even if it is a 4xx or a 5xx after the retries run out. Raises `httpx.TransportError` once retries are exhausted.
  - `await Http.aclose()`
  - Constant `USER_AGENT`
  - Pytest fixture `http` (an `Http` with no-op sleep)

- [ ] **Step 1: Write `tests/conftest.py`**

```python
import pytest

from sponsorscope.http import Http


async def _no_sleep(_seconds: float) -> None:
    return None


@pytest.fixture
async def http():
    client = Http(sleep=_no_sleep)
    yield client
    await client.aclose()
```

- [ ] **Step 2: Write the failing tests** in `tests/test_http.py`

```python
import httpx
import pytest

from sponsorscope.http import USER_AGENT, Http

URL = "https://example.test/a"


@pytest.fixture
def sleeps():
    return []


@pytest.fixture
async def recording_http(sleeps):
    async def record(seconds: float) -> None:
        sleeps.append(seconds)

    client = Http(sleep=record, rate=1e6)
    yield client
    await client.aclose()


async def test_sends_user_agent(http, respx_mock):
    route = respx_mock.get(URL).mock(return_value=httpx.Response(200))
    await http.get(URL)
    assert route.calls.last.request.headers["User-Agent"] == USER_AGENT
    assert USER_AGENT.startswith("sponsorscope/")


async def test_retries_5xx_then_succeeds(http, respx_mock):
    route = respx_mock.get(URL).mock(side_effect=[httpx.Response(503), httpx.Response(200, text="ok")])
    resp = await http.get(URL)
    assert resp.status_code == 200 and route.call_count == 2


async def test_gives_up_after_retries_and_returns_last_response(http, respx_mock):
    route = respx_mock.get(URL).mock(return_value=httpx.Response(503))
    resp = await http.get(URL)
    assert resp.status_code == 503 and route.call_count == 5  # 1 try + 4 retries


async def test_does_not_retry_404(http, respx_mock):
    route = respx_mock.get(URL).mock(return_value=httpx.Response(404))
    resp = await http.get(URL)
    assert resp.status_code == 404 and route.call_count == 1


async def test_honours_numeric_retry_after(recording_http, sleeps, respx_mock):
    respx_mock.get(URL).mock(side_effect=[httpx.Response(429, headers={"Retry-After": "7"}), httpx.Response(200)])
    await recording_http.get(URL)
    assert 7.0 in sleeps


async def test_http_date_retry_after_in_past_means_no_wait(recording_http, sleeps, respx_mock):
    respx_mock.get(URL).mock(
        side_effect=[httpx.Response(429, headers={"Retry-After": "Sun, 06 Nov 1994 08:49:37 GMT"}), httpx.Response(200)]
    )
    await recording_http.get(URL)
    assert 0.0 in sleeps


async def test_retry_after_is_capped(recording_http, sleeps, respx_mock):
    respx_mock.get(URL).mock(side_effect=[httpx.Response(429, headers={"Retry-After": "99999"}), httpx.Response(200)])
    await recording_http.get(URL)
    assert max(sleeps) <= 300.0


async def test_retries_transport_errors(http, respx_mock):
    route = respx_mock.get(URL).mock(side_effect=[httpx.ConnectError("boom"), httpx.Response(200)])
    resp = await http.get(URL)
    assert resp.status_code == 200 and route.call_count == 2


async def test_raises_after_persistent_transport_errors(http, respx_mock):
    respx_mock.get(URL).mock(side_effect=httpx.ConnectError("boom"))
    with pytest.raises(httpx.TransportError):
        await http.get(URL)
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `uv run pytest tests/test_http.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'sponsorscope.http'`

- [ ] **Step 4: Implement `sponsorscope/http.py`**

```python
from __future__ import annotations

import asyncio
import email.utils
import random
import time
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from urllib.parse import urlsplit

import httpx

USER_AGENT = "sponsorscope/0.1 (+https://github.com/BurakBakkar/sponsorscope)"
RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})
MAX_RETRY_AFTER = 300.0

Sleep = Callable[[float], Awaitable[None]]


class _HostLimiter:
    """Caps concurrent requests and spaces request starts for one host."""

    def __init__(self, concurrency: int, rate: float, sleep: Sleep):
        self.semaphore = asyncio.Semaphore(concurrency)
        self._interval = 1.0 / rate
        self._next_slot = 0.0
        self._lock = asyncio.Lock()
        self._sleep = sleep

    async def wait_turn(self) -> None:
        async with self._lock:
            now = time.monotonic()
            slot = max(now, self._next_slot)
            self._next_slot = slot + self._interval
        delay = slot - now
        if delay > 0:
            await self._sleep(delay)


class Http:
    """Polite async HTTP client shared by every register and ATS adapter."""

    def __init__(
        self,
        *,
        concurrency: int = 4,
        rate: float = 5.0,
        retries: int = 4,
        backoff: float = 0.5,
        timeout: float = 30.0,
        sleep: Sleep = asyncio.sleep,
    ):
        self._client = httpx.AsyncClient(
            timeout=timeout, headers={"User-Agent": USER_AGENT}, follow_redirects=True
        )
        self._concurrency = concurrency
        self._rate = rate
        self._retries = retries
        self._backoff = backoff
        self._sleep = sleep
        self._limiters: dict[str, _HostLimiter] = {}

    def _limiter(self, host: str) -> _HostLimiter:
        if host not in self._limiters:
            self._limiters[host] = _HostLimiter(self._concurrency, self._rate, self._sleep)
        return self._limiters[host]

    async def get(self, url: str, **kwargs) -> httpx.Response:
        limiter = self._limiter(urlsplit(url).hostname or "")
        attempt = 0
        while True:
            response: httpx.Response | None = None
            async with limiter.semaphore:
                await limiter.wait_turn()
                try:
                    response = await self._client.get(url, **kwargs)
                except httpx.TransportError:
                    if attempt >= self._retries:
                        raise
            if response is not None and (
                response.status_code not in RETRY_STATUSES or attempt >= self._retries
            ):
                return response
            await self._sleep(self._delay(attempt, response))
            attempt += 1

    def _delay(self, attempt: int, response: httpx.Response | None) -> float:
        retry_after = response.headers.get("Retry-After", "").strip() if response is not None else ""
        if retry_after.isdigit():
            return min(float(retry_after), MAX_RETRY_AFTER)
        if retry_after:
            try:
                when = email.utils.parsedate_to_datetime(retry_after)
                seconds = (when - datetime.now(timezone.utc)).total_seconds()
                return min(max(0.0, seconds), MAX_RETRY_AFTER)
            except (TypeError, ValueError):
                pass
        return self._backoff * (2**attempt) + random.uniform(0, self._backoff)

    async def aclose(self) -> None:
        await self._client.aclose()
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/test_http.py -v`
Expected: 9 passed

- [ ] **Step 6: Commit**

```bash
git add sponsorscope/http.py tests/conftest.py tests/test_http.py
git commit -m "feat: polite async HTTP client with per-host limits and retries"
```

---

### Task 3: Name normalisation and matching

This task comes before the store because `store.db` uses `normalize`.

**Files:**
- Create: `sponsorscope/matching/__init__.py` (empty), `sponsorscope/matching/names.py`, `tests/test_matching.py`

**Interfaces:**
- Produces:
  - `normalize(name: str) -> str`
  - `compact(norm: str) -> str` (spaces removed)
  - `SponsorIndex.build(rows: Iterable[tuple[int, str]]) -> SponsorIndex`, where each row is `(sponsor_id, norm_name)`. Attributes: `by_norm: dict[str, list[int]]`, `by_compact: dict[str, set[str]]`, `norms: list[str]`
  - `find_match(company_norm: str, index: SponsorIndex) -> tuple[str, str, float] | None`, returning `(sponsor_norm, method, score)` with method `"exact"` or `"normalised"`
  - `Overrides(force: set[tuple[str, str]] = set(), forbid: set[tuple[str, str]] = set())`, holding normalised `(company, sponsor)` pairs
  - `Overrides.load(path: Path) -> Overrides`
  - Constants `SHORT_NAME_MAX = 4`, `FUZZY_CUTOFF = 95`

- [ ] **Step 1: Write the failing tests** in `tests/test_matching.py`

```python
import pytest

from sponsorscope.matching.names import Overrides, SponsorIndex, compact, find_match, normalize


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("Booking.com B.V.", "booking com"),
        ("  ACME Widgets Limited ", "acme widgets"),
        ("Café Ünïcode GmbH", "cafe unicode"),
        ("Marks & Spencer PLC", "marks and spencer"),
        ("Monzo Bank Ltd", "monzo bank"),
        ("Adyen N.V.", "adyen"),
        ("Novo Nordisk A/S", "novo nordisk"),
        ("Wolt Enterprises Oy", "wolt enterprises"),
        ("Spotify AB", "spotify"),
        ("Acme Holdings Group Ltd", "acme"),
        ("Airbnb UK Ltd", "airbnb"),
        ('""Aa-Dee"" Services B.V.', "aa dee"),
        ("Ltd", ""),
    ],
)
def test_normalize(raw, expected):
    assert normalize(raw) == expected


def test_compact_removes_spaces():
    assert compact("booking com") == "bookingcom"


def _index(*legal_names):
    return SponsorIndex.build((i, normalize(n)) for i, n in enumerate(legal_names, start=1))


INDEX = _index(
    "Booking.com B.V.",
    "Apple Retail UK Limited",
    "Monzo Bank Ltd",
    "IBM UK Ltd",
)


@pytest.mark.parametrize(
    "company, expected",
    [
        ("Booking.com", ("booking com", "exact")),
        ("Bookingcom", ("booking com", "normalised")),
        ("Monzo Bank", ("monzo bank", "exact")),
        ("Apple", None),  # "apple retail" is a different entity name
        ("Monzo", None),  # too far from "monzo bank" to auto-match
        ("IBM", None),  # short-name guard, even though "ibm" would match exactly
    ],
)
def test_find_match(company, expected):
    result = find_match(normalize(company), INDEX)
    if expected is None:
        assert result is None
    else:
        assert result is not None and result[:2] == expected


def test_fuzzy_match_requires_unique_candidate():
    one = _index("Northwind Global Trading Partners X Ltd")
    two = _index("Northwind Global Trading Partners X Ltd", "Northwind Global Trading Partners Y Ltd")
    company = normalize("Northwind Global Trading Partners")
    match = find_match(company, one)
    assert match is not None and match[1] == "normalised" and match[2] >= 95
    assert find_match(company, two) is None


def test_index_groups_ids_by_norm():
    idx = SponsorIndex.build([(1, "acme"), (2, "acme"), (3, "beta")])
    assert idx.by_norm["acme"] == [1, 2]
    assert sorted(idx.norms) == ["acme", "beta"]


def test_overrides_load_normalises(tmp_path):
    path = tmp_path / "overrides.yaml"
    path.write_text(
        "match:\n  - {company: Stripe, sponsor: Stripe Payments UK Ltd}\n"
        "forbid:\n  - {company: Apple, sponsor: Apple Ltd}\n"
    )
    o = Overrides.load(path)
    assert o.force == {("stripe", "stripe payments")}
    assert o.forbid == {("apple", "apple")}


def test_overrides_load_missing_or_empty_file(tmp_path):
    assert Overrides.load(tmp_path / "nope.yaml") == Overrides()
    empty = tmp_path / "empty.yaml"
    empty.write_text("")
    assert Overrides.load(empty) == Overrides()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_matching.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement `sponsorscope/matching/names.py`**

```python
from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from rapidfuzz import fuzz, process

SHORT_NAME_MAX = 4
FUZZY_CUTOFF = 95

LEGAL_SUFFIXES = frozenset({
    "ltd", "limited", "plc", "llp", "lp", "bv", "nv", "gmbh", "ag", "inc", "llc", "corp",
    "corporation", "co", "company", "as", "aps", "oy", "oyj", "ab", "sa", "sarl", "srl", "pty",
})
QUALIFIERS = frozenset({
    "uk", "nederland", "netherlands", "europe", "international", "holding", "holdings",
    "group", "services",
})
_TRAILING = LEGAL_SUFFIXES | QUALIFIERS
_DOTTED = [("b.v.", "bv"), ("n.v.", "nv"), ("a/s", "as")]


def normalize(name: str) -> str:
    """Canonical form of a company name for matching register entries to ATS boards."""
    s = unicodedata.normalize("NFKD", name)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = s.lower().replace("&", " and ")
    for dotted, plain in _DOTTED:
        s = s.replace(dotted, plain)
    tokens = re.sub(r"[^a-z0-9]+", " ", s).split()
    while tokens and tokens[-1] in _TRAILING:
        tokens.pop()
    return " ".join(tokens)


def compact(norm: str) -> str:
    return norm.replace(" ", "")


@dataclass
class SponsorIndex:
    by_norm: dict[str, list[int]]
    by_compact: dict[str, set[str]]
    norms: list[str]

    @classmethod
    def build(cls, rows: Iterable[tuple[int, str]]) -> SponsorIndex:
        by_norm: dict[str, list[int]] = {}
        for sponsor_id, norm in rows:
            if norm:
                by_norm.setdefault(norm, []).append(sponsor_id)
        by_compact: dict[str, set[str]] = {}
        for norm in by_norm:
            by_compact.setdefault(compact(norm), set()).add(norm)
        return cls(by_norm=by_norm, by_compact=by_compact, norms=list(by_norm))


def find_match(company_norm: str, index: SponsorIndex) -> tuple[str, str, float] | None:
    """Return (sponsor_norm, method, score) for an unambiguous match, else None."""
    if len(compact(company_norm)) <= SHORT_NAME_MAX:
        return None
    if company_norm in index.by_norm:
        return company_norm, "exact", 100.0
    candidates = set(index.by_compact.get(compact(company_norm), set()))
    for norm, _score, _idx in process.extract(
        company_norm, index.norms, scorer=fuzz.token_sort_ratio, score_cutoff=FUZZY_CUTOFF, limit=3
    ):
        candidates.add(norm)
    if len(candidates) != 1:
        return None
    norm = candidates.pop()
    return norm, "normalised", float(fuzz.token_sort_ratio(company_norm, norm))


@dataclass
class Overrides:
    force: set[tuple[str, str]] = field(default_factory=set)
    forbid: set[tuple[str, str]] = field(default_factory=set)

    @classmethod
    def load(cls, path: Path) -> Overrides:
        if not path.exists():
            return cls()
        data = yaml.safe_load(path.read_text()) or {}

        def pairs(key: str) -> set[tuple[str, str]]:
            return {(normalize(e["company"]), normalize(e["sponsor"])) for e in data.get(key) or []}

        return cls(force=pairs("match"), forbid=pairs("forbid"))
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_matching.py -v`
Expected: all passed (24 tests)

- [ ] **Step 5: Commit**

```bash
git add sponsorscope/matching tests/test_matching.py
git commit -m "feat: company name normalisation and conservative sponsor matching"
```

---

### Task 4: SQLite store

**Files:**
- Create: `sponsorscope/store/__init__.py` (empty), `sponsorscope/store/db.py`, `tests/test_store.py`

**Interfaces:**
- Consumes: `normalize` (Task 3), `SponsorRecord`, `RawPosting` and `Label` (Task 1)
- Produces (all take `conn: sqlite3.Connection` first; `now` is an ISO timestamp string):
  - `connect(path: Path | str) -> sqlite3.Connection` (rows come back as `sqlite3.Row`; the schema is created if missing)
  - `count_sponsor_keys(records: Iterable[SponsorRecord]) -> int`
  - `upsert_sponsors(conn, source, records, version, now) -> int`
  - `get_source_version(conn, source) -> str | None`
  - `active_sponsor_count(conn, source) -> int`
  - `get_or_create_company(conn, display_name) -> int`
  - `upsert_board(conn, ats, slug, company_id, *, status, origin, now) -> None`. If the board exists, it updates `company_id` only and never changes `status`.
  - `boards_to_crawl(conn) -> list[sqlite3.Row]` with columns `ats, slug, company_id`, only for `status='hit'`
  - `record_board_result(conn, ats, slug, outcome) -> None`, where outcome is `"ok"` or `"not_found"`
  - `get_posting_meta(conn, posting_id) -> sqlite3.Row | None` with columns `content_hash, lang`
  - `upsert_posting(conn, p: RawPosting, *, company_id, country, lang, content_hash, now) -> None`
  - `deactivate_missing(conn, ats, slug, seen_ids: set[str]) -> int`
  - `has_label(conn, posting_id, content_hash, version) -> bool`
  - `save_label(conn, posting_id, content_hash, version, label: Label) -> None`
  - `replace_matches(conn, matches: Iterable[tuple[int, int, str, float]]) -> None`, rows being `(sponsor_id, company_id, method, score)`
  - Constant `GONE_AFTER = 3`

- [ ] **Step 1: Write the failing tests** in `tests/test_store.py`

```python
import pytest

from sponsorscope.models import Label, RawPosting, SponsorRecord
from sponsorscope.store import db

T1, T2 = "2026-10-13T03:00:00+00:00", "2026-10-14T03:00:00+00:00"


@pytest.fixture
def conn(tmp_path):
    c = db.connect(tmp_path / "t.db")
    yield c
    c.close()


def rec(name, route="Skilled Worker"):
    return SponsorRecord(country="GB", source="gb", evidence="licence", legal_name=name, route=route)


def posting(job_id, title="Engineer"):
    return RawPosting(ats="greenhouse", slug="acme", job_id=job_id, title=title, url="https://x",
                      description="d", location_raw="London", country=None, remote=None, posted_at="2026-10-01")


def test_connect_is_idempotent(tmp_path):
    db.connect(tmp_path / "t.db").close()
    c = db.connect(tmp_path / "t.db")
    tables = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"sponsors", "source_versions", "companies", "boards", "sponsor_matches", "postings", "labels"} <= tables


def test_upsert_sponsors_and_active_count(conn):
    assert db.upsert_sponsors(conn, "gb", [rec("Acme Ltd"), rec("Beta Ltd")], "v1", T1) == 2
    assert db.get_source_version(conn, "gb") == "v1"
    assert db.active_sponsor_count(conn, "gb") == 2
    db.upsert_sponsors(conn, "gb", [rec("Acme Ltd")], "v2", T2)
    assert db.active_sponsor_count(conn, "gb") == 1  # Beta retired but row kept
    assert conn.execute("SELECT COUNT(*) FROM sponsors").fetchone()[0] == 2


def test_null_route_does_not_duplicate(conn):
    db.upsert_sponsors(conn, "gb", [rec("Acme Ltd", route=None), rec("ACME Limited", route=None)], "v1", T1)
    assert conn.execute("SELECT COUNT(*) FROM sponsors").fetchone()[0] == 1


def test_count_sponsor_keys_matches_upsert_dedupe():
    records = [rec("Acme Ltd"), rec("ACME Limited"), rec("Acme Ltd", route="Global Business Mobility"), rec("Ltd")]
    assert db.count_sponsor_keys(records) == 2  # "Ltd" normalises to "" and is skipped


def test_get_or_create_company_dedupes_by_norm(conn):
    a = db.get_or_create_company(conn, "Acme Ltd")
    assert db.get_or_create_company(conn, "ACME Limited") == a
    assert db.get_or_create_company(conn, "Beta") != a


def test_upsert_board_never_resurrects_gone_board(conn):
    cid = db.get_or_create_company(conn, "Acme")
    db.upsert_board(conn, "greenhouse", "acme", cid, status="hit", origin="seed", now=T1)
    for _ in range(db.GONE_AFTER):
        db.record_board_result(conn, "greenhouse", "acme", "not_found")
    assert db.boards_to_crawl(conn) == []
    db.upsert_board(conn, "greenhouse", "acme", cid, status="hit", origin="seed", now=T2)
    assert db.boards_to_crawl(conn) == []


def test_ok_result_resets_not_found_streak(conn):
    cid = db.get_or_create_company(conn, "Acme")
    db.upsert_board(conn, "greenhouse", "acme", cid, status="hit", origin="seed", now=T1)
    db.record_board_result(conn, "greenhouse", "acme", "not_found")
    db.record_board_result(conn, "greenhouse", "acme", "not_found")
    db.record_board_result(conn, "greenhouse", "acme", "ok")
    db.record_board_result(conn, "greenhouse", "acme", "not_found")
    assert [b["slug"] for b in db.boards_to_crawl(conn)] == ["acme"]


def test_postings_upsert_meta_and_deactivate(conn):
    cid = db.get_or_create_company(conn, "Acme")
    for jid in ("1", "2"):
        db.upsert_posting(conn, posting(jid), company_id=cid, country="GB", lang="en", content_hash=f"h{jid}", now=T1)
    meta = db.get_posting_meta(conn, "greenhouse:acme:1")
    assert meta["content_hash"] == "h1" and meta["lang"] == "en"
    assert db.get_posting_meta(conn, "greenhouse:acme:9") is None
    assert db.deactivate_missing(conn, "greenhouse", "acme", {"greenhouse:acme:1"}) == 1
    active = {r[0] for r in conn.execute("SELECT id FROM postings WHERE active=1")}
    assert active == {"greenhouse:acme:1"}
    db.upsert_posting(conn, posting("2"), company_id=cid, country="GB", lang="en", content_hash="h2", now=T2)
    first_seen = conn.execute("SELECT first_seen, active FROM postings WHERE id='greenhouse:acme:2'").fetchone()
    assert tuple(first_seen) == (T1, 1)  # reactivated, first_seen preserved


def test_labels(conn):
    label = Label("yes", False, ("nl",), ("We offer visa sponsorship",))
    assert not db.has_label(conn, "p1", "h1", "rules-1")
    db.save_label(conn, "p1", "h1", "rules-1", label)
    assert db.has_label(conn, "p1", "h1", "rules-1")
    assert not db.has_label(conn, "p1", "h1", "rules-2")
    row = conn.execute("SELECT * FROM labels").fetchone()
    assert row["languages_required"] == '["nl"]' and row["mixed"] == 0


def test_replace_matches(conn):
    db.replace_matches(conn, [(1, 1, "exact", 100.0), (2, 1, "normalised", 97.0)])
    db.replace_matches(conn, [(3, 2, "manual", 100.0)])
    assert [tuple(r) for r in conn.execute("SELECT sponsor_id, company_id FROM sponsor_matches")] == [(3, 2)]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_store.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement `sponsorscope/store/db.py`**

```python
from __future__ import annotations

import json
import sqlite3
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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_store.py -v`
Expected: 10 passed

- [ ] **Step 5: Commit**

```bash
git add sponsorscope/store tests/test_store.py
git commit -m "feat: SQLite store with versioned sponsors, boards, postings and labels"
```

---

### Task 5: Location → country resolution

**Files:**
- Create: `sponsorscope/geo/__init__.py` (empty), `sponsorscope/geo/country.py`, `scripts/build_cities.py`, `sponsorscope/geo/data/cities.tsv` (generated), `tests/test_geo.py`

**Interfaces:**
- Produces:
  - `resolve_country(location_raw: str | None, structured: str | None = None, cities: Mapping[str, str] | None = None) -> str | None`. When `cities` is `None`, it uses `load_cities()`.
  - `load_cities(path: Path = CITIES_PATH) -> dict[str, str]`, mapping a lowercase city name to ISO-2. Returns `{}` if the file is missing.

- [ ] **Step 1: Write the failing tests** in `tests/test_geo.py`

```python
import pytest

from sponsorscope.geo.country import resolve_country

CITIES = {
    "london": "GB", "amsterdam": "NL", "san francisco": "US", "toronto": "CA", "berlin": "DE",
    "atlanta": "US", "paris": "FR", "munich": "DE",
}


@pytest.mark.parametrize(
    "location, structured, expected",
    [
        ("London, UK", None, "GB"),
        ("Amsterdam / Remote (EU)", None, "NL"),
        ("Remote", None, None),
        ("San Francisco, CA", None, "US"),  # CA is California here, not Canada
        ("Toronto, ON", None, "CA"),
        ("Berlin, DE", None, "DE"),
        ("Remote - US", None, "US"),
        ("London, Ontario, Canada", None, "CA"),  # country name beats city
        ("Atlanta, Georgia", None, "US"),  # US state, not the country
        ("New York, NY", None, "US"),
        ("Berlin, Germany", None, "DE"),
        ("Munich, Germany; Remote", None, "DE"),
        ("London or Berlin", None, None),
        ("London; Berlin", None, None),  # two countries → unknown
        (None, "gb", "GB"),
        ("Paris", "EU", "FR"),  # invalid structured code falls back to text
        (None, None, None),
        ("", None, None),
    ],
)
def test_resolve_country(location, structured, expected):
    assert resolve_country(location, structured, cities=CITIES) == expected
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_geo.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement `sponsorscope/geo/country.py`**

```python
from __future__ import annotations

import csv
import re
from collections.abc import Mapping
from functools import lru_cache
from pathlib import Path

import pycountry

CITIES_PATH = Path(__file__).parent / "data" / "cities.tsv"

_US_STATES = [
    "alabama", "alaska", "arizona", "arkansas", "california", "colorado", "connecticut", "delaware",
    "florida", "georgia", "hawaii", "idaho", "illinois", "indiana", "iowa", "kansas", "kentucky",
    "louisiana", "maine", "maryland", "massachusetts", "michigan", "minnesota", "mississippi",
    "missouri", "montana", "nebraska", "nevada", "new hampshire", "new jersey", "new mexico",
    "new york", "north carolina", "north dakota", "ohio", "oklahoma", "oregon", "pennsylvania",
    "rhode island", "south carolina", "south dakota", "tennessee", "texas", "utah", "vermont",
    "virginia", "washington", "west virginia", "wisconsin", "wyoming", "district of columbia",
    "washington dc", "washington d.c.",
]
_CA_PROVINCES = [
    "alberta", "british columbia", "manitoba", "new brunswick", "newfoundland and labrador",
    "nova scotia", "ontario", "prince edward island", "quebec", "québec", "saskatchewan",
    "northwest territories", "nunavut", "yukon",
]
_EXTRA = {
    "uk": "GB", "u.k.": "GB", "england": "GB", "scotland": "GB", "wales": "GB",
    "northern ireland": "GB", "great britain": "GB", "britain": "GB",
    "us": "US", "usa": "US", "u.s.": "US", "u.s.a.": "US", "united states of america": "US",
    "netherlands": "NL", "the netherlands": "NL", "holland": "NL", "deutschland": "DE",
    "czech republic": "CZ", "south korea": "KR", "korea": "KR", "russia": "RU", "vietnam": "VN",
    "turkey": "TR", "türkiye": "TR", "uae": "AE", "taiwan": "TW", "iran": "IR", "bolivia": "BO",
    "venezuela": "VE", "tanzania": "TZ", "syria": "SY", "laos": "LA", "moldova": "MD",
    **{s: "US" for s in _US_STATES},  # overrides the country Georgia on purpose
    **{p: "CA" for p in _CA_PROVINCES},
}

_SPLIT = re.compile(r"[,/|;()\n]+|\s[-–]\s")


@lru_cache(maxsize=1)
def _country_names() -> dict[str, str]:
    names: dict[str, str] = {}
    for c in pycountry.countries:
        for attr in ("name", "official_name", "common_name"):
            value = getattr(c, attr, None)
            if value:
                names[value.lower()] = c.alpha_2
    names.update(_EXTRA)
    return names


@lru_cache(maxsize=1)
def _codes() -> tuple[frozenset[str], dict[str, str]]:
    alpha2 = frozenset(c.alpha_2 for c in pycountry.countries)
    alpha3 = {c.alpha_3: c.alpha_2 for c in pycountry.countries}
    return alpha2, alpha3


@lru_cache(maxsize=1)
def load_cities(path: Path = CITIES_PATH) -> dict[str, str]:
    if not path.exists():
        return {}
    with path.open(encoding="utf-8", newline="") as f:
        return {row[0]: row[1] for row in csv.reader(f, delimiter="\t") if len(row) == 2}


def resolve_country(location_raw: str | None, structured: str | None = None,
                    cities: Mapping[str, str] | None = None) -> str | None:
    """Best-effort ISO-2 country for a posting; None when unknown or ambiguous.

    Evidence tiers, strongest first: country/state names, city names, bare codes.
    The first tier with any hit decides; more than one country in it means None.
    """
    alpha2, alpha3 = _codes()
    if structured and structured.strip().upper() in alpha2:
        return structured.strip().upper()
    if not location_raw:
        return None
    cities = load_cities() if cities is None else cities
    names = _country_names()
    tiers: list[set[str]] = [set(), set(), set()]
    for segment in _SPLIT.split(location_raw):
        token = segment.strip()
        if not token:
            continue
        low = token.lower()
        if low in names:
            tiers[0].add(names[low])
        elif low in cities:
            tiers[1].add(cities[low])
        elif token.isupper() and token in alpha2:
            tiers[2].add(token)
        elif token.isupper() and token in alpha3:
            tiers[2].add(alpha3[token])
    for tier in tiers:
        if len(tier) == 1:
            return next(iter(tier))
        if len(tier) > 1:
            return None
    return None
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_geo.py -v`
Expected: 18 passed

- [ ] **Step 5: Write `scripts/build_cities.py`**

```python
"""Build sponsorscope/geo/data/cities.tsv from GeoNames cities15000 (CC BY 4.0).

Run once, then commit the output:  uv run python scripts/build_cities.py
For duplicate names the most populous city wins (London → GB, not London, Ontario).
"""
from __future__ import annotations

import io
import zipfile
from pathlib import Path

import httpx

URL = "https://download.geonames.org/export/dump/cities15000.zip"
OUT = Path(__file__).resolve().parent.parent / "sponsorscope" / "geo" / "data" / "cities.tsv"


def main() -> None:
    data = httpx.get(URL, timeout=120, follow_redirects=True).raise_for_status().content
    best: dict[str, tuple[str, int]] = {}
    with zipfile.ZipFile(io.BytesIO(data)) as zf, zf.open("cities15000.txt") as raw:
        for line in io.TextIOWrapper(raw, encoding="utf-8"):
            cols = line.rstrip("\n").split("\t")
            name, ascii_name, cc, pop = cols[1], cols[2], cols[8], int(cols[14] or 0)
            for key in {name.lower().strip(), ascii_name.lower().strip()}:
                if key and (key not in best or pop > best[key][1]):
                    best[key] = (cc, pop)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", encoding="utf-8", newline="") as f:
        for key in sorted(best):
            f.write(f"{key}\t{best[key][0]}\n")
    print(f"wrote {len(best)} cities to {OUT}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 6: Generate the table and check it**

Run: `uv run python scripts/build_cities.py && grep -P '^(london|amsterdam|cambridge)\t' sponsorscope/geo/data/cities.tsv`
Expected: prints `wrote N cities` with N around 40,000–50,000, then `amsterdam	NL`, `cambridge	GB` and `london	GB`.

- [ ] **Step 7: Add a test that the real table loads**

Append to `tests/test_geo.py`:

```python
from sponsorscope.geo.country import load_cities


def test_bundled_city_table_resolves_major_cities():
    cities = load_cities()
    assert cities["london"] == "GB" and cities["amsterdam"] == "NL"
    assert resolve_country("Dublin") == "IE"
```

Run: `uv run pytest tests/test_geo.py -v`
Expected: 19 passed

- [ ] **Step 8: Commit**

```bash
git add sponsorscope/geo scripts/build_cities.py tests/test_geo.py
git commit -m "feat: resolve posting locations to ISO countries with GeoNames city table"
```

---

### Task 6: English filter and rules classifier

**Files:**
- Create: `sponsorscope/classify/__init__.py` (empty), `sponsorscope/classify/base.py`, `sponsorscope/classify/lang_detect.py`, `sponsorscope/classify/rules.py`, `tests/fixtures/labels.yaml`, `tests/test_lang_detect.py`, `tests/test_rules.py`

**Interfaces:**
- Consumes: `Label` (Task 1)
- Produces:
  - `Classifier` Protocol, with attribute `version: str` and method `classify(text: str) -> Label`
  - `is_english(text: str, threshold: float = 0.8) -> bool`. Text shorter than 40 characters returns `True`.
  - `RulesClassifier()` with `version = rules.VERSION` (`"rules-1"`)
  - Constant `rules.LANGUAGES: dict[str, str]`, mapping an ISO code to a name regex

- [ ] **Step 1: Write the failing language tests** in `tests/test_lang_detect.py`

```python
from sponsorscope.classify.lang_detect import is_english

EN = ("We are looking for a backend engineer to join our payments team in London. "
      "You will design and build reliable services used by millions of customers.")
NL = ("Wij zoeken een ervaren backend ontwikkelaar voor ons betalingsteam in Amsterdam. "
      "Je bouwt betrouwbare diensten die door miljoenen klanten worden gebruikt.")
DE = ("Wir suchen eine erfahrene Backend-Entwicklerin für unser Zahlungsteam in Berlin. "
      "Du entwickelst zuverlässige Dienste, die von Millionen Kunden genutzt werden.")


def test_detects_english():
    assert is_english(EN)


def test_rejects_dutch_and_german():
    assert not is_english(NL)
    assert not is_english(DE)


def test_short_text_is_kept_rather_than_silently_dropped():
    assert is_english("Data Engineer")
    assert is_english("Ingenieur (m/w/d)")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_lang_detect.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement `sponsorscope/classify/base.py` and `sponsorscope/classify/lang_detect.py`**

`base.py`:

```python
from __future__ import annotations

from typing import Protocol

from sponsorscope.models import Label


class Classifier(Protocol):
    version: str

    def classify(self, text: str) -> Label: ...
```

`lang_detect.py`:

```python
from __future__ import annotations

from functools import lru_cache

from lingua import Language, LanguageDetector, LanguageDetectorBuilder

MIN_RELIABLE_CHARS = 40
_LANGUAGES = [
    Language.ENGLISH, Language.DUTCH, Language.GERMAN, Language.FRENCH, Language.SPANISH,
    Language.PORTUGUESE, Language.ITALIAN, Language.DANISH, Language.SWEDISH, Language.FINNISH,
    Language.BOKMAL, Language.POLISH, Language.JAPANESE, Language.CHINESE,
]


@lru_cache(maxsize=1)
def _detector() -> LanguageDetector:
    return LanguageDetectorBuilder.from_languages(*_LANGUAGES).build()


def is_english(text: str, threshold: float = 0.8) -> bool:
    """True if the posting is English. Very short text is kept: detection is unreliable there."""
    sample = text.strip()[:2000]
    if len(sample) < MIN_RELIABLE_CHARS:
        return True
    return _detector().compute_language_confidence(sample, Language.ENGLISH) >= threshold
```

- [ ] **Step 4: Run the language tests to verify they pass**

Run: `uv run pytest tests/test_lang_detect.py -v`
Expected: 3 passed

- [ ] **Step 5: Write the labelled corpus** `tests/fixtures/labels.yaml`

```yaml
# Labelled English snippets for the rules classifier (and any future LLM classifier).
# sponsorship: yes | no | unknown;  mixed: true when both yes- and no-signals appear;  langs: ISO-639-1
# --- yes
- {text: "We offer visa sponsorship for this role.", sponsorship: "yes"}
- {text: "Visa sponsorship is available for candidates who need it.", sponsorship: "yes"}
- {text: "We can sponsor Skilled Worker visas.", sponsorship: "yes"}
- {text: "We are able to sponsor visas for this position.", sponsorship: "yes"}
- {text: "Relocation and visa support provided.", sponsorship: "yes"}
- {text: "We provide visa and relocation assistance to international hires.", sponsorship: "yes"}
- {text: "This role is eligible for the Dutch highly skilled migrant scheme.", sponsorship: "yes"}
- {text: "As a recognised sponsor we can apply for your kennismigrant permit.", sponsorship: "yes"}
- {text: "Our benefits include visa sponsorship and a relocation budget.", sponsorship: "yes"}
- {text: "We will sponsor your work visa if required.", sponsorship: "yes"}
- {text: "We are open to sponsoring candidates from outside the EU.", sponsorship: "yes"}
- {text: "Full visa sponsorship offered.", sponsorship: "yes"}
- {text: "The company will sponsor the work permit for the successful candidate.", sponsorship: "yes"}
- {text: "We happily sponsor visas for engineers relocating to London.", sponsorship: "yes"}
- {text: "Visa sponsorship provided where needed.", sponsorship: "yes"}
- {text: "We're offering visa sponsorship and help with housing.", sponsorship: "yes"}
- {text: "Sponsorship is available for the Skilled Worker route.", sponsorship: "yes"}
- {text: "Providing work permit sponsorship for non-EU applicants.", sponsorship: "yes"}
# --- no
- {text: "Unfortunately we are unable to offer visa sponsorship.", sponsorship: "no"}
- {text: "We cannot sponsor visas for this role.", sponsorship: "no"}
- {text: "Candidates must have the right to work in the UK.", sponsorship: "no"}
- {text: "You must already have the right to work in the Netherlands.", sponsorship: "no"}
- {text: "No visa sponsorship is available for this position.", sponsorship: "no"}
- {text: "Visa sponsorship is not available.", sponsorship: "no"}
- {text: "We do not sponsor work visas.", sponsorship: "no"}
- {text: "This role does not offer sponsorship.", sponsorship: "no"}
- {text: "Applicants must hold the right to work in Ireland.", sponsorship: "no"}
- {text: "We are not able to provide sponsorship.", sponsorship: "no"}
- {text: "Sponsorship will not be provided.", sponsorship: "no"}
- {text: "You must be eligible to work in the US without sponsorship.", sponsorship: "no"}
- {text: "Unable to sponsor at this time.", sponsorship: "no"}
- {text: "We won't be able to sponsor visas.", sponsorship: "no"}
- {text: "No sponsorship available.", sponsorship: "no"}
- {text: "This position is not eligible for visa sponsorship.", sponsorship: "no"}
- {text: "We're not in a position to offer visa sponsorship.", sponsorship: "no"}
- {text: "Right to work in the EU is required; we do not provide sponsorship.", sponsorship: "no"}
- {text: "Please note we can’t offer visa sponsorship.", sponsorship: "no"}
- {text: "Must have existing right to work in Denmark.", sponsorship: "no"}
# --- unknown
- {text: "We are a fast-growing fintech based in London.", sponsorship: "unknown"}
- {text: "Competitive salary, 25 days holiday and a pension scheme.", sponsorship: "unknown"}
- {text: "You will work closely with our data team.", sponsorship: "unknown"}
- {text: "We are a licensed sponsor under the UK points-based system.", sponsorship: "unknown"}
- {text: "Our clients include visa processing agencies.", sponsorship: "unknown"}
- {text: "Sponsor relationships with key partners.", sponsorship: "unknown"}
- {text: "Strong communication skills are required.", sponsorship: "unknown"}
- {text: "The role is based in Amsterdam with hybrid working.", sponsorship: "unknown"}
- {text: "Experience with immigration law is a plus.", sponsorship: "unknown"}
- {text: "Our mission is to make travel accessible.", sponsorship: "unknown"}
# --- mixed (yes and no both present → unknown + mixed)
- {text: "We can sponsor visas for senior engineers but are unable to sponsor for internships.", sponsorship: "unknown", mixed: true}
- {text: "Visa sponsorship is available for permanent roles; we cannot sponsor contractors.", sponsorship: "unknown", mixed: true}
- {text: "We offer visa sponsorship for experienced hires. Graduates must already have the right to work in the UK.", sponsorship: "unknown", mixed: true}
- {text: "Relocation and visa support is provided, but sponsorship is not available for part-time roles.", sponsorship: "unknown", mixed: true}
# --- language requirements
- {text: "Fluent Dutch is required.", sponsorship: "unknown", langs: [nl]}
- {text: "You speak fluent German and English.", sponsorship: "unknown", langs: [de]}
- {text: "Fluency in French is essential.", sponsorship: "unknown", langs: [fr]}
- {text: "German (C1) required.", sponsorship: "unknown", langs: [de]}
- {text: "Dutch language skills are mandatory.", sponsorship: "unknown", langs: [nl]}
- {text: "Native-level Danish is a must.", sponsorship: "unknown", langs: [da]}
- {text: "Fluent English; Dutch is a plus.", sponsorship: "unknown"}
- {text: "Speaking Spanish would be nice to have.", sponsorship: "unknown"}
- {text: "Proficiency in Japanese and Mandarin is required.", sponsorship: "unknown", langs: [ja, zh]}
- {text: "Fluent English and German a plus.", sponsorship: "unknown"}
- {text: "B2 level Polish or higher.", sponsorship: "unknown", langs: [pl]}
- {text: "Professional working proficiency in Swedish.", sponsorship: "unknown", langs: [sv]}
- {text: "We offer visa sponsorship. Fluent Dutch required.", sponsorship: "yes", langs: [nl]}
```

- [ ] **Step 6: Write the failing rules tests** in `tests/test_rules.py`

```python
from collections import Counter
from pathlib import Path

import yaml

from sponsorscope.classify.rules import VERSION, RulesClassifier

CORPUS = yaml.safe_load((Path(__file__).parent / "fixtures" / "labels.yaml").read_text())
CLF = RulesClassifier()


def test_corpus_is_large_enough():
    assert len(CORPUS) >= 60


def test_each_case_mixed_flag_and_languages():
    failures = []
    for case in CORPUS:
        label = CLF.classify(case["text"])
        if label.mixed != case.get("mixed", False) or list(label.languages_required) != case.get("langs", []):
            failures.append((case["text"], label))
    assert failures == []


def test_precision_and_recall_thresholds():
    stats = {c: Counter() for c in ("yes", "no")}
    for case in CORPUS:
        predicted = CLF.classify(case["text"]).sponsorship
        for c in stats:
            if predicted == c and case["sponsorship"] == c:
                stats[c]["tp"] += 1
            elif predicted == c:
                stats[c]["fp"] += 1
            elif case["sponsorship"] == c:
                stats[c]["fn"] += 1

    def precision(c):
        s = stats[c]
        return s["tp"] / (s["tp"] + s["fp"]) if s["tp"] + s["fp"] else 1.0

    def recall(c):
        s = stats[c]
        return s["tp"] / (s["tp"] + s["fn"]) if s["tp"] + s["fn"] else 1.0

    assert precision("no") >= 0.98, stats
    assert precision("yes") >= 0.95, stats
    assert recall("no") >= 0.80, stats
    assert recall("yes") >= 0.80, stats


def test_evidence_is_recorded_and_bounded():
    label = CLF.classify("Great team. " * 20 + "Unfortunately we are unable to offer visa sponsorship. " + "Apply now. " * 20)
    assert label.sponsorship == "no"
    assert label.evidence and all(len(e) <= 160 for e in label.evidence)
    assert any("unable to offer visa sponsorship" in e for e in label.evidence)


def test_mixed_records_both_sides():
    label = CLF.classify("We can sponsor visas for senior engineers but are unable to sponsor for internships.")
    assert label.sponsorship == "unknown" and label.mixed
    # short texts give one de-duplicated context string, so check content, not count
    assert any("We can sponsor" in e for e in label.evidence)
    assert any("unable to sponsor" in e for e in label.evidence)


def test_version_constant():
    assert CLF.version == VERSION == "rules-1"
```

- [ ] **Step 7: Run the tests to verify they fail**

Run: `uv run pytest tests/test_rules.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 8: Implement `sponsorscope/classify/rules.py`**

```python
from __future__ import annotations

import re

from sponsorscope.models import Label

VERSION = "rules-1"  # bump whenever rules change: the next run re-labels every posting
EVIDENCE_WIDTH = 160
NEGATION_WINDOW = 30

_F = re.IGNORECASE

NO_RULES = {
    "unable_to_offer": r"\b(?:unable|not able) to (?:offer|provide|support) (?:any )?(?:visa |work permit )?sponsorship\b",
    "not_offer": r"\b(?:does not|doesn't|do not|don't|will not|won't|can't|cannot|can not) (?:offer|provide|support) (?:visa |work permit )?sponsorship\b",
    "no_sponsorship": r"\bno (?:visa |work permit )?sponsorship\b",
    "right_to_work": r"\bmust (?:already )?(?:have|hold) (?:the |an existing |existing |full |the full )?right to work\b",
    "not_available": r"\b(?:visa )?sponsorship (?:is |will )?not (?:be )?(?:available|offered|provided|possible)\b",
    "cannot_sponsor": r"\b(?:cannot|can ?not|can't|do not|don't|does not|doesn't|will not|won't|unable to|not able to|won't be able to|will not be able to) sponsor\b",
    "without_sponsorship": r"\bwithout (?:the need for |requiring |needing )?(?:visa |employer )?sponsorship\b",
    "not_eligible": r"\bnot eligible for (?:visa |work permit )?sponsorship\b",
    "not_in_position": r"\bnot (?:currently )?in a position to (?:offer|provide) (?:visa )?sponsorship\b",
}
YES_RULES = {
    "sponsorship_available": r"\b(?:visa )?sponsorship (?:is )?(?:available|offered|provided)\b",
    "we_sponsor": r"\bwe (?:can|will|are able to|do|happily|gladly) sponsor\b",
    "offer_sponsorship": r"\b(?:offer|offers|offering|provide|provides|providing|include|includes|including) (?:full )?(?:visa |work permit )sponsorship\b",
    "relocation_visa": r"\b(?:relocation and visa|visa and relocation) (?:support|assistance|package)\b",
    "highly_skilled_migrant": r"\bhighly skilled migrant\b",
    "kennismigrant": r"\bkennismigrant\b",
    "open_to_sponsor": r"\bopen to sponsoring\b",
    "sponsor_visa": r"\bsponsor (?:your |a |the )?(?:work )?(?:visa|work permit|skilled worker visa)\b",
}
_NO = [re.compile(p, _F) for p in NO_RULES.values()]
_YES = [re.compile(p, _F) for p in YES_RULES.values()]
_NEGATION = re.compile(r"\b(?:not|no|unable|cannot|can't|won't|don't|never)\b", _F)

LANGUAGES = {
    "nl": "dutch", "de": "german", "fr": "french", "da": "danish", "fi": "finnish",
    "sv": "swedish", "no": "norwegian", "es": "spanish", "it": "italian", "pt": "portuguese",
    "pl": "polish", "ja": "japanese", "zh": "mandarin|chinese",
}
_LEVEL = r"(?:fluent|fluency|native|proficient|proficiency|c1|c2|b2)"
_LANG_PATTERNS = {
    code: [
        re.compile(rf"\b{_LEVEL}\b[\w \-]{{0,30}}?\b(?:{names})\b", _F),
        re.compile(rf"\b(?:{names})(?: language)?(?: skills)?(?: is| are)? (?:required|essential|a must|mandatory)\b", _F),
        re.compile(rf"\b(?:{names})\s*\(?(?:c1|c2|b2|native|fluent)\b", _F),
    ]
    for code, names in LANGUAGES.items()
}
_OPTIONAL = re.compile(r"\b(?:plus|nice to have|advantage|bonus|preferred|desirable|beneficial)\b", _F)
_CLAUSE_BREAK = re.compile(r"[.!?;,\n]")
_SENTENCE_BREAK = re.compile(r"[.!?;\n]")


def _prepare(text: str) -> str:
    text = text.replace("’", "'").replace("‘", "'")
    return re.sub(r"[ \t\r\f\v]+", " ", text)


def _context(text: str, start: int, end: int) -> str:
    pad = max(0, (EVIDENCE_WIDTH - (end - start)) // 2)
    return text[max(0, start - pad):min(len(text), end + pad)].strip()[:EVIDENCE_WIDTH]


def _negated(text: str, start: int) -> bool:
    window = text[max(0, start - NEGATION_WINDOW):start]
    breaks = list(_SENTENCE_BREAK.finditer(window))
    if breaks:
        window = window[breaks[-1].end():]
    return _NEGATION.search(window) is not None


def _clause(text: str, start: int, end: int) -> str:
    before = list(_CLAUSE_BREAK.finditer(text, 0, start))
    after = _CLAUSE_BREAK.search(text, end)
    return text[before[-1].end() if before else 0:after.start() if after else len(text)]


class RulesClassifier:
    """Deterministic phrase rules. Conflicting signals → unknown + mixed (see spec §7)."""

    version = VERSION

    def classify(self, text: str) -> Label:
        text = _prepare(text)
        no_hits = [m for rx in _NO for m in rx.finditer(text)]
        yes_hits = [m for rx in _YES for m in rx.finditer(text) if not _negated(text, m.start())]
        if yes_hits and no_hits:
            sponsorship, mixed = "unknown", True
        elif no_hits:
            sponsorship, mixed = "no", False
        elif yes_hits:
            sponsorship, mixed = "yes", False
        else:
            sponsorship, mixed = "unknown", False
        evidence = list(dict.fromkeys(_context(text, m.start(), m.end()) for m in no_hits + yes_hits))
        langs = []
        for code, patterns in _LANG_PATTERNS.items():
            for rx in patterns:
                if any(not _OPTIONAL.search(_clause(text, m.start(), m.end())) for m in rx.finditer(text)):
                    langs.append(code)
                    break
        return Label(sponsorship=sponsorship, mixed=mixed, languages_required=tuple(langs),
                     evidence=tuple(evidence))
```

- [ ] **Step 9: Run the tests to verify they pass**

Run: `uv run pytest tests/test_rules.py tests/test_lang_detect.py -v`
Expected: all passed. If a corpus case fails, fix the **rule**, not the corpus. Only change a corpus label if the label itself was wrong, and say why in the commit message.

- [ ] **Step 10: Commit**

```bash
git add sponsorscope/classify tests/fixtures/labels.yaml tests/test_rules.py tests/test_lang_detect.py
git commit -m "feat: English filter and rule-based sponsorship/language classifier with labelled corpus"
```

---

### Task 7: UK register plugin

**Files:**
- Create: `sponsorscope/registers/__init__.py` (empty), `sponsorscope/registers/base.py`, `sponsorscope/registers/gb.py`, `tests/test_register_gb.py`

**Interfaces:**
- Consumes: `Http` (Task 2), `SponsorRecord` (Task 1)
- Produces:
  - `Register` Protocol, with attribute `name: str`, `async latest(http) -> str` (a cheap version signal) and `async fetch(http, version: str) -> list[SponsorRecord]`
  - `RegisterFormatError(Exception)`
  - `UkRegister` with `name = "gb"`
  - `parse_csv(data: bytes) -> list[SponsorRecord]`
  - Constant `CONTENT_API`

- [ ] **Step 1: Write the failing tests** in `tests/test_register_gb.py`

```python
import httpx
import pytest

from sponsorscope.registers.base import RegisterFormatError
from sponsorscope.registers.gb import CONTENT_API, UkRegister, parse_csv

HEADER = "Organisation Name ,Town/City ,County,Type & Rating,Route\n"
ROWS = (
    '"  Acme Widgets Ltd",London,,Worker (A rating),Skilled Worker\n'
    '"Acme Widgets Ltd",London,,Worker (A rating),Global Business Mobility: Senior or Specialist Worker\n'
    '"Beta, Gamma & Sons Limited", ,Kent,Worker (A rating),Skilled Worker\n'
    ',London,,Worker (A rating),Skilled Worker\n'
)
CSV_URL = "https://assets.publishing.service.gov.uk/media/abc/2026-10-13_-_Worker_and_Temporary_Worker.csv"


def test_parse_csv_with_bom_and_padded_headers():
    records = parse_csv(("﻿" + HEADER + ROWS).encode("utf-8"))
    assert [r.legal_name for r in records] == ["Acme Widgets Ltd", "Acme Widgets Ltd", "Beta, Gamma & Sons Limited"]
    first = records[0]
    assert (first.country, first.source, first.evidence, first.city, first.route) == (
        "GB", "gb", "licence", "London", "Skilled Worker")
    assert records[2].city is None


def test_parse_csv_cp1252():
    data = (HEADER + '"Café Rouge Ltd",London,,Worker (A rating),Skilled Worker\n').encode("cp1252")
    assert parse_csv(data)[0].legal_name == "Café Rouge Ltd"


def test_parse_csv_missing_column_is_format_error():
    with pytest.raises(RegisterFormatError):
        parse_csv(b"Name,City\nAcme,London\n")


async def test_latest_picks_csv_attachment(http, respx_mock):
    respx_mock.get(CONTENT_API).mock(return_value=httpx.Response(200, json={"details": {"attachments": [
        {"url": "https://assets.publishing.service.gov.uk/media/x/guidance.pdf"},
        {"url": CSV_URL},
    ]}}))
    assert await UkRegister().latest(http) == CSV_URL


async def test_latest_without_csv_is_format_error(http, respx_mock):
    respx_mock.get(CONTENT_API).mock(return_value=httpx.Response(200, json={"details": {"attachments": []}}))
    with pytest.raises(RegisterFormatError):
        await UkRegister().latest(http)


async def test_fetch_downloads_version_url(http, respx_mock):
    respx_mock.get(CSV_URL).mock(return_value=httpx.Response(200, content=(HEADER + ROWS).encode()))
    records = await UkRegister().fetch(http, CSV_URL)
    assert len(records) == 3


async def test_fetch_http_error_raises(http, respx_mock):
    respx_mock.get(CSV_URL).mock(return_value=httpx.Response(500))
    with pytest.raises(httpx.HTTPStatusError):
        await UkRegister().fetch(http, CSV_URL)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_register_gb.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement `sponsorscope/registers/base.py`**

```python
from __future__ import annotations

from typing import Protocol

from sponsorscope.http import Http
from sponsorscope.models import SponsorRecord


class RegisterFormatError(Exception):
    """The upstream file or page no longer looks like what the parser expects."""


class Register(Protocol):
    name: str  # ISO-2 lowercase, also the `source` column value

    async def latest(self, http: Http) -> str:
        """Cheap version signal (URL, date, etc.). Unchanged version → skip fetch."""
        ...

    async def fetch(self, http: Http, version: str) -> list[SponsorRecord]: ...
```

- [ ] **Step 4: Implement `sponsorscope/registers/gb.py`**

```python
from __future__ import annotations

import csv
import io

from sponsorscope.http import Http
from sponsorscope.models import SponsorRecord
from sponsorscope.registers.base import RegisterFormatError

CONTENT_API = "https://www.gov.uk/api/content/government/publications/register-of-licensed-sponsors-workers"
NAME_COL, CITY_COL, ROUTE_COL = "Organisation Name", "Town/City", "Route"


def _decode(data: bytes) -> str:
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("cp1252")


def _clean(value: str | None) -> str | None:
    value = (value or "").strip()
    return value or None


def parse_csv(data: bytes) -> list[SponsorRecord]:
    reader = csv.DictReader(io.StringIO(_decode(data)))
    if reader.fieldnames is None:
        raise RegisterFormatError("UK register CSV is empty")
    reader.fieldnames = [f.strip() for f in reader.fieldnames]
    missing = {NAME_COL, CITY_COL, ROUTE_COL} - set(reader.fieldnames)
    if missing:
        raise RegisterFormatError(f"UK register CSV missing columns: {sorted(missing)}")
    records = []
    for row in reader:
        name = _clean(row.get(NAME_COL))
        if name is None:
            continue
        records.append(SponsorRecord(country="GB", source="gb", evidence="licence", legal_name=name,
                                     city=_clean(row.get(CITY_COL)), route=_clean(row.get(ROUTE_COL))))
    return records


class UkRegister:
    """Home Office Register of licensed sponsors: workers (OGL v3.0)."""

    name = "gb"

    async def latest(self, http: Http) -> str:
        resp = await http.get(CONTENT_API)
        resp.raise_for_status()
        for attachment in resp.json().get("details", {}).get("attachments", []):
            url = attachment.get("url", "")
            if url.lower().endswith(".csv"):
                return url
        raise RegisterFormatError("no CSV attachment in GOV.UK content API response")

    async def fetch(self, http: Http, version: str) -> list[SponsorRecord]:
        resp = await http.get(version)
        resp.raise_for_status()
        return parse_csv(resp.content)
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/test_register_gb.py -v`
Expected: 7 passed

- [ ] **Step 6: Commit**

```bash
git add sponsorscope/registers tests/test_register_gb.py
git commit -m "feat: UK licensed sponsor register plugin"
```

---

### Task 8: ATS adapters: base, Greenhouse, Lever

**Files:**
- Create: `sponsorscope/ats/__init__.py` (empty), `sponsorscope/ats/base.py`, `sponsorscope/ats/greenhouse.py`, `sponsorscope/ats/lever.py`, `tests/test_ats_greenhouse.py`, `tests/test_ats_lever.py`

**Interfaces:**
- Consumes: `Http` (Task 2), `RawPosting` (Task 1), `html_to_text` (Task 1)
- Produces:
  - `ATS` Protocol, with attribute `name: str` and `async fetch(http, slug) -> list[RawPosting]`. It raises `BoardNotFound` when the board doesn't exist; any other exception means a failed fetch.
  - `BoardNotFound(Exception)`
  - `infer_remote(text: str | None) -> str | None`
  - Classes `Greenhouse` (`name="greenhouse"`) and `Lever` (`name="lever"`)

- [ ] **Step 1: Write the failing Greenhouse tests** in `tests/test_ats_greenhouse.py`

```python
import html

import httpx
import pytest

from sponsorscope.ats.base import BoardNotFound, infer_remote
from sponsorscope.ats.greenhouse import Greenhouse


def job(job_id, internal_id, content, location="London, UK"):
    return {"id": job_id, "internal_job_id": internal_id, "title": " Backend Engineer ",
            "absolute_url": f"https://boards.greenhouse.io/acme/jobs/{job_id}",
            "location": {"name": location}, "content": content,
            "updated_at": "2026-10-02T10:00:00-04:00", "first_published": "2026-09-30T10:00:00-04:00"}


def mock_board(respx_mock, slug, response):
    return respx_mock.get(host="boards-api.greenhouse.io", path=f"/v1/boards/{slug}/jobs").mock(return_value=response)


async def test_parses_escaped_html_and_dedupes_internal_job(http, respx_mock):
    escaped = html.escape("<p>We <strong>offer</strong> visa sponsorship &amp; relocation.</p>")
    route = mock_board(respx_mock, "acme", httpx.Response(200, json={"jobs": [
        job(1, 100, escaped), job(2, 100, escaped), job(3, 101, None, location="Remote - US"),
    ]}))
    postings = await Greenhouse().fetch(http, "acme")
    assert route.calls.last.request.url.params["content"] == "true"
    assert [p.id for p in postings] == ["greenhouse:acme:1", "greenhouse:acme:3"]
    first = postings[0]
    assert first.title == "Backend Engineer"
    assert first.description == "We offer visa sponsorship & relocation."
    assert (first.location_raw, first.country, first.remote, first.posted_at) == ("London, UK", None, None, "2026-09-30")
    assert postings[1].description == "" and postings[1].remote == "remote"


async def test_missing_board_raises_board_not_found(http, respx_mock):
    mock_board(respx_mock, "nope", httpx.Response(404, json={"status": 404, "error": "Job not found"}))
    with pytest.raises(BoardNotFound):
        await Greenhouse().fetch(http, "nope")


async def test_server_error_raises_http_error(http, respx_mock):
    mock_board(respx_mock, "acme", httpx.Response(500))
    with pytest.raises(httpx.HTTPStatusError):
        await Greenhouse().fetch(http, "acme")


def test_infer_remote():
    assert infer_remote("Remote (UK)") == "remote"
    assert infer_remote("London - Hybrid") == "hybrid"
    assert infer_remote("London") is None
    assert infer_remote(None) is None
```

- [ ] **Step 2: Write the failing Lever tests** in `tests/test_ats_lever.py`

```python
import httpx
import pytest

from sponsorscope.ats.base import BoardNotFound
from sponsorscope.ats.lever import Lever

POSTING = {
    "id": "abc-123", "text": "Data Engineer", "hostedUrl": "https://jobs.lever.co/acme/abc-123",
    "categories": {"location": "Amsterdam", "team": "Data"}, "country": "nl", "workplaceType": "hybrid",
    "createdAt": 1727690400000, "descriptionPlain": "Join our data team.",
    "lists": [{"text": "Requirements", "content": "<li>Fluent Dutch</li><li>Python</li>"}],
    "additionalPlain": "We offer visa sponsorship.",
}


def mock_host(respx_mock, host, slug, response):
    return respx_mock.get(host=host, path=f"/v0/postings/{slug}").mock(return_value=response)


async def test_parses_posting(http, respx_mock):
    route = mock_host(respx_mock, "api.lever.co", "acme", httpx.Response(200, json=[POSTING]))
    [p] = await Lever().fetch(http, "acme")
    assert route.calls.last.request.url.params["mode"] == "json"
    assert p.id == "lever:acme:abc-123"
    assert (p.title, p.country, p.remote, p.location_raw, p.posted_at) == (
        "Data Engineer", "NL", "hybrid", "Amsterdam", "2024-09-30")
    assert "Join our data team." in p.description
    assert "Requirements" in p.description and "Fluent Dutch" in p.description
    assert p.description.endswith("We offer visa sponsorship.")


async def test_falls_back_to_eu_host(http, respx_mock):
    mock_host(respx_mock, "api.lever.co", "euco", httpx.Response(404, json={"ok": False}))
    mock_host(respx_mock, "api.eu.lever.co", "euco", httpx.Response(200, json=[POSTING]))
    assert len(await Lever().fetch(http, "euco")) == 1


async def test_missing_on_both_hosts_raises_board_not_found(http, respx_mock):
    mock_host(respx_mock, "api.lever.co", "nope", httpx.Response(404))
    mock_host(respx_mock, "api.eu.lever.co", "nope", httpx.Response(404))
    with pytest.raises(BoardNotFound):
        await Lever().fetch(http, "nope")


async def test_null_country_and_unspecified_workplace(http, respx_mock):
    posting = {**POSTING, "country": None, "workplaceType": "unspecified", "categories": {"location": "Remote"}}
    mock_host(respx_mock, "api.lever.co", "acme", httpx.Response(200, json=[posting]))
    [p] = await Lever().fetch(http, "acme")
    assert p.country is None and p.remote == "remote"
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `uv run pytest tests/test_ats_greenhouse.py tests/test_ats_lever.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 4: Implement `sponsorscope/ats/base.py`**

```python
from __future__ import annotations

from typing import Protocol

from sponsorscope.http import Http
from sponsorscope.models import RawPosting


class BoardNotFound(Exception):
    """The ATS says this board/slug does not exist."""


class ATS(Protocol):
    name: str

    async def fetch(self, http: Http, slug: str) -> list[RawPosting]:
        """All current postings on a board. Raises BoardNotFound if the board doesn't exist."""
        ...


def infer_remote(text: str | None) -> str | None:
    low = (text or "").lower()
    if "hybrid" in low:
        return "hybrid"
    if "remote" in low:
        return "remote"
    return None
```

- [ ] **Step 5: Implement `sponsorscope/ats/greenhouse.py`**

```python
from __future__ import annotations

import html

from sponsorscope.ats.base import BoardNotFound, infer_remote
from sponsorscope.http import Http
from sponsorscope.models import RawPosting
from sponsorscope.text import html_to_text

BASE = "https://boards-api.greenhouse.io/v1/boards"


class Greenhouse:
    name = "greenhouse"

    async def fetch(self, http: Http, slug: str) -> list[RawPosting]:
        resp = await http.get(f"{BASE}/{slug}/jobs", params={"content": "true"})
        if resp.status_code == 404:
            raise BoardNotFound(f"greenhouse:{slug}")
        resp.raise_for_status()
        seen: set[object] = set()
        postings = []
        for job in resp.json().get("jobs", []):
            key = job.get("internal_job_id") or job["id"]  # one job can have several postings
            if key in seen:
                continue
            seen.add(key)
            location = (job.get("location") or {}).get("name")
            published = job.get("first_published") or job.get("updated_at")
            postings.append(RawPosting(
                ats=self.name, slug=slug, job_id=str(job["id"]),
                title=(job.get("title") or "").strip(), url=job.get("absolute_url") or "",
                description=html_to_text(html.unescape(job.get("content") or "")),
                location_raw=location, country=None, remote=infer_remote(location),
                posted_at=published[:10] if published else None,
            ))
        return postings
```

- [ ] **Step 6: Implement `sponsorscope/ats/lever.py`**

```python
from __future__ import annotations

from datetime import datetime, timezone

from sponsorscope.ats.base import BoardNotFound, infer_remote
from sponsorscope.http import Http
from sponsorscope.models import RawPosting
from sponsorscope.text import html_to_text

HOSTS = ("https://api.lever.co", "https://api.eu.lever.co")
WORKPLACE = {"remote": "remote", "hybrid": "hybrid", "on-site": "onsite", "onsite": "onsite"}


class Lever:
    """Lever postings API. Slugs are case-sensitive; EU accounts live on a separate host."""

    name = "lever"

    async def fetch(self, http: Http, slug: str) -> list[RawPosting]:
        for host in HOSTS:
            resp = await http.get(f"{host}/v0/postings/{slug}", params={"mode": "json"})
            if resp.status_code == 404:
                continue
            resp.raise_for_status()
            return [self._parse(slug, p) for p in resp.json()]
        raise BoardNotFound(f"lever:{slug}")

    def _parse(self, slug: str, p: dict) -> RawPosting:
        location = (p.get("categories") or {}).get("location")
        parts = [p.get("descriptionPlain") or ""]
        for section in p.get("lists") or []:
            parts += [section.get("text") or "", html_to_text(section.get("content"))]
        parts.append(p.get("additionalPlain") or "")
        created = p.get("createdAt")
        country = p.get("country")
        return RawPosting(
            ats=self.name, slug=slug, job_id=str(p["id"]),
            title=(p.get("text") or "").strip(), url=p.get("hostedUrl") or "",
            description="\n".join(part for part in parts if part).strip(),
            location_raw=location, country=country.upper() if country else None,
            remote=WORKPLACE.get((p.get("workplaceType") or "").lower()) or infer_remote(location),
            posted_at=datetime.fromtimestamp(created / 1000, tz=timezone.utc).date().isoformat() if created else None,
        )
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `uv run pytest tests/test_ats_greenhouse.py tests/test_ats_lever.py -v`
Expected: 8 passed

- [ ] **Step 8: Commit**

```bash
git add sponsorscope/ats tests/test_ats_greenhouse.py tests/test_ats_lever.py
git commit -m "feat: Greenhouse and Lever ATS adapters"
```

---

### Task 9: Run report

**Files:**
- Create: `sponsorscope/report.py`, `tests/test_report.py`

**Interfaces:**
- Produces:
  - `RunReport(started_at: str)`, with fields `finished_at: str | None`, `sources: dict[str, dict]` and `ats: dict[str, dict]`
  - `.source(name, status, **info)`, where status is one of `"ok" | "unchanged" | "failed" | "blocked"`
  - `.board_summary(ats, **info)`
  - `.warnings() -> list[str]`
  - `.to_dict() -> dict`

- [ ] **Step 1: Write the failing tests** in `tests/test_report.py`

```python
from sponsorscope.report import RunReport


def test_warnings_cover_failed_sources_and_ats_problems():
    r = RunReport(started_at="t0")
    r.source("gb", "ok", rows=10)
    r.source("nl", "failed", error="HTTP 500")
    r.source("fi", "blocked", error="403")
    r.board_summary("greenhouse", boards=10, ok=9, not_found=0, failed=1, postings=50, outage=False, errors=["x: boom"])
    r.board_summary("lever", boards=5, ok=5, not_found=0, failed=0, postings=20, outage=False, errors=[])
    warnings = r.warnings()
    assert any(w.startswith("nl: failed") for w in warnings)
    assert any(w.startswith("fi: blocked") for w in warnings)
    assert any("greenhouse" in w and "1 of 10" in w for w in warnings)
    assert not any(w.startswith("gb") or "lever" in w for w in warnings)


def test_outage_warning():
    r = RunReport(started_at="t0")
    r.board_summary("lever", boards=4, ok=1, not_found=0, failed=3, postings=2, outage=True, errors=[])
    assert any("outage" in w for w in r.warnings())


def test_to_dict_round_trips():
    r = RunReport(started_at="t0")
    r.source("gb", "unchanged", version="v1")
    d = r.to_dict()
    assert d == {"started_at": "t0", "finished_at": None,
                 "sources": {"gb": {"status": "unchanged", "version": "v1"}}, "ats": {}}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_report.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement `sponsorscope/report.py`**

```python
from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass
class RunReport:
    started_at: str
    finished_at: str | None = None
    sources: dict[str, dict] = field(default_factory=dict)
    ats: dict[str, dict] = field(default_factory=dict)

    def source(self, name: str, status: str, **info) -> None:
        self.sources[name] = {"status": status, **info}

    def board_summary(self, ats: str, **info) -> None:
        self.ats[ats] = info

    def warnings(self) -> list[str]:
        out = []
        for name, info in self.sources.items():
            if info["status"] in ("failed", "blocked"):
                out.append(f"{name}: {info['status']} ({info.get('error', '')})")
        for ats, info in self.ats.items():
            if info.get("outage"):
                out.append(f"{ats}: outage, {info['failed'] + info['not_found']} of {info['boards']} boards failed; nothing deactivated")
            elif info.get("failed"):
                out.append(f"{ats}: {info['failed']} of {info['boards']} boards failed")
        return out

    def to_dict(self) -> dict:
        return asdict(self)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_report.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add sponsorscope/report.py tests/test_report.py
git commit -m "feat: run report with per-source status and warnings"
```

---

### Task 10: Export: per-country shards and index

**Files:**
- Create: `sponsorscope/export/__init__.py` (empty), `sponsorscope/export/shards.py`, `tests/test_export.py`

**Interfaces:**
- Consumes: the `store.db` functions (Task 4)
- Produces:
  - `export_site(conn, site_dir: Path, classifier_version: str, generated_at: str, run_report: dict | None = None) -> dict[str, int]`, which returns the row count per country code
  - It writes:
    - `site/data/{cc}.json.gz`, where `cc` is the lowercase country code, or `xx` for unknown
    - `site/data/index.json`, with keys `generated_at, fields, countries, companies, ats, sources`
    - `site/data/last_run.json`, only when `run_report` is given
  - `badge_text(source, evidence, country, filings, period) -> str`
  - Constants `FIELDS`, `UNKNOWN_COUNTRY = "XX"`, `SHARD_WARN_BYTES`

- [ ] **Step 1: Write the failing tests** in `tests/test_export.py`

```python
import gzip
import json

import pytest

from sponsorscope.export.shards import FIELDS, badge_text, export_site
from sponsorscope.models import Label, RawPosting, SponsorRecord
from sponsorscope.store import db

T1 = "2026-10-13T03:00:00+00:00"


@pytest.fixture
def conn(tmp_path):
    c = db.connect(tmp_path / "t.db")
    yield c
    c.close()


def add_posting(conn, company_id, job_id, country, lang="en", label=Label("yes", False, (), ("We offer visa sponsorship",))):
    p = RawPosting(ats="greenhouse", slug="acme", job_id=job_id, title=f"Job {job_id}", url=f"https://x/{job_id}",
                   description="d", location_raw="London", country=None, remote=None, posted_at="2026-10-01")
    db.upsert_posting(conn, p, company_id=company_id, country=country, lang=lang, content_hash=f"h{job_id}", now=T1)
    if label:
        db.save_label(conn, p.id, f"h{job_id}", "rules-1", label)


def read_shard(site, cc):
    return json.loads(gzip.decompress((site / "data" / f"{cc}.json.gz").read_bytes()))


def test_empty_db_exports_valid_empty_index(conn, tmp_path):
    counts = export_site(conn, tmp_path / "site", "rules-1", T1)
    index = json.loads((tmp_path / "site" / "data" / "index.json").read_text())
    assert counts == {}
    assert index["countries"] == {} and index["fields"] == FIELDS and index["companies"] == []


def test_shards_badges_and_filters(conn, tmp_path):
    acme = db.get_or_create_company(conn, "Acme Widgets")
    db.upsert_sponsors(conn, "gb", [SponsorRecord("GB", "gb", "licence", "Acme Widgets Ltd")], "v1", T1)
    sponsor_id = conn.execute("SELECT id FROM sponsors").fetchone()[0]
    db.replace_matches(conn, [(sponsor_id, acme, "exact", 100.0)])
    add_posting(conn, acme, "1", "GB")
    add_posting(conn, acme, "2", "NL")  # matched company, but no NL sponsor → no badge
    add_posting(conn, acme, "3", None)  # unknown location → xx shard, no badge
    add_posting(conn, acme, "4", "GB", lang="other")  # non-English → excluded
    add_posting(conn, acme, "5", "GB", label=None)  # no label yet → exported as unknown
    conn.execute("UPDATE postings SET active = 0 WHERE id = 'greenhouse:acme:2'")
    add_posting(conn, acme, "6", "NL")

    site = tmp_path / "site"
    (site / "data").mkdir(parents=True)
    (site / "data" / "zz.json.gz").write_bytes(b"stale")
    counts = export_site(conn, site, "rules-1", T1, run_report={"sources": {"gb": {"status": "ok"}}})

    assert counts == {"GB": 2, "NL": 1, "XX": 1}
    assert not (site / "data" / "zz.json.gz").exists()
    gb = {r[0]: dict(zip(FIELDS, r)) for r in read_shard(site, "gb")}
    assert gb["greenhouse:acme:1"]["badges"] == [["licence", "Licensed sponsor (UK)"]]
    assert gb["greenhouse:acme:1"]["sponsorship"] == "yes"
    assert gb["greenhouse:acme:1"]["evidence"] == ["We offer visa sponsorship"]
    assert gb["greenhouse:acme:5"]["sponsorship"] == "unknown"
    nl = [dict(zip(FIELDS, r)) for r in read_shard(site, "nl")]
    assert nl[0]["badges"] == []
    xx = [dict(zip(FIELDS, r)) for r in read_shard(site, "xx")]
    assert xx[0]["country"] is None and xx[0]["badges"] == []

    index = json.loads((site / "data" / "index.json").read_text())
    assert index["companies"] == ["Acme Widgets"] and index["ats"] == ["greenhouse"]
    assert index["sources"]["gb"]["status"] == "ok" and index["sources"]["gb"]["data_as_of"] == T1
    assert json.loads((site / "data" / "last_run.json").read_text())["sources"]["gb"]["status"] == "ok"


def test_retired_sponsor_gives_no_badge(conn, tmp_path):
    acme = db.get_or_create_company(conn, "Acme Widgets")
    db.upsert_sponsors(conn, "gb", [SponsorRecord("GB", "gb", "licence", "Acme Widgets Ltd")], "v1", T1)
    sponsor_id = conn.execute("SELECT id FROM sponsors").fetchone()[0]
    db.replace_matches(conn, [(sponsor_id, acme, "exact", 100.0)])
    db.upsert_sponsors(conn, "gb", [SponsorRecord("GB", "gb", "licence", "Other Co Ltd")], "v2", "2026-10-14T03:00:00+00:00")
    add_posting(conn, acme, "1", "GB")
    export_site(conn, tmp_path / "site", "rules-1", T1)
    assert dict(zip(FIELDS, read_shard(tmp_path / "site", "gb")[0]))["badges"] == []


def test_badge_text():
    assert badge_text("gb", "licence", "GB", None, None) == "Licensed sponsor (UK)"
    assert badge_text("us", "history", "US", 37, "FY2026") == "Filed 37 certified H-1B LCAs (FY2026)"
    assert badge_text("ca", "history", "CA", 12, "2026 Q1") == "12 positive LMIAs (2026 Q1)"
    assert badge_text("ie", "history", "IE", 8, "2026") == "8 employment permits issued (2026)"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_export.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement `sponsorscope/export/shards.py`**

```python
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
SELECT m.company_id, s.source, s.evidence, s.country, SUM(s.filings) AS filings, MAX(s.period) AS period
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
        out[r["company_id"]][r["country"]].append(
            [r["evidence"], badge_text(r["source"], r["evidence"], r["country"], r["filings"], r["period"])])
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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_export.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add sponsorscope/export tests/test_export.py
git commit -m "feat: export per-country gzipped shards and index for the static page"
```

---

### Task 11: Pipeline orchestration and CLI

**Files:**
- Create: `sponsorscope/pipeline.py`, `sponsorscope/cli.py`, `seeds/manual.yaml`, `overrides.yaml`, `tests/test_pipeline.py`, `tests/test_cli.py`

**Interfaces:**
- Consumes: everything above
- Produces:
  - `seed_boards(conn, path: Path, now: str) -> int`
  - `async run_registers(conn, http, registers, report, now) -> None`
  - `run_match(conn, overrides: Overrides) -> int` (returns the number of match rows)
  - `async run_crawl(conn, http, adapters: dict[str, ATS], classifier, report, now, cities=None, detect=is_english) -> None`
  - `async nightly(conn, http, *, registers, adapters, classifier, seeds_path, overrides, site_dir, now, cities=None) -> RunReport`
  - Constants `SHRINK_GUARD = 0.8`, `OUTAGE_RATIO = 0.5` and `OUTAGE_MIN_BOARDS = 4`
  - CLI `sponsorscope` with commands `seed | registers | match | crawl | export | nightly | check-db`

- [ ] **Step 1: Write the failing pipeline tests** in `tests/test_pipeline.py`

```python
import gzip
import html
import json
from contextlib import contextmanager

import httpx
import pytest
import respx

from sponsorscope import pipeline
from sponsorscope.ats.greenhouse import Greenhouse
from sponsorscope.classify.rules import RulesClassifier
from sponsorscope.matching.names import Overrides
from sponsorscope.registers.gb import CONTENT_API, UkRegister
from sponsorscope.store import db

T = ["2026-10-13T03:00:00+00:00", "2026-10-14T03:00:00+00:00", "2026-10-15T03:00:00+00:00"]
CSV_V1 = "https://assets.publishing.service.gov.uk/media/a1/register-2026-10-12.csv"
CSV_V2 = "https://assets.publishing.service.gov.uk/media/b2/register-2026-10-13.csv"
SPONSORS = ["Acme Widgets Ltd"] + [f"Filler Company {i} Ltd" for i in range(9)]
LONG = " We build reliable widgets for customers across Europe and the wider world, and we care deeply about quality."
CITIES = {"london": "GB", "amsterdam": "NL"}


def uk_csv(names):
    rows = "".join(f'"{n}",London,,Worker (A rating),Skilled Worker\n' for n in names)
    return ("Organisation Name,Town/City,County,Type & Rating,Route\n" + rows).encode()


def gh_job(job_id, title, location, text):
    return {"id": job_id, "internal_job_id": job_id, "title": title,
            "absolute_url": f"https://boards.greenhouse.io/acme/jobs/{job_id}", "location": {"name": location},
            "content": html.escape(f"<p>{text}</p>"), "first_published": "2026-09-30T10:00:00Z"}


JOB_YES = gh_job(1, "Backend Engineer", "London, UK", "We offer visa sponsorship for this role." + LONG)
JOB_NO = gh_job(2, "Data Analyst", "London, UK", "Candidates must have the right to work in the UK." + LONG)
JOB_NL = gh_job(3, "Ingenieur", "Amsterdam, Netherlands",
                "Wij zoeken een ervaren ingenieur die graag samenwerkt met onze klanten in Nederland en daarbuiten. Je werkt in een klein team.")


def ok(jobs):
    return httpx.Response(200, json={"jobs": jobs})


@contextmanager
def sources(csv_url=CSV_V1, csv_bytes=None, boards=None, api_status=200):
    with respx.mock(assert_all_called=False) as m:
        if api_status == 200:
            m.get(CONTENT_API).mock(return_value=httpx.Response(200, json={"details": {"attachments": [{"url": csv_url}]}}))
        else:
            m.get(CONTENT_API).mock(return_value=httpx.Response(api_status))
        csv_route = m.get(csv_url).mock(return_value=httpx.Response(200, content=csv_bytes or uk_csv(SPONSORS)))
        for slug, response in (boards or {"acme": ok([JOB_YES, JOB_NO, JOB_NL])}).items():
            m.get(host="boards-api.greenhouse.io", path=f"/v1/boards/{slug}/jobs").mock(return_value=response)
        yield csv_route


@pytest.fixture
def conn(tmp_path):
    c = db.connect(tmp_path / "t.db")
    yield c
    c.close()


@pytest.fixture
def seeds(tmp_path):
    path = tmp_path / "seeds.yaml"
    path.write_text("- {ats: greenhouse, slug: acme, name: Acme Widgets}\n")
    return path


async def run(conn, http, tmp_path, seeds, now):
    return await pipeline.nightly(conn, http, registers=[UkRegister()], adapters={"greenhouse": Greenhouse()},
                                  classifier=RulesClassifier(), seeds_path=seeds, overrides=Overrides(),
                                  site_dir=tmp_path / "site", now=now, cities=CITIES)


def shard(tmp_path, cc):
    return json.loads(gzip.decompress((tmp_path / "site" / "data" / f"{cc}.json.gz").read_bytes()))


def active_ids(conn):
    return {r[0] for r in conn.execute("SELECT id FROM postings WHERE active = 1")}


async def test_end_to_end_exports_badged_postings(conn, http, tmp_path, seeds):
    with sources():
        report = await run(conn, http, tmp_path, seeds, T[0])
    rows = {r[0]: r for r in shard(tmp_path, "gb")}
    assert set(rows) == {"greenhouse:acme:1", "greenhouse:acme:2"}  # Dutch posting dropped
    yes, no = rows["greenhouse:acme:1"], rows["greenhouse:acme:2"]
    assert yes[8] == "yes" and yes[12] == [["licence", "Licensed sponsor (UK)"]]
    assert no[8] == "no"
    assert report.sources["gb"]["status"] == "ok" and report.sources["gb"]["rows"] == 10
    assert report.ats["greenhouse"]["ok"] == 1
    assert json.loads((tmp_path / "site" / "data" / "last_run.json").read_text())["sources"]["gb"]["status"] == "ok"


async def test_unchanged_version_skips_download(conn, http, tmp_path, seeds):
    with sources():
        await run(conn, http, tmp_path, seeds, T[0])
    with sources() as csv_route:
        report = await run(conn, http, tmp_path, seeds, T[1])
    assert csv_route.call_count == 0 and report.sources["gb"]["status"] == "unchanged"


async def test_failed_register_keeps_rows_and_badges(conn, http, tmp_path, seeds):
    with sources():
        await run(conn, http, tmp_path, seeds, T[0])
    with sources(api_status=500):
        report = await run(conn, http, tmp_path, seeds, T[1])
    assert report.sources["gb"]["status"] == "failed"
    assert db.active_sponsor_count(conn, "gb") == 10
    assert {r[0]: r for r in shard(tmp_path, "gb")}["greenhouse:acme:1"][12] != []


async def test_shrink_guard_rejects_truncated_register(conn, http, tmp_path, seeds):
    with sources():
        await run(conn, http, tmp_path, seeds, T[0])
    with sources(csv_url=CSV_V2, csv_bytes=uk_csv(SPONSORS[:1])):
        report = await run(conn, http, tmp_path, seeds, T[1])
    assert report.sources["gb"]["status"] == "failed" and "shrink" in report.sources["gb"]["error"]
    assert db.active_sponsor_count(conn, "gb") == 10 and db.get_source_version(conn, "gb") == CSV_V1


async def test_failed_board_does_not_deactivate(conn, http, tmp_path, seeds):
    with sources():
        await run(conn, http, tmp_path, seeds, T[0])
    before = active_ids(conn)
    with sources(boards={"acme": httpx.Response(500)}):
        report = await run(conn, http, tmp_path, seeds, T[1])
    assert active_ids(conn) == before and report.ats["greenhouse"]["failed"] == 1


async def test_missing_posting_is_deactivated(conn, http, tmp_path, seeds):
    with sources():
        await run(conn, http, tmp_path, seeds, T[0])
    with sources(boards={"acme": ok([JOB_YES, JOB_NL])}):
        await run(conn, http, tmp_path, seeds, T[1])
    assert "greenhouse:acme:2" not in active_ids(conn)


async def test_ats_outage_blocks_deactivation(conn, http, tmp_path):
    seeds = tmp_path / "seeds.yaml"
    seeds.write_text("".join(f"- {{ats: greenhouse, slug: {s}, name: {n}}}\n" for s, n in
                             [("acme", "Acme Widgets"), ("b1", "Beta One"), ("b2", "Beta Two"), ("b3", "Beta Three")]))
    healthy = {"acme": ok([JOB_YES, JOB_NO]), "b1": ok([]), "b2": ok([]), "b3": ok([])}
    with sources(boards=healthy):
        await run(conn, http, tmp_path, seeds, T[0])
    broken = {"acme": ok([JOB_YES]), "b1": httpx.Response(500), "b2": httpx.Response(500), "b3": httpx.Response(500)}
    with sources(boards=broken):
        report = await run(conn, http, tmp_path, seeds, T[1])
    assert report.ats["greenhouse"]["outage"] is True
    assert "greenhouse:acme:2" in active_ids(conn)


async def test_board_gone_after_three_404s(conn, http, tmp_path, seeds):
    for now in T:
        with sources(boards={"acme": httpx.Response(404)}):
            await run(conn, http, tmp_path, seeds, now)
    assert db.boards_to_crawl(conn) == []


async def test_rerun_does_not_relabel(conn, http, tmp_path, seeds):
    with sources():
        await run(conn, http, tmp_path, seeds, T[0])
    labels_before = conn.execute("SELECT COUNT(*) FROM labels").fetchone()[0]
    with sources():
        await run(conn, http, tmp_path, seeds, T[1])
    assert conn.execute("SELECT COUNT(*) FROM labels").fetchone()[0] == labels_before == 2


def test_run_match_respects_overrides(conn):
    from sponsorscope.models import SponsorRecord

    db.upsert_sponsors(conn, "gb", [SponsorRecord("GB", "gb", "licence", n) for n in
                                    ("Apple Ltd", "Stripe Payments UK Ltd")], "v1", T[0])
    apple = db.get_or_create_company(conn, "Apple")
    stripe = db.get_or_create_company(conn, "Stripe")
    assert pipeline.run_match(conn, Overrides()) == 1  # apple ↔ "apple" exact; stripe unmatched
    o = Overrides(force={("stripe", "stripe payments")}, forbid={("apple", "apple")})
    assert pipeline.run_match(conn, o) == 1
    pairs = {(r["company_id"], r["method"]) for r in conn.execute("SELECT * FROM sponsor_matches")}
    assert pairs == {(stripe, "manual")} and apple not in {c for c, _ in pairs}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_pipeline.py -v`
Expected: FAIL with `ImportError: cannot import name 'pipeline'`

- [ ] **Step 3: Implement `sponsorscope/pipeline.py`**

```python
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
from sponsorscope.registers.base import Register
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
            outcomes[outcome] += 1
            if outcome == "ok":
                seen[board["slug"]] = {p.id for p in result}
                for p in result:
                    _process_posting(conn, p, board["company_id"], classifier, now, cities, detect)
                postings += len(result)
                conn.commit()
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
```

- [ ] **Step 4: Run the pipeline tests to verify they pass**

Run: `uv run pytest tests/test_pipeline.py -v`
Expected: 10 passed

- [ ] **Step 5: Write the failing CLI tests** in `tests/test_cli.py`

```python
import json

from typer.testing import CliRunner

from sponsorscope.cli import app

runner = CliRunner()


def test_check_db_on_fresh_db(tmp_path):
    result = runner.invoke(app, ["check-db", "--db", str(tmp_path / "x.db")])
    assert result.exit_code == 0 and "ok" in result.output


def test_export_on_empty_db_writes_empty_index(tmp_path):
    result = runner.invoke(app, ["export", "--db", str(tmp_path / "x.db"), "--site", str(tmp_path / "site")])
    assert result.exit_code == 0, result.output
    index = json.loads((tmp_path / "site" / "data" / "index.json").read_text())
    assert index["countries"] == {}


def test_seed_loads_boards(tmp_path):
    seeds = tmp_path / "s.yaml"
    seeds.write_text("- {ats: lever, slug: acme, name: Acme}\n")
    result = runner.invoke(app, ["seed", "--db", str(tmp_path / "x.db"), "--seeds", str(seeds)])
    assert result.exit_code == 0 and "1 boards" in result.output
```

- [ ] **Step 6: Implement `sponsorscope/cli.py`**

```python
from __future__ import annotations

import asyncio
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated

import typer

from sponsorscope import pipeline
from sponsorscope.ats.greenhouse import Greenhouse
from sponsorscope.ats.lever import Lever
from sponsorscope.classify.rules import RulesClassifier
from sponsorscope.export.shards import export_site
from sponsorscope.http import Http
from sponsorscope.matching.names import Overrides
from sponsorscope.registers.gb import UkRegister
from sponsorscope.report import RunReport
from sponsorscope.store.db import connect

app = typer.Typer(no_args_is_help=True, add_completion=False, help="Visa-sponsorship job tracker pipeline.")

Db = Annotated[Path, typer.Option("--db", help="SQLite database path")]
Site = Annotated[Path, typer.Option("--site", help="Static site directory")]
Seeds = Annotated[Path, typer.Option("--seeds", help="Seed boards YAML")]
OverridesPath = Annotated[Path, typer.Option("--overrides", help="Match overrides YAML")]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _registers():
    return [UkRegister()]


def _adapters():
    return {"greenhouse": Greenhouse(), "lever": Lever()}


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
def registers_cmd(db: Db = Path("sponsorscope.db")) -> None:
    """Refresh every sponsor register whose version changed."""
    conn, report = connect(db), RunReport(started_at=_now())
    _run_with_http(lambda http: pipeline.run_registers(conn, http, _registers(), report, report.started_at))
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
```

- [ ] **Step 7: Write `overrides.yaml` and `seeds/manual.yaml`**

`overrides.yaml`:

```yaml
# Manual overrides for matching ATS companies to register entries.
# Names are normalised the same way as the matcher (suffixes like Ltd/B.V. stripped).
# match:  force a link the matcher misses (e.g. trading name ≠ legal name)
# forbid: block a wrong automatic link (e.g. a small "Apple Ltd" ≠ Apple Inc)
match: []
#  - {company: Deliveroo, sponsor: Roofoods Ltd}
forbid: []
#  - {company: Apple, sponsor: Apple Ltd}
```

`seeds/manual.yaml`:

```yaml
# Known job boards to crawl until discovery (Plan 3) exists.
# Lever slugs are case-sensitive.
- {ats: greenhouse, slug: airbnb, name: Airbnb}
- {ats: greenhouse, slug: stripe, name: Stripe}
- {ats: greenhouse, slug: gitlab, name: GitLab}
- {ats: greenhouse, slug: monzo, name: Monzo Bank}
- {ats: greenhouse, slug: deliveroo, name: Deliveroo}
- {ats: lever, slug: palantir, name: Palantir Technologies}
- {ats: lever, slug: spotify, name: Spotify}
```

- [ ] **Step 8: Verify the seed slugs against the live APIs and drop any that 404**

Run:

```bash
for s in airbnb stripe gitlab monzo deliveroo; do printf "greenhouse %s " $s; curl -s -o /dev/null -w "%{http_code}\n" "https://boards-api.greenhouse.io/v1/boards/$s/jobs"; done
for s in palantir spotify; do printf "lever %s " $s; curl -s -o /dev/null -w "%{http_code}\n" "https://api.lever.co/v0/postings/$s?mode=json"; done
```

Expected: `200` for each kept entry. Delete every line in `seeds/manual.yaml` whose slug didn't return `200`. Keep at least one entry per ATS: `airbnb` and `palantir` were verified on 2026-10-13.

- [ ] **Step 9: Run all the tests**

Run: `uv run pytest -v`
Expected: all passed

- [ ] **Step 10: Commit**

```bash
git add sponsorscope/pipeline.py sponsorscope/cli.py seeds overrides.yaml tests/test_pipeline.py tests/test_cli.py
git commit -m "feat: nightly pipeline orchestration with failure isolation, and CLI"
```

---

### Task 12: Static page

**Files:**
- Create: `site/index.html`, `site/style.css`, `site/filters.js`, `site/app.js`, `site/filters.test.js`, `package.json`

**Interfaces:**
- Consumes: `site/data/index.json` (keys `generated_at, fields, countries, companies, ats, sources`) and `site/data/{cc}.json.gz` row arrays in `FIELDS` order (Task 10)
- Produces (in `filters.js`, all pure):
  - `DEFAULT_STATE`, `LANG_LABELS`, `SOURCE_LABELS`
  - `parseState(search)`, `serializeState(state)`
  - `toObjects(fields, rows)`
  - `filterRows(rows, state, now)`
  - `shardsFor(state, index)`
  - `safeUrl(url)`
  - `sourceLine(name, info)`

- [ ] **Step 1: Write `package.json`**

```json
{
  "private": true,
  "type": "module",
  "scripts": { "test": "node --test site/" }
}
```

- [ ] **Step 2: Write the failing tests** in `site/filters.test.js`

```js
import { test } from "node:test";
import assert from "node:assert/strict";
import {
  DEFAULT_STATE, filterRows, parseState, safeUrl, serializeState, shardsFor, sourceLine, toObjects,
} from "./filters.js";

const FIELDS = ["id", "title", "company", "url", "country", "remote", "posted_at", "first_seen",
  "sponsorship", "mixed", "langs", "evidence", "badges", "ats"];
const ROWS = toObjects(FIELDS, [
  ["greenhouse:a:1", "Backend Engineer", "Acme", "https://x/1", "GB", "remote", "2026-10-10", "2026-10-10T03:00:00+00:00", "yes", false, [], ["We offer visa sponsorship"], [["licence", "Licensed sponsor (UK)"]], "greenhouse"],
  ["greenhouse:a:2", "Data Analyst", "Acme", "https://x/2", "GB", null, "2026-09-01", "2026-09-01T03:00:00+00:00", "no", false, [], [], [["licence", "Licensed sponsor (UK)"]], "greenhouse"],
  ["lever:b:3", "Product Designer", "Beta", "https://x/3", "NL", "hybrid", null, "2026-10-12T03:00:00+00:00", "unknown", true, ["nl"], [], [], "lever"],
  ["lever:b:4", "Support Agent", "Beta", "https://x/4", null, "onsite", "2026-10-11", "2026-10-11T03:00:00+00:00", "unknown", false, [], [], [], "lever"],
]);
const NOW = new Date("2026-10-13T12:00:00Z");
const ids = (rows) => rows.map((r) => r.id);
const st = (over = {}) => ({ ...structuredClone(DEFAULT_STATE), ...over });
const run = (over) => ids(filterRows(ROWS, st(over), NOW));

test("default view hides 'no' postings", () => {
  assert.deepEqual(run({}), ["greenhouse:a:1", "lever:b:3", "lever:b:4"]);
});
test("unknown-location filter uses XX", () => {
  assert.deepEqual(run({ countries: ["XX"], sponsorship: [] }), ["lever:b:4"]);
});
test("hide postings requiring a language", () => {
  assert.deepEqual(run({ hideLangs: ["nl"] }), ["greenhouse:a:1", "lever:b:4"]);
});
test("badge filter", () => {
  assert.deepEqual(run({ badges: ["licence"], sponsorship: [] }), ["greenhouse:a:1", "greenhouse:a:2"]);
});
test("text search over title and company", () => {
  assert.deepEqual(run({ q: "designer" }), ["lever:b:3"]);
  assert.deepEqual(run({ q: "ACME", sponsorship: [] }), ["greenhouse:a:1", "greenhouse:a:2"]);
});
test("remote 'unknown' matches null work mode", () => {
  assert.deepEqual(run({ remote: ["unknown"], sponsorship: [] }), ["greenhouse:a:2"]);
});
test("posted within N days falls back to first_seen", () => {
  assert.deepEqual(run({ days: 7, sponsorship: [] }), ["greenhouse:a:1", "lever:b:3", "lever:b:4"]);
});
test("company, ats and mixed filters", () => {
  assert.deepEqual(run({ company: "Beta" }), ["lever:b:3", "lever:b:4"]);
  assert.deepEqual(run({ ats: ["greenhouse"] }), ["greenhouse:a:1"]);
  assert.deepEqual(run({ mixed: "only" }), ["lever:b:3"]);
  assert.deepEqual(run({ mixed: "hide" }), ["greenhouse:a:1", "lever:b:4"]);
});
test("state survives a URL round trip", () => {
  const s = st({ countries: ["GB", "NL"], q: "data eng", days: 7, sponsorship: [], mixed: "hide" });
  assert.deepEqual(parseState("?" + serializeState(s)), s);
  assert.equal(serializeState(st()), "");
  assert.deepEqual(parseState("?mixed=bogus&days=abc"), st());
});
test("shardsFor uses selected countries or all", () => {
  const index = { countries: { GB: 2, NL: 1, XX: 1 } };
  assert.deepEqual(shardsFor(st(), index), ["GB", "NL", "XX"]);
  assert.deepEqual(shardsFor(st({ countries: ["NL"] }), index), ["NL"]);
  assert.deepEqual(shardsFor(st(), { countries: {} }), []);
});
test("safeUrl only allows http(s)", () => {
  assert.equal(safeUrl("javascript:alert(1)"), null);
  assert.equal(safeUrl("not a url"), null);
  assert.equal(safeUrl("https://boards.greenhouse.io/x"), "https://boards.greenhouse.io/x");
});
test("sourceLine shows staleness", () => {
  assert.equal(sourceLine("gb", { status: "ok", data_as_of: "2026-10-13T03:00:00+00:00" }), "UK register: data from 2026-10-13");
  assert.equal(sourceLine("nl", { status: "failed", data_as_of: "2026-10-05T03:00:00+00:00" }), "NL register: failed, showing data from 2026-10-05");
  assert.equal(sourceLine("fi", { status: "blocked", data_as_of: null }), "FI register: blocked, no data yet");
});
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `node --test site/`
Expected: FAIL with `Cannot find module '.../site/filters.js'`

- [ ] **Step 4: Implement `site/filters.js`**

```js
// Pure filtering/state helpers for the sponsorscope page (tested with node --test).

export const DEFAULT_STATE = {
  countries: [], sponsorship: ["yes", "unknown"], badges: [], hideLangs: [],
  q: "", company: "", remote: [], days: 0, ats: [], mixed: "any",
};
const LIST_KEYS = ["countries", "sponsorship", "badges", "hideLangs", "remote", "ats"];
const MIXED_VALUES = ["any", "only", "hide"];
const DAY_MS = 86_400_000;

export const LANG_LABELS = {
  nl: "Dutch", de: "German", fr: "French", da: "Danish", fi: "Finnish", sv: "Swedish",
  no: "Norwegian", es: "Spanish", it: "Italian", pt: "Portuguese", pl: "Polish",
  ja: "Japanese", zh: "Chinese",
};
export const SOURCE_LABELS = {
  gb: "UK register", nl: "NL register", dk: "DK register", fi: "FI register",
  us: "US LCA data", ca: "Canada LMIA list", ie: "Ireland permits",
};

export function parseState(search) {
  const params = new URLSearchParams(search);
  const state = structuredClone(DEFAULT_STATE);
  for (const key of LIST_KEYS) {
    if (params.has(key)) state[key] = params.get(key).split(",").filter(Boolean);
  }
  if (params.has("q")) state.q = params.get("q");
  if (params.has("company")) state.company = params.get("company");
  if (params.has("days")) state.days = Number.parseInt(params.get("days"), 10) || 0;
  if (MIXED_VALUES.includes(params.get("mixed"))) state.mixed = params.get("mixed");
  return state;
}

export function serializeState(state) {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(state)) {
    const fallback = DEFAULT_STATE[key];
    if (Array.isArray(value)) {
      if (value.join(",") !== fallback.join(",")) params.set(key, value.join(","));
    } else if (value !== fallback) {
      params.set(key, String(value));
    }
  }
  return params.toString();
}

export function toObjects(fields, rows) {
  return rows.map((row) => Object.fromEntries(fields.map((field, i) => [field, row[i]])));
}

export function filterRows(rows, state, now = new Date()) {
  const q = state.q.trim().toLowerCase();
  const cutoff = state.days > 0 ? new Date(now.getTime() - state.days * DAY_MS).toISOString().slice(0, 10) : null;
  return rows.filter((r) => {
    if (state.countries.length && !state.countries.includes(r.country ?? "XX")) return false;
    if (state.sponsorship.length && !state.sponsorship.includes(r.sponsorship)) return false;
    if (state.badges.length && !state.badges.some((b) => r.badges.some(([type]) => type === b))) return false;
    if (state.hideLangs.length && r.langs.some((l) => state.hideLangs.includes(l))) return false;
    if (state.company && r.company !== state.company) return false;
    if (state.remote.length && !state.remote.includes(r.remote ?? "unknown")) return false;
    if (state.ats.length && !state.ats.includes(r.ats)) return false;
    if (state.mixed === "only" && !r.mixed) return false;
    if (state.mixed === "hide" && r.mixed) return false;
    if (cutoff && (r.posted_at ?? r.first_seen.slice(0, 10)) < cutoff) return false;
    if (q && !`${r.title} ${r.company}`.toLowerCase().includes(q)) return false;
    return true;
  });
}

export function shardsFor(state, index) {
  return state.countries.length ? state.countries : Object.keys(index.countries);
}

export function safeUrl(url) {
  try {
    const parsed = new URL(url);
    return parsed.protocol === "https:" || parsed.protocol === "http:" ? parsed.href : null;
  } catch {
    return null;
  }
}

export function sourceLine(name, info) {
  const label = SOURCE_LABELS[name] ?? name;
  const asOf = info.data_as_of ? info.data_as_of.slice(0, 10) : null;
  if ((info.status === "ok" || info.status === "unchanged") && asOf) return `${label}: data from ${asOf}`;
  return asOf ? `${label}: ${info.status}, showing data from ${asOf}` : `${label}: ${info.status}, no data yet`;
}
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `node --test site/`
Expected: `# pass 12`, `# fail 0`

- [ ] **Step 6: Write `site/index.html`**

```html
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>sponsorscope: jobs that may sponsor your visa</title>
  <link rel="stylesheet" href="style.css">
  <script type="module" src="app.js"></script>
</head>
<body>
  <header>
    <h1>sponsorscope</h1>
    <p>Job postings joined with official visa-sponsor registers. Labels come from text rules. Always read the posting.</p>
  </header>
  <main>
    <aside id="filters" aria-label="Filters"></aside>
    <section aria-label="Results">
      <p id="summary" aria-live="polite">Loading…</p>
      <ol id="results"></ol>
      <button id="more" type="button" hidden>Show more</button>
    </section>
  </main>
  <footer>
    <ul id="sources"></ul>
    <p>Contains public sector information licensed under the
      <a href="https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/">Open Government Licence v3.0</a>.
      Contains information licensed under the Open Government Licence – Canada.
      Location data from <a href="https://www.geonames.org/">GeoNames</a> (CC BY 4.0).</p>
    <p><strong>Not legal advice.</strong> A sponsor licence does not guarantee a given role is sponsored.</p>
  </footer>
</body>
</html>
```

- [ ] **Step 7: Write `site/app.js`**

```js
import {
  LANG_LABELS, filterRows, parseState, safeUrl, serializeState, shardsFor, sourceLine, toObjects,
} from "./filters.js";

const PAGE_SIZE = 200;
const SPONSORSHIP_TEXT = { yes: "Mentions sponsorship", no: "Rules out sponsorship", unknown: "Sponsorship not mentioned" };
const shardCache = new Map();
let index = null;
let state = parseState(location.search);
let current = [];
let visible = PAGE_SIZE;
let token = 0;

const $ = (selector) => document.querySelector(selector);

// All untrusted strings go through textContent: never innerHTML.
function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (key === "text") node.textContent = value;
    else node.setAttribute(key, value);
  }
  node.append(...children);
  return node;
}

async function loadShard(cc) {
  if (!shardCache.has(cc)) {
    shardCache.set(cc, (async () => {
      const resp = await fetch(`data/${cc.toLowerCase()}.json.gz`);
      if (!resp.ok) return [];
      const bytes = new Uint8Array(await resp.arrayBuffer());
      const gzipped = bytes[0] === 0x1f && bytes[1] === 0x8b; // some servers decompress for us
      const text = gzipped
        ? await new Response(new Blob([bytes]).stream().pipeThrough(new DecompressionStream("gzip"))).text()
        : new TextDecoder().decode(bytes);
      return toObjects(index.fields, JSON.parse(text));
    })());
  }
  return shardCache.get(cc);
}

function checkboxGroup(legend, key, options) {
  const fieldset = el("fieldset", {}, el("legend", { text: legend }));
  for (const [value, label] of options) {
    const input = el("input", { type: "checkbox", value });
    input.checked = state[key].includes(value);
    input.addEventListener("change", () => {
      state[key] = input.checked ? [...state[key], value] : state[key].filter((v) => v !== value);
      update();
    });
    fieldset.append(el("label", {}, input, ` ${label}`));
  }
  return fieldset;
}

function select(label, key, options, parse = String) {
  const node = el("select", { "aria-label": label }, ...options.map(([v, t]) => el("option", { value: String(v), text: t })));
  node.value = String(state[key]);
  node.addEventListener("change", () => { state[key] = parse(node.value); update(); });
  return node;
}

function buildFilters() {
  const search = el("input", { type: "search", placeholder: "Search title or company", "aria-label": "Search" });
  search.value = state.q;
  search.addEventListener("input", () => { state.q = search.value; update(); });
  const countries = Object.entries(index.countries)
    .map(([cc, n]) => [cc, `${cc === "XX" ? "Unknown location" : cc} (${n.toLocaleString()})`]);
  $("#filters").replaceChildren(
    search,
    select("Company", "company", [["", "Any company"], ...index.companies.map((c) => [c, c])]),
    checkboxGroup("Country", "countries", countries),
    checkboxGroup("Sponsorship", "sponsorship", Object.entries(SPONSORSHIP_TEXT)),
    checkboxGroup("Register", "badges", [["licence", "Licensed sponsor"], ["history", "Sponsorship history"]]),
    checkboxGroup("Hide if it requires", "hideLangs", Object.entries(LANG_LABELS)),
    checkboxGroup("Work mode", "remote", [["remote", "Remote"], ["hybrid", "Hybrid"], ["onsite", "On-site"], ["unknown", "Not stated"]]),
    checkboxGroup("Job board", "ats", index.ats.map((a) => [a, a])),
    select("Posted within", "days", [[0, "Any time"], [1, "Last 24 hours"], [7, "Last 7 days"], [30, "Last 30 days"]], Number),
    select("Mixed signals", "mixed", [["any", "Mixed signals: show"], ["hide", "Mixed signals: hide"], ["only", "Mixed signals: only"]]),
  );
}

function renderRow(r) {
  const href = safeUrl(r.url);
  const title = href
    ? el("a", { href, target: "_blank", rel: "noopener noreferrer", text: r.title })
    : el("span", { text: r.title });
  const chips = el("div", { class: "chips" });
  for (const [type, text] of r.badges) chips.append(el("span", { class: `badge ${type}`, text }));
  chips.append(el("span", { class: `label ${r.sponsorship}`, text: SPONSORSHIP_TEXT[r.sponsorship] }));
  if (r.mixed) chips.append(el("span", { class: "label mixed", text: "Mixed signals" }));
  for (const lang of r.langs) chips.append(el("span", { class: "lang", text: `Requires ${LANG_LABELS[lang] ?? lang}` }));
  const meta = [r.company, r.country ?? "Unknown location", r.remote, r.posted_at ?? r.first_seen.slice(0, 10)];
  const item = el("li", {}, el("h2", {}, title), el("p", { class: "meta", text: meta.filter(Boolean).join(" · ") }), chips);
  if (r.evidence.length) {
    item.append(el("details", {}, el("summary", { text: "Why this label?" }),
      ...r.evidence.map((e) => el("blockquote", { text: e }))));
  }
  return item;
}

function render() {
  $("#summary").textContent = `${current.length.toLocaleString()} postings`;
  $("#results").replaceChildren(...current.slice(0, visible).map(renderRow));
  $("#more").hidden = current.length <= visible;
}

async function update() {
  history.replaceState(null, "", `?${serializeState(state)}`);
  visible = PAGE_SIZE;
  const mine = ++token;
  const shards = await Promise.all(shardsFor(state, index).map(loadShard));
  if (mine !== token) return; // a newer update started while shards loaded
  current = filterRows(shards.flat(), state);
  render();
}

async function main() {
  const resp = await fetch("data/index.json");
  if (!resp.ok) {
    $("#summary").textContent = "No data published yet.";
    return;
  }
  index = await resp.json();
  buildFilters();
  $("#sources").replaceChildren(...Object.entries(index.sources).map(([name, info]) => el("li", { text: sourceLine(name, info) })));
  $("#more").addEventListener("click", () => { visible += PAGE_SIZE; render(); });
  await update();
}

main();
```

- [ ] **Step 8: Write `site/style.css`**

```css
:root { color-scheme: light dark; --muted: #6b7280; --yes: #15803d; --no: #b91c1c; --unknown: #6b7280; --badge: #1d4ed8; }
* { box-sizing: border-box; }
body { margin: 0; font: 16px/1.5 system-ui, sans-serif; }
header, footer { padding: 1rem 1.5rem; }
header h1 { margin: 0; }
header p, footer, .meta { color: var(--muted); }
main { display: grid; grid-template-columns: 18rem 1fr; gap: 1.5rem; padding: 0 1.5rem; }
@media (max-width: 800px) { main { grid-template-columns: 1fr; } }
#filters { display: flex; flex-direction: column; gap: .75rem; }
#filters input[type="search"], #filters select { width: 100%; padding: .4rem; }
fieldset { border: 1px solid color-mix(in srgb, currentColor 20%, transparent); border-radius: .4rem; max-height: 14rem; overflow: auto; }
fieldset label { display: block; }
#results { list-style: none; padding: 0; margin: 0; }
#results li { padding: .75rem 0; border-bottom: 1px solid color-mix(in srgb, currentColor 15%, transparent); }
#results h2 { font-size: 1.05rem; margin: 0; }
.meta { margin: .1rem 0 .4rem; font-size: .9rem; }
.chips { display: flex; flex-wrap: wrap; gap: .35rem; }
.chips span { font-size: .8rem; padding: .1rem .5rem; border-radius: 999px; border: 1px solid currentColor; }
.badge { color: var(--badge); }
.label.yes { color: var(--yes); } .label.no { color: var(--no); } .label.unknown, .label.mixed, .lang { color: var(--unknown); }
details { margin-top: .4rem; font-size: .9rem; }
blockquote { margin: .3rem 0 .3rem 1rem; color: var(--muted); }
#more { margin: 1rem 0; padding: .5rem 1rem; }
```

- [ ] **Step 9: Smoke-test the page locally**

Run:

```bash
uv run sponsorscope nightly --db dev.db --site site   # dev.db is git-ignored (*.db)
python3 -m http.server -d site 8765
```

Open `http://localhost:8765` and check:
- the result count is greater than 0
- the country checkboxes filter the list
- the URL query updates as filters change
- reloading the page keeps the filters
- "Why this label?" shows the evidence
- the footer shows "UK register: data from <today>"

Stop the server with Ctrl-C. Don't commit `site/data/`; `.gitignore` already excludes it.

- [ ] **Step 10: Commit**

```bash
git add package.json site/index.html site/style.css site/filters.js site/app.js site/filters.test.js
git commit -m "feat: static filterable page with shareable URL state"
```

---

### Task 13: Nightly workflow, DB publishing, README, final verification

**Files:**
- Create: `.github/workflows/nightly.yml`, `scripts/publish_db.sh`, `README.md`

**Interfaces:**
- Consumes: the CLI commands `nightly` and `check-db` (Task 11)

- [ ] **Step 1: Write `scripts/publish_db.sh`**

```bash
#!/usr/bin/env bash
# Upload sponsorscope.db to the rolling `db-latest` release and keep 7 dated snapshots.
set -euo pipefail

DB="${1:-sponsorscope.db}"
TAG="db-latest"
KEEP=7

uv run sponsorscope check-db --db "$DB"

if ! gh release view "$TAG" >/dev/null 2>&1; then
  gh release create "$TAG" --title "Database snapshot" \
    --notes "Rolling SQLite snapshot written by the nightly workflow." --latest=false
fi

stamp="$(date -u +%Y-%m-%d)"
cp "$DB" "sponsorscope-$stamp.db"
gh release upload "$TAG" "$DB" "sponsorscope-$stamp.db" --clobber

gh release view "$TAG" --json assets -q '.assets[].name' \
  | grep -E '^sponsorscope-[0-9]{4}-[0-9]{2}-[0-9]{2}\.db$' | sort | head -n -"$KEEP" \
  | while read -r old; do gh release delete-asset "$TAG" "$old" -y; done
```

Run: `chmod +x scripts/publish_db.sh && bash -n scripts/publish_db.sh`
Expected: no output (the syntax is OK).

- [ ] **Step 2: Write `.github/workflows/nightly.yml`**

```yaml
name: nightly

on:
  schedule:
    - cron: "0 3 * * *"
  workflow_dispatch:

permissions:
  contents: write
  pages: write
  id-token: write

concurrency:
  group: sponsorscope-db
  cancel-in-progress: false

jobs:
  run:
    runs-on: ubuntu-latest
    timeout-minutes: 300
    environment:
      name: github-pages
      url: ${{ steps.deploy.outputs.page_url }}
    env:
      GH_TOKEN: ${{ github.token }}
    steps:
      - uses: actions/checkout@v5

      - uses: astral-sh/setup-uv@v6

      - name: Install
        run: uv sync --frozen

      - name: Download previous database
        run: gh release download db-latest -p sponsorscope.db -D . || echo "No previous database; starting fresh."

      - name: Run pipeline
        run: uv run sponsorscope nightly --db sponsorscope.db --site site

      - name: Publish database
        run: scripts/publish_db.sh sponsorscope.db

      - uses: actions/configure-pages@v5

      - uses: actions/upload-pages-artifact@v3
        with:
          path: site

      - name: Deploy page
        id: deploy
        uses: actions/deploy-pages@v4

      # Keep-alive: GitHub disables scheduled workflows after 60 days without a commit.
      - name: Commit run report
        run: |
          cp site/data/last_run.json last_run.json
          git config user.name "sponsorscope-bot"
          git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
          git add last_run.json
          git commit -m "chore: nightly run report" || exit 0
          git push
```

- [ ] **Step 3: Write `README.md`**

````markdown
# sponsorscope

A nightly-updated, filterable list of job postings that may offer **visa sponsorship**.

- **Sponsor data:** official government registers. v1 has the UK Register of
  licensed sponsors; more countries are coming, see the design spec.
- **Postings:** public ATS job-board APIs (Greenhouse and Lever in v1).
- **Labels:** each English posting is labelled by text rules for sponsorship
  (yes / no / unknown, plus "mixed signals") and for required languages.
  Every label shows the phrases that triggered it.

**Not legal advice.** A sponsor licence does not guarantee that a given role is
sponsored.

## How it works

`seed → registers → match → crawl (geo, English filter, classify) → export` runs
nightly on GitHub Actions:

- The SQLite database is kept as an asset on the `db-latest` release.
- The page in `site/` is deployed to GitHub Pages.
- Design: `docs/superpowers/specs/2026-10-13-sponsorscope-design.md`

## Development

```bash
uv sync
uv run pytest           # Python tests
node --test site/       # page filter tests
uv run sponsorscope nightly --db dev.db --site site
python3 -m http.server -d site 8000
```

- **Add a board:** add it to `seeds/manual.yaml`.
- **Fix a wrong company match:** add an entry to `overrides.yaml`.
- **Change the rules:** after editing `sponsorscope/classify/rules.py`, bump
  `VERSION` and add cases to `tests/fixtures/labels.yaml`.

## Data licences

- UK register: contains public sector information licensed under the Open
  Government Licence v3.0.
- City data: [GeoNames](https://www.geonames.org/), CC BY 4.0.
````

- [ ] **Step 4: Run every check**

Run: `uv run pytest -q && node --test site/ && bash -n scripts/publish_db.sh && uv run sponsorscope --help`
Expected: all Python tests pass, `# fail 0` from node, and the CLI help lists `seed registers match crawl export nightly check-db`.

- [ ] **Step 5: Check for attribution trailers**

Run: `git log --format=%B | grep -ci "co-authored-by" || true`
Expected: `0`

- [ ] **Step 6: Commit**

```bash
git add .github/workflows/nightly.yml scripts/publish_db.sh README.md
git commit -m "ci: nightly workflow publishing DB snapshot and GitHub Pages site"
```

- [ ] **Step 7: Stop and hand over to the user for the push**

Don't push yet. Report to the user:
- the test results
- the local smoke-run counts
- that the branch `spec/sponsorscope-design` is ready to merge into `main`

Then ask whether to proceed with Plans 2 and 3 first (the agreed "work all of it here, then push"), or to push now. Before the first workflow run, someone must set the repo's **Settings → Pages → Source** to "GitHub Actions". That is an outward-facing change, so ask the user to do it or to approve doing it with `gh api`.
````
