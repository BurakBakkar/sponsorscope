# sponsorscope Remaining Registers (Plan 2 of 3) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the remaining six sponsor-data plugins:

- **NL, DK and FI**, licence registers
- **US, CA and IE**, sponsorship-history data

All six follow the `Register` protocol from Plan 1, and blocked sources are
reported honestly.

**Architecture:**
- Each plugin is one file in `sponsorscope/registers/`.
- `latest()` returns a cheap version signal. For HTML registers it also caches
  the parsed page, so a changed version costs one request, not two.
- History plugins aggregate rows per normalised employer into `filings` plus a
  `period`. Export's existing `HISTORY_TEMPLATES` turn these into badges such as
  "Filed 37 certified H-1B LCAs (FY2025)".

**Tech Stack:**
- Adds `python-calamine` to read XLSX files.
- Adds `openpyxl` as a dev-only dependency, to build XLSX test fixtures.

**Spec:** `docs/superpowers/specs/2026-10-13-sponsorscope-design.md` (§2.1 and §8)

**Builds on:** Plan 1 (`docs/superpowers/plans/2026-10-13-sponsorscope-core-pipeline.md`)

## Global Constraints

- Plan 1's Global Constraints apply:
  - no `Co-Authored-By` or Claude attribution in commits
  - no push until the user confirms
  - the same HTTP politeness rules
- **Never bypass bot protection.** A bot challenge (Cloudflare `cf-mitigated`
  or "Just a moment…") raises `RegisterBlocked`, and the run report shows
  `blocked`.
- **History sources use the last complete period** so a year-to-date file can't
  trip the 20% shrink guard:
  - **US:** the newest fiscal year that has a Q4 file, e.g. FY2025
  - **IE:** the newest calendar year before the current one
  - **CA:** the newest quarter. Each quarter is a separate file and none of them
    is cumulative.
- **US counts** only rows with `CASE_STATUS == "Certified"` and
  `VISA_CLASS == "H-1B"`, to match the badge wording. `"Certified - Withdrawn"`
  is excluded.
- History plugins aggregate rows by `normalize(employer)`. For the display name
  they keep the most common raw spelling. Store-level dedupe would otherwise
  overwrite counts instead of summing them.

### Interpretations of the spec (decided here)

1. **FI is best-effort.** migri.fi and avoindata.fi both serve a Cloudflare
   challenge to automated clients, as verified on 2026-10-13. The plugin
   detects the block and reports it. If the page ever becomes reachable, a
   header-driven table parser handles it, using the columns reported for the
   page. That parser is unverified against a live page.
2. **CA uses only the newest quarter, not a rolling year.** It's simpler, and
   the badge says which quarter it covers.
3. **NL and DK store their registry IDs in `registry_id`**: the KVK number (as
   a string, keeping leading zeros) and the CVR number.

## Review Focus

1. **The US file is huge (79–250 MB).** It must be downloaded only when the
   version changes. Memory is bounded to one sheet. [Task 6]
2. **The US page link text has a typo** ("Dislclosure"), so file discovery must
   match on the href. [Task 6]
3. **CA quirks:** the header is on row 2, and the file ends with a notes block.
   Stray rows must not become employers. [Task 7]
4. **The IE file includes a "Total" footer row.** It must not become an
   employer called "Total". [Task 8]
5. **A blocked source must show as `blocked`, not `failed`**, while the other
   sources keep running. [Task 1]

---

### Task 1: `RegisterBlocked` and its pipeline status

**Files:**
- Modify: `sponsorscope/registers/base.py`, `sponsorscope/pipeline.py`
- Test: `tests/test_pipeline.py`, `tests/test_register_base.py`

**Interfaces:**
- Produces:
  - `RegisterBlocked(Exception)`
  - `is_bot_challenge(resp: httpx.Response) -> bool`
  - `run_registers` records `status="blocked"` for `RegisterBlocked`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_register_base.py`:

```python
import httpx

from sponsorscope.registers.base import is_bot_challenge


def test_detects_cloudflare_challenge():
    assert is_bot_challenge(httpx.Response(403, headers={"cf-mitigated": "challenge"}, text="x"))
    assert is_bot_challenge(httpx.Response(403, text="<title>Just a moment...</title>"))
    assert not is_bot_challenge(httpx.Response(403, text="Forbidden"))
    assert not is_bot_challenge(httpx.Response(200, text="Just a moment"))
```

Append to `tests/test_pipeline.py`:

```python
from sponsorscope.registers.base import RegisterBlocked


class BlockedRegister:
    name = "fi"

    async def latest(self, http):
        raise RegisterBlocked("bot challenge (HTTP 403)")

    async def fetch(self, http, version):
        raise AssertionError("never called")


async def test_blocked_register_is_reported_and_others_still_run(conn, http, tmp_path, seeds):
    with sources():
        report = await pipeline.nightly(conn, http, registers=[BlockedRegister(), UkRegister()],
                                        adapters={"greenhouse": Greenhouse()}, classifier=RulesClassifier(),
                                        seeds_path=seeds, overrides=Overrides(), site_dir=tmp_path / "site",
                                        now=T[0], cities=CITIES)
    assert report.sources["fi"]["status"] == "blocked" and "challenge" in report.sources["fi"]["error"]
    assert report.sources["gb"]["status"] == "ok"
```

- [ ] **Step 2: Run the tests**

Run: `uv run pytest tests/test_register_base.py tests/test_pipeline.py -q`
Expected: FAIL with `ImportError: cannot import name 'is_bot_challenge'`

- [ ] **Step 3: Implement.**

Append to `sponsorscope/registers/base.py`, and add `import httpx` at the top:

```python
class RegisterBlocked(Exception):
    """The source refuses automated access (bot challenge). Reported as 'blocked'; never bypassed."""


def is_bot_challenge(resp: httpx.Response) -> bool:
    if resp.status_code not in (403, 429, 503):
        return False
    return "cf-mitigated" in resp.headers or "just a moment" in resp.text[:4000].lower()
```

In `sponsorscope/pipeline.py`:
- import `RegisterBlocked` with `from sponsorscope.registers.base import Register, RegisterBlocked`
- in `run_registers`, add this branch before `except Exception as exc:`:

```python
        except RegisterBlocked as exc:
            conn.rollback()
            report.source(reg.name, "blocked", error=str(exc)[:300])
```

- [ ] **Step 4: Run all the tests**

Run: `uv run pytest -q`
Expected: all passed

- [ ] **Step 5: Commit**

```bash
git add sponsorscope/registers/base.py sponsorscope/pipeline.py tests/test_register_base.py tests/test_pipeline.py
git commit -m "feat: RegisterBlocked status for sources behind bot challenges"
```

---

### Task 2: NL register (IND Public register Work)

**Files:**
- Create: `sponsorscope/registers/nl.py`, `tests/test_register_nl.py`

**Interfaces:**
- Produces:
  - `NlRegister` (`name="nl"`)
  - `parse_page(html: str) -> tuple[str, list[SponsorRecord]]`, returning the version and the records
  - Constant `PAGE`

- [ ] **Step 1: Write the failing tests** in `tests/test_register_nl.py`

```python
import httpx
import pytest

from sponsorscope.registers.base import RegisterFormatError
from sponsorscope.registers.nl import PAGE, NlRegister, parse_page

HTML = """<html><head><meta name="dcterms.modified" content="2026-10-05"></head><body>
<p>The overview was last updated on 5 October 2026.</p>
<div class="ind-table-wrapper"><table>
<thead><tr><th scope="col">Organisation</th><th scope="col">KVK (Chamber of Commerce) number</th></tr></thead>
<tbody>
<tr><th scope="row">""Aa-Dee"" Machinefabriek en Staalbouw Nederland B.V.</th><td>16051874</td></tr>
<tr><th scope="row">Booking.com B.V.</th><td>01041354</td></tr>
<tr><th scope="row">JETRO Amsterdam</th><td></td></tr>
<tr><th scope="row">  </th><td>123</td></tr>
</tbody></table></div></body></html>"""


def test_parse_page():
    version, records = parse_page(HTML)
    assert version == "5 October 2026"
    assert [r.legal_name for r in records] == [
        '"Aa-Dee" Machinefabriek en Staalbouw Nederland B.V.', "Booking.com B.V.", "JETRO Amsterdam"]
    assert records[1].registry_id == "01041354" and records[2].registry_id is None
    assert {(r.country, r.source, r.evidence, r.route) for r in records} == {("NL", "nl", "licence", "Work")}


def test_parse_page_format_errors():
    with pytest.raises(RegisterFormatError):
        parse_page(HTML.replace("last updated on", "refreshed"))
    with pytest.raises(RegisterFormatError):
        parse_page(HTML.replace("<th scope=\"col\">Organisation</th>", "<th>Name</th>"))


async def test_latest_then_fetch_uses_one_request(http, respx_mock):
    route = respx_mock.get(PAGE).mock(return_value=httpx.Response(200, text=HTML))
    reg = NlRegister()
    version = await reg.latest(http)
    assert len(await reg.fetch(http, version)) == 3
    assert route.call_count == 1
```

- [ ] **Step 2: Run the tests**

Run: `uv run pytest tests/test_register_nl.py -q`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement `sponsorscope/registers/nl.py`**

```python
from __future__ import annotations

import re

from selectolax.lexbor import LexborHTMLParser

from sponsorscope.http import Http
from sponsorscope.models import SponsorRecord
from sponsorscope.registers.base import RegisterFormatError

PAGE = "https://ind.nl/en/public-register-recognised-sponsors/public-register-work"
_UPDATED = re.compile(r"last updated on (\d{1,2} \w+ \d{4})", re.IGNORECASE)


def _clean(text: str | None) -> str:
    return re.sub(r"\s+", " ", (text or "").replace("\xa0", " ")).strip()


def parse_page(html: str) -> tuple[str, list[SponsorRecord]]:
    tree = LexborHTMLParser(html)
    match = _UPDATED.search(tree.body.text() if tree.body else "")
    if match is None:
        raise RegisterFormatError("NL register: 'last updated on' date not found")
    table = tree.css_first("div.ind-table-wrapper > table") or tree.css_first("table")
    headers = [_clean(h.text()) for h in table.css("thead th")] if table else []
    if not headers or headers[0] != "Organisation":
        raise RegisterFormatError(f"NL register: unexpected table headers {headers}")
    records = []
    for row in table.css("tbody tr"):
        name_cell, kvk_cell = row.css_first("th"), row.css_first("td")
        name = _clean(name_cell.text() if name_cell else "").replace('""', '"')
        if not name:
            continue
        kvk = _clean(kvk_cell.text() if kvk_cell else "")
        records.append(SponsorRecord(country="NL", source="nl", evidence="licence", legal_name=name,
                                     registry_id=kvk or None, route="Work"))
    return match.group(1), records


class NlRegister:
    """IND public register of recognised sponsors, 'Work' (labour and highly skilled migrants)."""

    name = "nl"

    def __init__(self) -> None:
        self._cache: tuple[str, list[SponsorRecord]] | None = None

    async def latest(self, http: Http) -> str:
        resp = await http.get(PAGE)
        resp.raise_for_status()
        self._cache = parse_page(resp.text)
        return self._cache[0]

    async def fetch(self, http: Http, version: str) -> list[SponsorRecord]:
        if self._cache is None or self._cache[0] != version:
            await self.latest(http)
        return self._cache[1]
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/test_register_nl.py -q`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add sponsorscope/registers/nl.py tests/test_register_nl.py
git commit -m "feat: NL IND recognised-sponsor register plugin"
```

---

### Task 3: DK register (SIRI Certified companies)

**Files:**
- Create: `sponsorscope/registers/dk.py`, `tests/test_register_dk.py`

**Interfaces:**
- Produces: `DkRegister` (`name="dk"`), `parse_page(html) -> tuple[str, list[SponsorRecord]]`, `PAGE`

- [ ] **Step 1: Write the failing tests** in `tests/test_register_dk.py`

```python
import httpx
import pytest

from sponsorscope.registers.base import RegisterFormatError
from sponsorscope.registers.dk import PAGE, DkRegister, parse_page

HTML = """<html><body><div class="rich-text-editor"><table width="614">
<tr><td class="xl65"><p class="bodycopy-small">Name of company</p></td><td><p class="bodycopy-small">CVR no.</p></td></tr>
<tr><td class="xl66"><p class="bodycopy-small">
   &amp;TRADITION A/S</p></td><td><p class="bodycopy-small">18169304</p></td></tr>
<tr><td><p class="bodycopy-small">3Shape A/S&nbsp;</p></td><td><p class="bodycopy-small">25553489&nbsp;</p></td></tr>
<tr><td><p class="bodycopy-small">&nbsp;</p></td><td><p class="bodycopy-small"></p></td></tr>
<tr><td><p class="bodycopy-small">Aarhus Universitet</p></td><td><p class="bodycopy-small">31119103</p></td></tr>
</table></div>
<p class="byline bodycopy-small white"> Last updated 12-10-2026 - Published by: SIRI </p></body></html>"""


def test_parse_page():
    version, records = parse_page(HTML)
    assert version == "12-10-2026"
    assert [(r.legal_name, r.registry_id) for r in records] == [
        ("&TRADITION A/S", "18169304"), ("3Shape A/S", "25553489"), ("Aarhus Universitet", "31119103")]
    assert {(r.country, r.evidence, r.route) for r in records} == {("DK", "licence", "Fast-track")}


def test_format_errors():
    with pytest.raises(RegisterFormatError):
        parse_page(HTML.replace("Name of company", "Firm"))
    with pytest.raises(RegisterFormatError):
        parse_page(HTML.replace("Last updated", "Updated"))


async def test_latest_then_fetch(http, respx_mock):
    route = respx_mock.get(PAGE).mock(return_value=httpx.Response(200, text=HTML))
    reg = DkRegister()
    assert len(await reg.fetch(http, await reg.latest(http))) == 3 and route.call_count == 1
```

- [ ] **Step 2: Run the tests**

Run: `uv run pytest tests/test_register_dk.py -q`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement `sponsorscope/registers/dk.py`**

```python
from __future__ import annotations

import re

from selectolax.lexbor import LexborHTMLParser

from sponsorscope.http import Http
from sponsorscope.models import SponsorRecord
from sponsorscope.registers.base import RegisterFormatError

PAGE = "https://www.nyidanmark.dk/en-GB/Words-and-concepts/SIRI/Certified-companies"
_UPDATED = re.compile(r"Last updated (\d{2}-\d{2}-\d{4})")
_HEADER = ["Name of company", "CVR no."]


def _clean(text: str | None) -> str:
    return re.sub(r"\s+", " ", (text or "").replace("\xa0", " ")).strip()


def parse_page(html: str) -> tuple[str, list[SponsorRecord]]:
    tree = LexborHTMLParser(html)
    match = _UPDATED.search(tree.body.text() if tree.body else "")
    if match is None:
        raise RegisterFormatError("DK register: 'Last updated' date not found")
    table = tree.css_first("div.rich-text-editor table") or tree.css_first("table")
    rows = [[_clean(c.text()) for c in r.css("td") or r.css("th")] for r in table.css("tr")] if table else []
    if not rows or rows[0][:2] != _HEADER:
        raise RegisterFormatError(f"DK register: unexpected header {rows[0] if rows else None}")
    records = [
        SponsorRecord(country="DK", source="dk", evidence="licence", legal_name=r[0],
                      registry_id=(r[1] or None) if len(r) > 1 else None, route="Fast-track")
        for r in rows[1:] if r and r[0]
    ]
    return match.group(1), records


class DkRegister:
    """SIRI certified companies (Fast-track scheme). Danish sort order puts 'Aa…' last; irrelevant here."""

    name = "dk"

    def __init__(self) -> None:
        self._cache: tuple[str, list[SponsorRecord]] | None = None

    async def latest(self, http: Http) -> str:
        resp = await http.get(PAGE)
        resp.raise_for_status()
        self._cache = parse_page(resp.text)
        return self._cache[0]

    async def fetch(self, http: Http, version: str) -> list[SponsorRecord]:
        if self._cache is None or self._cache[0] != version:
            await self.latest(http)
        return self._cache[1]
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/test_register_dk.py -q`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add sponsorscope/registers/dk.py tests/test_register_dk.py
git commit -m "feat: DK SIRI certified-companies register plugin"
```

---

### Task 4: FI register (Migri Certified employers, best-effort)

**Files:**
- Create: `sponsorscope/registers/fi.py`, `tests/test_register_fi.py`

**Interfaces:**
- Produces: `FiRegister` (`name="fi"`), `parse_page(html) -> tuple[str, list[SponsorRecord]]`, `PAGE`

- [ ] **Step 1: Write the failing tests** in `tests/test_register_fi.py`

```python
import httpx
import pytest

from sponsorscope.registers.base import RegisterBlocked, RegisterFormatError
from sponsorscope.registers.fi import PAGE, FiRegister, parse_page

# Columns as reported for migri.fi (unverified live: the site serves a bot challenge).
HTML = """<html><body><table>
<tr><th>Employer</th><th>Business ID</th><th>Certificate issued</th><th>Valid until</th></tr>
<tr><td>Hansavest Työvoima Oy</td><td>2788957-5</td><td>8 March 2023</td><td>8 March 2028</td></tr>
<tr><td>Wolt Enterprises Oy</td><td>2646674-9</td><td>1 June 2024</td><td>1 June 2029</td></tr>
</table></body></html>"""


def test_parse_page_by_header_names():
    version, records = parse_page(HTML)
    assert [(r.legal_name, r.registry_id) for r in records] == [
        ("Hansavest Työvoima Oy", "2788957-5"), ("Wolt Enterprises Oy", "2646674-9")]
    assert len(version) == 16 and parse_page(HTML)[0] == version  # content hash: stable
    assert {(r.country, r.evidence) for r in records} == {("FI", "licence")}


def test_parse_page_without_business_id_table():
    with pytest.raises(RegisterFormatError):
        parse_page("<table><tr><th>Name</th></tr></table>")


async def test_bot_challenge_raises_blocked(http, respx_mock):
    respx_mock.get(PAGE).mock(return_value=httpx.Response(
        403, headers={"cf-mitigated": "challenge"}, text="<title>Just a moment...</title>"))
    with pytest.raises(RegisterBlocked):
        await FiRegister().latest(http)


async def test_reachable_page_parses(http, respx_mock):
    respx_mock.get(PAGE).mock(return_value=httpx.Response(200, text=HTML))
    reg = FiRegister()
    assert len(await reg.fetch(http, await reg.latest(http))) == 2
```

- [ ] **Step 2: Run the tests**

Run: `uv run pytest tests/test_register_fi.py -q`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement `sponsorscope/registers/fi.py`**

```python
from __future__ import annotations

import hashlib
import re

from selectolax.lexbor import LexborHTMLParser

from sponsorscope.http import Http
from sponsorscope.models import SponsorRecord
from sponsorscope.registers.base import RegisterBlocked, RegisterFormatError, is_bot_challenge

PAGE = "https://migri.fi/en/certified-employers"
_ID_HEADER = re.compile(r"business id|y-tunnus", re.IGNORECASE)
_NAME_HEADER = re.compile(r"employer|name|työnantaja", re.IGNORECASE)


def _clean(text: str | None) -> str:
    return re.sub(r"\s+", " ", (text or "").replace("\xa0", " ")).strip()


def parse_page(html: str) -> tuple[str, list[SponsorRecord]]:
    """Header-driven parse (column order on migri.fi is unverified). Version = content hash."""
    tree = LexborHTMLParser(html)
    for table in tree.css("table"):
        rows = [[_clean(c.text()) for c in r.css("th, td")] for r in table.css("tr")]
        if not rows:
            continue
        header = rows[0]
        id_col = next((i for i, h in enumerate(header) if _ID_HEADER.search(h)), None)
        if id_col is None:
            continue
        name_col = next((i for i, h in enumerate(header) if _NAME_HEADER.search(h) and i != id_col), 0)
        records = [
            SponsorRecord(country="FI", source="fi", evidence="licence", legal_name=r[name_col],
                          registry_id=r[id_col] or None, route="Certified employer")
            for r in rows[1:] if len(r) > max(id_col, name_col) and r[name_col]
        ]
        digest = hashlib.sha256("\n".join(f"{r.legal_name}|{r.registry_id}" for r in records).encode()).hexdigest()
        return digest[:16], records
    raise RegisterFormatError("FI register: no table with a Business ID column")


class FiRegister:
    """Migri certified employers. Behind a Cloudflare challenge as of 2026-10-13 → reported as blocked."""

    name = "fi"

    def __init__(self) -> None:
        self._cache: tuple[str, list[SponsorRecord]] | None = None

    async def latest(self, http: Http) -> str:
        resp = await http.get(PAGE)
        if is_bot_challenge(resp):
            raise RegisterBlocked(f"migri.fi serves a bot challenge (HTTP {resp.status_code}); not bypassed")
        resp.raise_for_status()
        self._cache = parse_page(resp.text)
        return self._cache[0]

    async def fetch(self, http: Http, version: str) -> list[SponsorRecord]:
        if self._cache is None or self._cache[0] != version:
            await self.latest(http)
        return self._cache[1]
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/test_register_fi.py -q`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add sponsorscope/registers/fi.py tests/test_register_fi.py
git commit -m "feat: FI certified-employers plugin that reports bot challenges as blocked"
```

---

### Task 5: XLSX reading helper

**Files:**
- Modify: `pyproject.toml` (`uv add python-calamine` and `uv add --dev openpyxl`)
- Create: `sponsorscope/registers/xlsx.py`, `tests/xlsx_fixtures.py`, `tests/test_xlsx.py`

**Interfaces:**
- Produces:
  - `sheet_rows(data: bytes, index: int = 0) -> Iterator[list]`
  - `cell_str(v) -> str`
  - `cell_int(v) -> int`
  - Test helper `make_xlsx(rows: list[list], sheet: str = "Sheet1") -> bytes`

- [ ] **Step 1: Add the dependencies**

Run: `uv add 'python-calamine>=0.2' && uv add --dev 'openpyxl>=3.1'`
Expected: `pyproject.toml` and `uv.lock` are updated.

- [ ] **Step 2: Write the fixture helper and the failing test**

`tests/xlsx_fixtures.py`:

```python
import io

from openpyxl import Workbook


def make_xlsx(rows: list[list], sheet: str = "Sheet1") -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = sheet
    for row in rows:
        ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
```

`tests/test_xlsx.py`:

```python
from sponsorscope.registers.xlsx import cell_int, cell_str, sheet_rows
from tests.xlsx_fixtures import make_xlsx


def test_sheet_rows_round_trip():
    data = make_xlsx([["Employer Name", "Total"], ["  Acme Ltd ", 3], ["Beta", None]])
    rows = list(sheet_rows(data))
    assert [cell_str(r[0]) for r in rows] == ["Employer Name", "Acme Ltd", "Beta"]
    assert [cell_int(r[1]) for r in rows[1:]] == [3, 0]


def test_cell_helpers():
    assert cell_str(None) == "" and cell_str(1.0) == "1.0" and cell_str("  x\xa0") == "x"
    assert cell_int("") == 0 and cell_int(2.0) == 2 and cell_int("7") == 7 and cell_int("n/a") == 0
```

- [ ] **Step 3: Run the tests**

Run: `uv run pytest tests/test_xlsx.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'sponsorscope.registers.xlsx'`

- [ ] **Step 4: Implement `sponsorscope/registers/xlsx.py`**

```python
from __future__ import annotations

import io
from collections.abc import Iterator

from python_calamine import CalamineWorkbook


def sheet_rows(data: bytes, index: int = 0) -> Iterator[list]:
    """Rows of one sheet. calamine holds the sheet in Rust memory (~2.8 GB for the 250 MB US file)."""
    workbook = CalamineWorkbook.from_filelike(io.BytesIO(data))
    yield from workbook.get_sheet_by_index(index).iter_rows()


def cell_str(value: object) -> str:
    if value is None:
        return ""
    return str(value).replace("\xa0", " ").strip()


def cell_int(value: object) -> int:
    try:
        return int(float(value)) if value not in (None, "") else 0
    except (TypeError, ValueError):
        return 0
```

- [ ] **Step 5: Run the tests**

Run: `uv run pytest tests/test_xlsx.py -q`
Expected: 2 passed

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml uv.lock sponsorscope/registers/xlsx.py tests/xlsx_fixtures.py tests/test_xlsx.py
git commit -m "feat: XLSX row reader for spreadsheet registers"
```

---

### Task 6: US plugin (DOL LCA disclosure data, sponsorship history)

**Files:**
- Create: `sponsorscope/registers/us.py`, `tests/test_register_us.py`

**Interfaces:**
- Consumes: `sheet_rows`, `cell_str` (Task 5), `normalize`
- Produces:
  - `UsRegister` (`name="us"`)
  - `pick_file(html: str) -> tuple[str, str]`, returning the URL and a period such as `"FY2025"`
  - `parse_lca(data: bytes, period: str) -> list[SponsorRecord]`
  - Constant `PAGE`

- [ ] **Step 1: Write the failing tests** in `tests/test_register_us.py`

```python
import httpx
import pytest

from sponsorscope.registers.base import RegisterFormatError
from sponsorscope.registers.us import PAGE, UsRegister, parse_lca, pick_file
from tests.xlsx_fixtures import make_xlsx

PAGE_HTML = """<table><tr><td>LCA Programs (H-1B, H-1B1, E-3)</td>
<td><a href="https://www.dol.gov//media/LCA_Disclosure_Data_FY2026_Q3.xlsx">LCA_Dislclosure_Data_FY2026_Q3.xlsx</a></td></tr>
<tr><td><a href="/sites/dolgov/files/ETA/oflc/pdfs/LCA_Disclosure_Data_FY2025_Q4.xlsx">FY2025 Q4</a></td></tr>
<tr><td><a href="/sites/dolgov/files/ETA/oflc/pdfs/LCA_Disclosure_Data_FY2025_Q3.xlsx">FY2025 Q3</a></td></tr>
<tr><td><a href="/sites/dolgov/files/ETA/oflc/pdfs/PERM_Disclosure_Data_FY2025_Q4.xlsx">PERM</a></td></tr></table>"""
HEADER = ["CASE_NUMBER", "CASE_STATUS", "DECISION_DATE", "VISA_CLASS", "EMPLOYER_NAME", "EMPLOYER_COUNTRY"]


def test_pick_file_prefers_latest_complete_fiscal_year():
    url, period = pick_file(PAGE_HTML)
    assert url == "https://www.dol.gov/sites/dolgov/files/ETA/oflc/pdfs/LCA_Disclosure_Data_FY2025_Q4.xlsx"
    assert period == "FY2025"


def test_pick_file_falls_back_to_newest_when_no_q4():
    url, period = pick_file(PAGE_HTML.replace("FY2025_Q4", "FY2025_Q2"))
    assert url.endswith("LCA_Disclosure_Data_FY2026_Q3.xlsx") and period == "FY2026"
    with pytest.raises(RegisterFormatError):
        pick_file("<a href='/other.xlsx'>x</a>")


def test_parse_lca_counts_certified_h1b_per_normalised_employer():
    data = make_xlsx([HEADER,
        ["I-1", "Certified", "2025-10-01", "H-1B", "Acme Widgets LLC", "UNITED STATES OF AMERICA"],
        ["I-2", "Certified", "2025-10-02", "H-1B", "ACME WIDGETS, LLC", "UNITED STATES OF AMERICA"],
        ["I-3", "Certified", "2025-10-03", "H-1B", "Acme Widgets LLC", "UNITED STATES OF AMERICA"],
        ["I-4", "Certified - Withdrawn", "2025-10-04", "H-1B", "Acme Widgets LLC", ""],
        ["I-5", "Denied", "2025-10-05", "H-1B", "Beta Corp", ""],
        ["I-6", "Certified", "2025-10-06", "E-3 Australian", "Beta Corp", ""],
        ["I-7", "Certified", "2025-10-07", "H-1B", "Gamma Inc", ""]])
    records = {r.legal_name: r for r in parse_lca(data, "FY2025")}
    assert set(records) == {"Acme Widgets LLC", "Gamma Inc"}
    acme = records["Acme Widgets LLC"]
    assert (acme.country, acme.source, acme.evidence, acme.route, acme.filings, acme.period) == (
        "US", "us", "history", "H-1B", 3, "FY2025")


def test_parse_lca_missing_columns():
    with pytest.raises(RegisterFormatError):
        parse_lca(make_xlsx([["CASE_NUMBER", "EMPLOYER"]]), "FY2025")


async def test_latest_and_fetch(http, respx_mock):
    respx_mock.get(PAGE).mock(return_value=httpx.Response(200, text=PAGE_HTML))
    url = "https://www.dol.gov/sites/dolgov/files/ETA/oflc/pdfs/LCA_Disclosure_Data_FY2025_Q4.xlsx"
    respx_mock.get(url).mock(return_value=httpx.Response(200, content=make_xlsx([HEADER,
        ["I-1", "Certified", "d", "H-1B", "Gamma Inc", ""]])))
    reg = UsRegister()
    version = await reg.latest(http)
    assert version == url
    [record] = await reg.fetch(http, version)
    assert (record.legal_name, record.filings, record.period) == ("Gamma Inc", 1, "FY2025")
```

- [ ] **Step 2: Run the tests**

Run: `uv run pytest tests/test_register_us.py -q`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement `sponsorscope/registers/us.py`**

```python
from __future__ import annotations

import re
from collections import Counter
from urllib.parse import urljoin

from selectolax.lexbor import LexborHTMLParser

from sponsorscope.http import Http
from sponsorscope.matching.names import normalize
from sponsorscope.models import SponsorRecord
from sponsorscope.registers.base import RegisterFormatError
from sponsorscope.registers.xlsx import cell_str, sheet_rows

PAGE = "https://www.dol.gov/agencies/eta/foreign-labor/performance"
_FILE = re.compile(r"LCA_Disclosure_Data_FY(\d{4})_Q(\d)\.xlsx$", re.IGNORECASE)  # match hrefs: link text has typos
_REQUIRED = ("CASE_STATUS", "VISA_CLASS", "EMPLOYER_NAME")


def _url_period(url: str) -> str:
    match = _FILE.search(url)
    if match is None:
        raise RegisterFormatError(f"US LCA: cannot read fiscal year from {url}")
    return f"FY{match.group(1)}"


def pick_file(html: str) -> tuple[str, str]:
    """Newest fiscal year with a Q4 (complete) file; otherwise the newest file of any quarter."""
    files: dict[tuple[int, int], str] = {}
    for a in LexborHTMLParser(html).css("a[href]"):
        href = (a.attributes.get("href") or "").split("?")[0]
        match = _FILE.search(href)
        if match:
            files[(int(match.group(1)), int(match.group(2)))] = urljoin(PAGE, href).replace("gov//", "gov/")
    if not files:
        raise RegisterFormatError("US LCA: no LCA_Disclosure_Data_FY*_Q*.xlsx link on the performance page")
    complete = [key for key in files if key[1] == 4]
    key = max(complete) if complete else max(files)
    return files[key], f"FY{key[0]}"


def parse_lca(data: bytes, period: str) -> list[SponsorRecord]:
    rows = sheet_rows(data)
    header = [cell_str(h) for h in next(rows, [])]
    idx = {h: i for i, h in enumerate(header)}
    missing = [c for c in _REQUIRED if c not in idx]
    if missing:
        raise RegisterFormatError(f"US LCA: missing columns {missing}")
    status_i, visa_i, name_i = (idx[c] for c in _REQUIRED)
    width = max(status_i, visa_i, name_i)
    filings: Counter[str] = Counter()
    spellings: dict[str, Counter[str]] = {}
    for row in rows:
        if len(row) <= width or cell_str(row[status_i]) != "Certified" or cell_str(row[visa_i]) != "H-1B":
            continue
        raw = cell_str(row[name_i])
        norm = normalize(raw)
        if not norm:
            continue
        filings[norm] += 1
        spellings.setdefault(norm, Counter())[raw] += 1
    return [
        SponsorRecord(country="US", source="us", evidence="history", legal_name=spellings[n].most_common(1)[0][0],
                      route="H-1B", filings=count, period=period)
        for n, count in filings.items()
    ]


class UsRegister:
    """DOL OFLC LCA disclosure data: certified H-1B LCAs per employer for the last complete fiscal year."""

    name = "us"

    async def latest(self, http: Http) -> str:
        resp = await http.get(PAGE)
        resp.raise_for_status()
        return pick_file(resp.text)[0]

    async def fetch(self, http: Http, version: str) -> list[SponsorRecord]:
        resp = await http.get(version)  # 80–250 MB; only downloaded when the version (file URL) changes
        resp.raise_for_status()
        return parse_lca(resp.content, _url_period(version))
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/test_register_us.py -q`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add sponsorscope/registers/us.py tests/test_register_us.py
git commit -m "feat: US LCA disclosure plugin (certified H-1B filings per employer, last complete FY)"
```

---

### Task 7: CA plugin (ESDC positive LMIA employers)

**Files:**
- Create: `sponsorscope/registers/ca.py`, `tests/test_register_ca.py`

**Interfaces:**
- Produces:
  - `CaRegister` (`name="ca"`)
  - `pick_resource(package: dict) -> tuple[str, str]`, returning the URL and a period such as `"2026 Q1"`
  - `parse_lmia(data: bytes, period: str) -> list[SponsorRecord]`
  - Constant `PACKAGE_API`

- [ ] **Step 1: Write the failing tests** in `tests/test_register_ca.py`

```python
import httpx
import pytest

from sponsorscope.registers.base import RegisterFormatError
from sponsorscope.registers.ca import PACKAGE_API, CaRegister, parse_lmia, pick_resource
from tests.xlsx_fixtures import make_xlsx

BASE = "https://open.canada.ca/data/dataset/90fed587/resource"
PACKAGE = {"result": {"metadata_modified": "2026-07-22T13:31:33", "resources": [
    {"name": "2025Q4-Employers Who Were Issued a Positive LMIA", "format": "XLSX", "language": ["en"],
     "url": f"{BASE}/a/download/tfwp_2025q4_pos_en.xlsx"},
    {"name": "2026Q1-Employers Who Were Issued a Positive LMIA", "format": "XLSX", "language": ["en"],
     "url": f"{BASE}/b/download/tfwp_2026q1_pos_en.xlsx"},
    {"name": "2026T1-Employeurs", "format": "XLSX", "language": ["fr"], "url": f"{BASE}/c/download/tfwp_2026q1_pos_fr.xlsx"},
    {"name": "2026Q1-Employers (CSV)", "format": "CSV", "language": ["en"], "url": f"{BASE}/d/download/x.csv"},
]}}
HEADER = ["Province/Territory", "Program Stream", "Employer", "Address", "Occupation", "Incorporate Status",
          "Approved LMIAs", "Approved Positions"]


def lmia_rows():
    return [["Positive Labour Market Impact Assessment (LMIA) Employers List, 2026 Q1"], HEADER,
            ["Ontario   ", "High Wage   ", "Acme Software Inc.", "Toronto, ON", "21231-Software engineers", "Yes", 2.0, 3.0],
            ["Ontario", "Global Talent Stream", "ACME SOFTWARE INC", "Toronto, ON", "21231", "Yes", 1.0, 1.0],
            ["Quebec", "Low Wage", "Boulangerie Ltée", "Montréal, QC", "65201", "Unknown", 1.0, 4.0],
            ["", "", "", "", "", "", "", ""],
            ["Notes:"], ["1. Employers with personal names are excluded."]]


def test_pick_resource_newest_english_xlsx():
    assert pick_resource(PACKAGE) == (f"{BASE}/b/download/tfwp_2026q1_pos_en.xlsx", "2026 Q1")
    with pytest.raises(RegisterFormatError):
        pick_resource({"result": {"resources": []}})


def test_parse_lmia_header_on_second_row_and_notes_footer():
    records = {r.legal_name: r for r in parse_lmia(make_xlsx(lmia_rows()), "2026 Q1")}
    assert set(records) == {"Acme Software Inc.", "Boulangerie Ltée"}
    acme = records["Acme Software Inc."]
    assert (acme.country, acme.evidence, acme.filings, acme.period, acme.route) == ("CA", "history", 3, "2026 Q1", "LMIA")


def test_parse_lmia_without_header():
    with pytest.raises(RegisterFormatError):
        parse_lmia(make_xlsx([["title"], ["Employer", "Count"]]), "2026 Q1")


async def test_latest_and_fetch(http, respx_mock):
    respx_mock.get(PACKAGE_API).mock(return_value=httpx.Response(200, json=PACKAGE))
    url = f"{BASE}/b/download/tfwp_2026q1_pos_en.xlsx"
    respx_mock.get(url).mock(return_value=httpx.Response(200, content=make_xlsx(lmia_rows())))
    reg = CaRegister()
    assert await reg.latest(http) == url
    assert len(await reg.fetch(http, url)) == 2
```

- [ ] **Step 2: Run the tests**

Run: `uv run pytest tests/test_register_ca.py -q`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement `sponsorscope/registers/ca.py`**

```python
from __future__ import annotations

import re
from collections import Counter

from sponsorscope.http import Http
from sponsorscope.matching.names import normalize
from sponsorscope.models import SponsorRecord
from sponsorscope.registers.base import RegisterFormatError
from sponsorscope.registers.xlsx import cell_int, cell_str, sheet_rows

PACKAGE_API = "https://open.canada.ca/data/api/action/package_show?id=90fed587-1364-4f33-a9ee-208181dc0b97"
_NAME_QUARTER = re.compile(r"^(\d{4})Q(\d)-")
_URL_QUARTER = re.compile(r"tfwp_(\d{4})q(\d)_pos_en\.xlsx", re.IGNORECASE)
_HEADER_START = ["Province/Territory", "Program Stream", "Employer"]


def pick_resource(package: dict) -> tuple[str, str]:
    best: tuple[tuple[int, int], str] | None = None
    for res in (package.get("result") or {}).get("resources", []):
        language = res.get("language")
        if (res.get("format") or "").upper() != "XLSX" or language not in (["en"], "en"):
            continue
        match = _NAME_QUARTER.match(res.get("name") or "") or _URL_QUARTER.search(res.get("url") or "")
        if match:
            key = (int(match.group(1)), int(match.group(2)))
            if best is None or key > best[0]:
                best = (key, res["url"])
    if best is None:
        raise RegisterFormatError("CA LMIA: no English XLSX quarterly resource in the CKAN package")
    return best[1], f"{best[0][0]} Q{best[0][1]}"


def _url_period(url: str) -> str:
    match = _URL_QUARTER.search(url)
    return f"{match.group(1)} Q{match.group(2)}" if match else "latest quarter"


def parse_lmia(data: bytes, period: str) -> list[SponsorRecord]:
    rows = list(sheet_rows(data))
    header_at = next((i for i, r in enumerate(rows[:10]) if [cell_str(c) for c in r[:3]] == _HEADER_START), None)
    if header_at is None:
        raise RegisterFormatError("CA LMIA: header row not found in the first 10 rows")
    idx = {cell_str(h): i for i, h in enumerate(rows[header_at])}
    if "Approved LMIAs" not in idx:
        raise RegisterFormatError("CA LMIA: 'Approved LMIAs' column missing")
    name_i, count_i = idx["Employer"], idx["Approved LMIAs"]
    filings: Counter[str] = Counter()
    spellings: dict[str, Counter[str]] = {}
    for row in rows[header_at + 1:]:
        if row and cell_str(row[0]).startswith("Notes"):
            break
        if len(row) <= max(name_i, count_i):
            continue
        raw = cell_str(row[name_i])
        norm = normalize(raw)
        if not norm:
            continue
        filings[norm] += cell_int(row[count_i]) or 1
        spellings.setdefault(norm, Counter())[raw] += 1
    return [
        SponsorRecord(country="CA", source="ca", evidence="history", legal_name=spellings[n].most_common(1)[0][0],
                      route="LMIA", filings=count, period=period)
        for n, count in filings.items()
    ]


class CaRegister:
    """ESDC positive LMIA employers list (newest quarter; quarters are not cumulative)."""

    name = "ca"

    async def latest(self, http: Http) -> str:
        resp = await http.get(PACKAGE_API)
        resp.raise_for_status()
        return pick_resource(resp.json())[0]

    async def fetch(self, http: Http, version: str) -> list[SponsorRecord]:
        resp = await http.get(version)
        resp.raise_for_status()
        return parse_lmia(resp.content, _url_period(version))
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/test_register_ca.py -q`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add sponsorscope/registers/ca.py tests/test_register_ca.py
git commit -m "feat: CA positive-LMIA employers plugin"
```

---

### Task 8: IE plugin (DETE employment permits issued to companies)

**Files:**
- Create: `sponsorscope/registers/ie.py`, `tests/test_register_ie.py`

**Interfaces:**
- Produces:
  - `IeRegister(today: Callable[[], date] = date.today)` (`name="ie"`)
  - `pick_year_page(html: str, today: date) -> tuple[str, int]`
  - `find_file(html: str, page_url: str) -> str`
  - `parse_permits(data: bytes, period: str) -> list[SponsorRecord]`
  - Constant `STATS_PAGE`

- [ ] **Step 1: Write the failing tests** in `tests/test_register_ie.py`

```python
from datetime import date

import httpx
import pytest

from sponsorscope.registers.base import RegisterFormatError
from sponsorscope.registers.ie import STATS_PAGE, IeRegister, find_file, parse_permits, pick_year_page
from tests.xlsx_fixtures import make_xlsx

STATS_HTML = """<ul>
<li><a href="/en/publications/employment-permit-statistics-2026.html">Employment Permit Statistics for 2026</a></li>
<li><a href="/en/publications/employment-permit-statistics-2025.html">2025</a></li>
<li><a href="/en/Publications/Employment-Permit-Statisitcs-2013.html">2013</a></li></ul>"""
YEAR_HTML = """<div class="relatedDocument"><a href="/en/publications/publication-files/employment-permits-issued-to-companies-2025.xlsx">
Employment permits issued to companies 2025</a></div>"""
PERMITS = [["Employer Name", "Permits Issued Jan", "Permits Issued Feb", "Permits Issued Grand Total"],
           ["24 Doc (Doctor On Call) Limited", 1.0, 2.0, 3.0],
           ["Acme Widgets Ltd", "", 1.0, 1.0],
           ["ACME WIDGETS LIMITED", 2.0, "", 2.0],
           ["Total", 3.0, 3.0, 6.0]]


def test_pick_year_page_uses_last_complete_year():
    url, year = pick_year_page(STATS_HTML, date(2026, 10, 13))
    assert (url, year) == ("https://enterprise.gov.ie/en/publications/employment-permit-statistics-2025.html", 2025)
    with pytest.raises(RegisterFormatError):
        pick_year_page("<a href='/x.html'>x</a>", date(2026, 10, 13))


def test_find_file():
    page = "https://enterprise.gov.ie/en/publications/employment-permit-statistics-2025.html"
    assert find_file(YEAR_HTML, page) == (
        "https://enterprise.gov.ie/en/publications/publication-files/employment-permits-issued-to-companies-2025.xlsx")


def test_parse_permits_skips_total_and_aggregates():
    records = {r.legal_name: r for r in parse_permits(make_xlsx(PERMITS, sheet="Export"), "2025")}
    assert set(records) == {"24 Doc (Doctor On Call) Limited", "Acme Widgets Ltd"}
    acme = records["Acme Widgets Ltd"]
    assert (acme.country, acme.evidence, acme.filings, acme.period, acme.route) == ("IE", "history", 3, "2025", "Employment permit")


def test_parse_permits_unexpected_header():
    with pytest.raises(RegisterFormatError):
        parse_permits(make_xlsx([["Company", "Count"]]), "2025")


async def test_latest_and_fetch(http, respx_mock):
    year_url = "https://enterprise.gov.ie/en/publications/employment-permit-statistics-2025.html"
    file_url = "https://enterprise.gov.ie/en/publications/publication-files/employment-permits-issued-to-companies-2025.xlsx"
    respx_mock.get(STATS_PAGE).mock(return_value=httpx.Response(200, text=STATS_HTML))
    respx_mock.get(year_url).mock(return_value=httpx.Response(200, text=YEAR_HTML))
    respx_mock.get(file_url).mock(return_value=httpx.Response(200, content=make_xlsx(PERMITS)))
    reg = IeRegister(today=lambda: date(2026, 10, 13))
    assert await reg.latest(http) == file_url
    assert {r.period for r in await reg.fetch(http, file_url)} == {"2025"}
```

- [ ] **Step 2: Run the tests**

Run: `uv run pytest tests/test_register_ie.py -q`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement `sponsorscope/registers/ie.py`**

```python
from __future__ import annotations

import re
from collections import Counter
from collections.abc import Callable
from datetime import date
from urllib.parse import urljoin

from selectolax.lexbor import LexborHTMLParser

from sponsorscope.http import Http
from sponsorscope.matching.names import normalize
from sponsorscope.models import SponsorRecord
from sponsorscope.registers.base import RegisterFormatError
from sponsorscope.registers.xlsx import cell_int, cell_str, sheet_rows

STATS_PAGE = "https://enterprise.gov.ie/en/what-we-do/workplace-and-skills/employment-permits/statistics/"
_YEAR_PAGE = re.compile(r"employment-permit-statistics-(\d{4})\.html", re.IGNORECASE)
_FILE_YEAR = re.compile(r"issued-to-companies-(\d{4})", re.IGNORECASE)


def pick_year_page(html: str, today: date) -> tuple[str, int]:
    """Newest year before the current one (the current year's file is year-to-date)."""
    pages: dict[int, str] = {}
    for a in LexborHTMLParser(html).css("a[href]"):
        href = a.attributes.get("href") or ""
        match = _YEAR_PAGE.search(href)
        if match:
            pages[int(match.group(1))] = urljoin(STATS_PAGE, href)
    if not pages:
        raise RegisterFormatError("IE permits: no yearly statistics pages linked")
    complete = [y for y in pages if y < today.year]
    year = max(complete) if complete else max(pages)
    return pages[year], year


def find_file(html: str, page_url: str) -> str:
    tree = LexborHTMLParser(html)
    link = tree.css_first('div.relatedDocument a[href*="issued-to-companies"]') or \
        tree.css_first('a[href*="issued-to-companies"]')
    if link is None:
        raise RegisterFormatError(f"IE permits: no 'issued-to-companies' file on {page_url}")
    return urljoin(page_url, link.attributes.get("href") or "")


def parse_permits(data: bytes, period: str) -> list[SponsorRecord]:
    rows = sheet_rows(data)
    header = [cell_str(h) for h in next(rows, [])]
    if not header or header[0] != "Employer Name" or not header[-1].endswith("Grand Total"):
        raise RegisterFormatError(f"IE permits: unexpected header {header[:2]}…")
    total_i = len(header) - 1
    filings: Counter[str] = Counter()
    spellings: dict[str, Counter[str]] = {}
    for row in rows:
        raw = cell_str(row[0]) if row else ""
        if raw in ("", "Total") or len(row) <= total_i:
            continue
        norm = normalize(raw)
        if not norm:
            continue
        filings[norm] += cell_int(row[total_i])
        spellings.setdefault(norm, Counter())[raw] += 1
    return [
        SponsorRecord(country="IE", source="ie", evidence="history", legal_name=spellings[n].most_common(1)[0][0],
                      route="Employment permit", filings=count, period=period)
        for n, count in filings.items()
    ]


class IeRegister:
    """DETE employment permits issued to companies (last complete calendar year)."""

    name = "ie"

    def __init__(self, today: Callable[[], date] = date.today) -> None:
        self._today = today

    async def latest(self, http: Http) -> str:
        stats = await http.get(STATS_PAGE)
        stats.raise_for_status()
        page_url, _year = pick_year_page(stats.text, self._today())
        page = await http.get(page_url)
        page.raise_for_status()
        return find_file(page.text, page_url)

    async def fetch(self, http: Http, version: str) -> list[SponsorRecord]:
        resp = await http.get(version)
        resp.raise_for_status()
        match = _FILE_YEAR.search(version)
        return parse_permits(resp.content, match.group(1) if match else "latest year")
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/test_register_ie.py -q`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add sponsorscope/registers/ie.py tests/test_register_ie.py
git commit -m "feat: IE employment-permits-issued plugin (last complete year)"
```

---

### Task 9: Wire up all registers; attribution; live verification

**Files:**
- Modify: `sponsorscope/cli.py`, `site/index.html`, `README.md`
- Test: `tests/test_cli.py`

**Interfaces:**
- Produces: `cli._registers()` returns all seven plugins, ordered gb, nl, dk, fi, us, ca, ie

- [ ] **Step 1: Write the failing test.** Append to `tests/test_cli.py`:

```python
def test_all_registers_wired():
    from sponsorscope import cli
    assert [r.name for r in cli._registers()] == ["gb", "nl", "dk", "fi", "us", "ca", "ie"]
```

- [ ] **Step 2: Run the test**

Run: `uv run pytest tests/test_cli.py -q`
Expected: FAIL with `AssertionError: ['gb'] != [...]`

- [ ] **Step 3: Implement.** In `sponsorscope/cli.py`, add the imports and replace `_registers`:

```python
from sponsorscope.registers.ca import CaRegister
from sponsorscope.registers.dk import DkRegister
from sponsorscope.registers.fi import FiRegister
from sponsorscope.registers.ie import IeRegister
from sponsorscope.registers.nl import NlRegister
from sponsorscope.registers.us import UsRegister


def _registers():
    return [UkRegister(), NlRegister(), DkRegister(), FiRegister(), UsRegister(), CaRegister(), IeRegister()]
```

In `site/index.html`, replace the first footer `<p>…</p>` (the licence paragraph) with:

```html
    <p>Sponsor data: UK Home Office register of licensed sponsors (contains public sector information licensed under the
      <a href="https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/">Open Government Licence v3.0</a>);
      IND public register of recognised sponsors (NL); SIRI certified companies (DK); Migri certified employers (FI);
      US DOL OFLC LCA disclosure data; ESDC positive LMIA employers (contains information licensed under the Open Government Licence – Canada);
      DETE employment permits issued to companies (IE).
      Location data from <a href="https://www.geonames.org/">GeoNames</a> (CC BY 4.0).</p>
```

In `README.md`:
- replace the **Sponsor data** bullet with: `- **Sponsor data:** UK, NL, DK and FI licence registers, plus US (H-1B LCA), CA (positive LMIA) and IE (employment permits) sponsorship history. FI is currently behind a bot challenge and shows as "blocked".`
- under **Data licences**, add the line `- Canada LMIA list: Open Government Licence – Canada. NL, DK, FI, US and IE sources state no licence; only derived badges and company names are published.`

- [ ] **Step 4: Run every check**

Run: `uv run pytest -q && node --test 'site/*.test.js'`
Expected: all passed

- [ ] **Step 5: Live check against the real sources.** This downloads about 80 MB for the US.

Run: `uv run sponsorscope registers --db dev.db`
Expected, one line per source:
- `gb`: `ok` or `unchanged`
- `nl`: `ok`, rows about 13,000
- `dk`: `ok`, rows about 987
- `fi`: `blocked`
- `us`: `ok`, a few tens of thousands of employers, version ending `FY2025_Q4.xlsx`
- `ca`: `ok`, a few thousand employers
- `ie`: `ok`, a few thousand employers

Then run `uv run sponsorscope match --db dev.db && uv run sponsorscope export --db dev.db --site site`. Spot-check that some seed companies now have history badges, e.g. Airbnb or Stripe getting `Filed N certified H-1B LCAs (FY2025)` in the US shard.

- [ ] **Step 6: Commit**

```bash
git add sponsorscope/cli.py site/index.html README.md tests/test_cli.py
git commit -m "feat: enable NL, DK, FI, US, CA and IE sponsor sources; attribute them on the page"
```
