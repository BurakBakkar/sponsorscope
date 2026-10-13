# sponsorscope — Design Spec

**Date:** 2026-10-13
**Status:** Draft for review

## 1. Purpose

A public, filterable web page listing job postings that are likely to offer
visa sponsorship, for people who need a sponsored work visa to move abroad.

It joins two kinds of public data:

1. **Official government sponsor data**: registers of employers licensed to
   sponsor, and records of employers that have filed for or received sponsorship.
2. **Live job postings** from public applicant-tracking-system (ATS) APIs.

Each posting is labelled for **sponsorship** (yes / no / unknown) and
**language requirements** (e.g. "fluent Dutch required"). A pipeline refreshes
everything nightly on GitHub Actions and publishes a static page to GitHub
Pages.

**Success for v1:** the author uses it for their own job search, and it is
reliable and transparent enough to share publicly. Every label shows the
evidence behind it, and stale sources are visibly flagged.

### Non-goals (v1)

- No LLM classification (rules only; the classifier is swappable later).
- No non-English postings (detected and dropped).
- No user accounts, saved searches, alerts or server backend.
- No historical analytics UI. History is kept in the DB but not surfaced,
  except through `first_seen`.

## 2. Sources

### 2.1 Sponsor data (verified 2026-10-13)

Evidence comes in two kinds, and the page shows them as different badges:

- **licence**: the employer is currently licensed or recognised to sponsor.
  Badge: **"Licensed sponsor"**.
- **history**: the employer has filed for or received sponsorship before.
  The badge states the source-specific measure and period, never a summary
  claim:
  - US: *"Filed 37 certified H-1B LCAs (FY2026)"*
  - CA: *"12 positive LMIAs (2026 Q1)"*
  - IE: *"8 employment permits issued (2026)"*

  A certified LCA is a step before the visa petition, not an approval, so
  "has sponsored" would overstate what the US data shows.

| Plugin | Source | Evidence | Format / access | Cadence | Notes |
|---|---|---|---|---|---|
| `gb` | Home Office *Register of licensed sponsors: workers* | licence | CSV (~11 MB, ~143k rows). URL found via the GOV.UK Content API `details.attachments[0].url` | ~daily | Cols: Organisation Name, Town/City, County, Type & Rating, Route. One row per org×route. OGL v3.0 |
| `nl` | IND *Public register Work* | licence | Single HTML table (~13k rows), no download | monthly | Cols: Organisation, KVK number. "Last updated" date is free text on the page. Licence not stated |
| `dk` | SIRI *Certified companies* (Fast-track) | licence | HTML table (~950 rows), en-GB page | irregular | Cols: Name, CVR no. Danish sort order puts "Aa" last. Licence not stated |
| `fi` | Migri *Certified employers* | licence | Format not confirmed. migri.fi returned 403 to automated requests | weekly | Cols (per search snippets): name, business ID, issue date, expiry date. **Fragile; see §8** |
| `us` | DOL OFLC *LCA Disclosure Data* (H-1B/H-1B1/E-3) | history | XLSX, 80–250 MB, one cumulative file per fiscal year. Links scraped from the Performance Data page (path pattern not stable) | quarterly | These are applications, not approvals. Aggregated on ingest to (employer, FY, certified count) |
| `ca` | ESDC *Positive LMIA Employers List* | history | XLSX via CKAN `package_show` on open.canada.ca | quarterly (lagged) | Title row above the header, footnotes below. OGL-Canada |
| `ie` | DETE *Employment permits issued to companies YYYY* | history | XLSX, year-to-date | monthly | Permit grants, not a licence register |

**Excluded, with reasons (recorded so nobody re-researches them):**

- **Sweden**: the certified-employer scheme ended 15 Dec 2023 (per secondary
  sources), so there is no current list.
- **New Zealand**: accredited employers can only be found through a JS search
  behind Incapsula. There is no bulk download, employers may opt out, and
  enumerating the search likely violates the site's terms. Revisit if INZ
  publishes a dataset.
- **Australia**: no public list of approved sponsors yet. There is a
  sanctioned-sponsors register and a bill to create a public register (status
  unconfirmed). Revisit.
- **Germany, Belgium, Luxembourg**: no comparable list found.

**Version-aware refresh:** before downloading, each plugin checks a cheap
version signal (Content API `updated_at`, CKAN `metadata_modified`, the
"last updated" text on the page, the file name). It skips the download if the
version is unchanged. This keeps the US files (up to 250 MB) to one download
per quarter.

### 2.2 Job postings (verified live 2026-10-13)

| Adapter | List endpoint | Full text in list? | Structured location | Missing-slug response | Notes |
|---|---|---|---|---|---|
| `greenhouse` | `boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true` | yes | free text only (`location.name`, `offices[]`) | 404 | Case-insensitive. One job can have several postings (`internal_job_id`); dedupe on it |
| `lever` | `api.lever.co/v0/postings/{slug}?mode=json` (EU: `api.eu.lever.co`) | yes | `country` (ISO-2), `workplaceType` | 404 | **Case-sensitive slugs.** Probe both hosts. Only `createdAt` (epoch ms) |
| `ashby` | `api.ashbyhq.com/posting-api/job-board/{slug}` | yes | `address.postalAddress.addressCountry`, `isRemote`, `workplaceType` | 404 | Skip `isListed=false`. Country may be a non-country ("European Union") |
| `workable` | `apply.workable.com/api/v1/widget/accounts/{slug}?details=true` | yes (with `details`) | `country`, `city`, `telecommuting`, `locations[].countryCode` | 404 (empty account → 200 `jobs: []`) | Undocumented endpoint, behind Cloudflare |
| `smartrecruiters` | `api.smartrecruiters.com/v1/companies/{id}/postings` (`offset`/`limit≤100`) | **no**, detail call per posting | `location.country` (lowercase ISO-2), `remote`, `hybrid` | **200 empty** (same as a real company with the feed off) | Probe existence via `careers.smartrecruiters.com/{id}` (200 vs 302). Dedupe per-language copies on `refNumber`. Detail calls only for new IDs |
| `recruitee` | `{slug}.recruitee.com/api/offers/` | yes | `country_code`, `remote`, `hybrid`, `on_site` | 404 | **Token required from 10 Feb 2027; see §8** |
| `personio` | `{slug}.jobs.personio.de/xml` | yes (HTML in CDATA) | free text only (`office`) | 404 (HTML) | XML root `<workzag-jobs>`. Only `createdAt` |

**Discovery seeds** (all MIT-licensed; validate every slug by probing before
use):

- `Feashliaa/job-board-aggregator`: per-ATS company JSON, collected from
  Common Crawl
- `ConorsCode/open-jobs-data`: `companies.json` across 9 ATSes, updated daily
- Common Crawl CDX index queries on each ATS's public URL pattern, as an
  optional later seed generator

## 3. Architecture

Python 3.12, managed with `uv`. Single package, CLI-driven, with each pipeline
stage as its own subcommand.

```
sponsorscope/
├── registers/          # one plugin per country; Register protocol → SponsorRecord
│   ├── base.py
│   └── gb.py nl.py dk.py fi.py us.py ca.py ie.py
├── ats/                # one adapter per ATS; ATS protocol
│   ├── base.py         # probe(slug) -> ProbeResult; fetch(slug) -> list[RawPosting]
│   └── greenhouse.py lever.py ashby.py workable.py
│       smartrecruiters.py recruitee.py personio.py
├── discovery/
│   ├── seeds.py        # load seed lists
│   ├── slugs.py        # legal name → candidate slugs
│   └── probe.py        # batched, rate-limited probing; writes boards cache
├── matching/names.py   # name normalisation + (company, country) join
├── geo/country.py      # location → ISO-2 (structured fields, then GeoNames cities15000)
├── classify/
│   ├── base.py         # Classifier protocol → Label
│   ├── lang_detect.py  # English filter (lingua-py)
│   └── rules.py        # sponsorship + language-requirement rules
├── http.py             # shared async client: per-host limits, retries, UA
├── store/db.py         # SQLite schema, migrations, upserts
├── export/shards.py    # DB → site/data/*.json.gz + index.json
├── report.py           # run report (last_run.json)
└── cli.py              # typer: registers | match | discover | crawl | classify | export | smoke
overrides.yaml          # manual match / non-match overrides
site/                   # static page (vanilla JS, no build step)
.github/workflows/
├── nightly.yml
├── weekly-discover.yml
└── smoke.yml           # manual dispatch; live checks against real sources
```

**Boundaries:**

- `registers/` and `ats/` are pure I/O + parsing. They don't know about each
  other or the DB, and they emit typed dataclasses.
- `matching/` is the only place where sponsor data meets ATS data.
- `classify/` takes posting text and returns a `Label`. An LLM classifier
  later is a new class that implements the same protocol.
- `store/` owns the schema. `export/` is a disposable view and can be rebuilt
  from the DB at any time.
- Interfaces use `typing.Protocol`, so test fakes need no inheritance.

**Key libraries:** `httpx` (async HTTP), `selectolax` (HTML), `lxml` (XML),
`python-calamine` (fast XLSX reading for the large US files), `rapidfuzz`
(name similarity), `lingua-language-detector`, `typer`, `pyyaml`. Tests use
`pytest` and `respx`.

## 4. Data model (SQLite)

```sql
sponsors (
  id INTEGER PRIMARY KEY,
  country TEXT NOT NULL,          -- ISO-2
  source TEXT NOT NULL,           -- plugin name
  evidence TEXT NOT NULL,         -- 'licence' | 'history'
  legal_name TEXT NOT NULL,
  norm_name TEXT NOT NULL,
  registry_id TEXT,               -- KVK / CVR / FI business ID when present
  city TEXT,
  route TEXT,                     -- e.g. 'Skilled Worker', 'H-1B'
  filings INTEGER,                -- history sources: count of certified filings/permits
  first_seen TEXT NOT NULL,
  last_seen TEXT NOT NULL,
  UNIQUE (source, norm_name, route)
)

source_versions (source TEXT PRIMARY KEY, version TEXT, fetched_at TEXT)

companies (id INTEGER PRIMARY KEY, display_name TEXT, norm_name TEXT UNIQUE)

boards (
  ats TEXT, slug TEXT, company_id INTEGER,
  status TEXT,                    -- 'hit' | 'miss' | 'gone'
  origin TEXT,                    -- 'seed' | 'guess'
  consecutive_failures INTEGER DEFAULT 0,
  last_probed TEXT, next_probe_at TEXT,
  PRIMARY KEY (ats, slug)
)

sponsor_matches (
  sponsor_id INTEGER, company_id INTEGER,
  method TEXT,                    -- 'exact' | 'normalised' | 'manual'
  score REAL,
  PRIMARY KEY (sponsor_id, company_id)
)

postings (
  id TEXT PRIMARY KEY,            -- '{ats}:{slug}:{job_id}'
  ats TEXT, slug TEXT, company_id INTEGER,
  title TEXT, url TEXT, location_raw TEXT,
  country TEXT,                   -- ISO-2 or NULL (shown as 'Unknown location')
  remote TEXT,                    -- 'remote' | 'hybrid' | 'onsite' | NULL
  posted_at TEXT, content_hash TEXT, lang TEXT,
  first_seen TEXT, last_seen TEXT, active INTEGER
)

labels (
  posting_id TEXT, content_hash TEXT, classifier_version TEXT,
  sponsorship TEXT,               -- 'yes' | 'no' | 'unknown'
  mixed INTEGER DEFAULT 0,        -- 1 when yes- and no-rules both matched
  languages_required TEXT,        -- JSON list of ISO-639-1 codes
  evidence TEXT,                  -- JSON list of matched phrases
  PRIMARY KEY (posting_id, content_hash, classifier_version)
)
```

**Rules:**

- **Descriptions are not stored.** Every nightly run re-fetches each known
  board, so the text is in memory for the run. Only `content_hash` (sha256 of
  the normalised text) is kept. This keeps the DB small enough to download and
  upload every night.
- A posting is (re)classified when no label exists for
  `(posting_id, content_hash, classifier_version)`. Bumping
  `classify.rules.VERSION` re-labels everything on the next run.
- A posting's **sponsor badges** come from matched sponsors where
  `sponsor.country == posting.country`. Remote postings with
  `country IS NULL` get no badge, because the visa country is unknown.
- Seed slugs are recorded with `origin='seed'`. If the company from a seed
  doesn't match any sponsor, its postings are still shown, relying on the
  posting-text label alone.

## 5. Matching

The core problem is joining register legal names ("Booking.com B.V.") to ATS
companies (slug `booking`, display name "Booking.com").

1. **Normalise** both sides:
   - lowercase, strip accents, `&` → `and`
   - drop punctuation
   - remove legal suffixes (`ltd`, `limited`, `plc`, `llp`, `b.v.`, `bv`,
     `n.v.`, `gmbh`, `inc`, `llc`, `corp`, `a/s`, `aps`, `oy`, `oyj`, `ab`)
   - remove trailing qualifiers (`uk`, `nederland`, `europe`, `international`,
     `holding(s)`, `group`, `services`)
   - collapse whitespace
2. **Exact match** on `norm_name` → `method='exact'`.
3. **Normalised match** (compare with spaces removed, plus a rapidfuzz
   `token_sort_ratio ≥ 95`) → `method='normalised'`, but **only when the
   candidate is unique**. If several sponsors are candidates, there is no
   automatic match.
4. **Short-name guard:** names that are 4 characters or fewer after
   normalisation never auto-match. They need an `overrides.yaml` entry.
5. **`overrides.yaml`** forces matches (`method='manual'`) or forbids them
   (e.g. small UK "Apple Ltd" ≠ Apple Inc).

**Slug guessing (discovery):** from a sponsor's normalised name, generate
candidates:

- the name joined with no separator, with `-`, and with `_`
- the first token, but only if it is longer than 4 characters

Probe each candidate on every ATS. Lever is case-sensitive, so probe Lever with
the lowercase form only. Slugs with other casing must come from seeds.

## 6. Pipelines

### 6.1 Nightly (`nightly.yml`, cron `0 3 * * *` UTC)

1. Download the latest `sponsorscope.db` from the `db-latest` GitHub Release.
   On the first run, create an empty DB.
2. `registers`: for each plugin, check the version and refresh if it changed.
   Upsert sponsors. Each plugin is isolated.
3. `match`: match new or changed sponsors and apply `overrides.yaml`.
4. `crawl`: fetch every board with `status='hit'`, isolated per board.
5. For each posting:
   - resolve the country
   - detect the language and drop non-English postings
   - classify if it has no label for the current hash and version
6. Deactivate postings that are missing from a **successfully fetched** board.
7. `export`: write `site/data/index.json` and `site/data/{cc}.json.gz`.
8. Run `PRAGMA integrity_check`, then upload the DB to the release. Keep 7
   dated snapshots.
9. Deploy `site/` to GitHub Pages.
10. Commit `last_run.json`. This doubles as the keep-alive commit, because
    GitHub disables scheduled workflows after 60 days without repo activity.

### 6.2 Weekly discovery (`weekly-discover.yml`, cron `0 4 * * 0`)

Steps 1–3, then:

- Load seeds.
- Generate slug candidates for sponsors that have no board yet.
- Probe the candidates that are due (`next_probe_at ≤ now`), in rate-limited
  batches with a cap per run.
- Back off misses: 1 week → 4 weeks → 12 weeks.
- Upload the DB.

### 6.3 Both workflows

- `concurrency: { group: sponsorscope-db, cancel-in-progress: false }`.
- No secrets are required beyond the default `GITHUB_TOKEN`, with
  `contents: write`, `pages: write` and `id-token: write`.

## 7. Classification (rules, v1)

**Language filter:** `lingua` on title + description. Keep the posting only if
English is detected with confidence ≥ 0.8.

**Sponsorship label**, using case-insensitive phrase/regex families. Each
family is a named rule in `rules.py`:

- `no` — "unable to (offer|provide) (visa )?sponsorship", "no visa
  sponsorship", "must (already )?have the right to work in", "sponsorship is
  not available", "not able to sponsor", "without (the need for )?sponsorship".
- `yes` — "visa sponsorship (is )?(available|offered|provided)", "we (can|will|
  are able to) sponsor", "relocation and visa support", "skilled worker visa
  sponsorship", "highly skilled migrant (visa|permit)", "kennismigrant".
- If both match → `unknown` with `mixed = true`, and both sets of evidence are
  recorded. The page shows a "mixed signals" chip. Reason: the default view
  hides `no`, so a false `no` hides a real opportunity. A conflict (e.g. "we
  sponsor senior roles but not internships") is left for a person to read.
- If neither matches → `unknown`.

**Language requirements:** detect "(fluent|fluency in|native|proficient|
professional working proficiency in|C1|C2|B2) … {language}" and "{language}
(is )?(required|essential|a must|mandatory)". Phrasing like "is a plus" or
"nice to have" doesn't count. Languages: Dutch, German, French, Danish,
Finnish, Swedish, Norwegian, Spanish, Italian, Portuguese, Polish, Japanese,
Mandarin. English itself is never recorded.

**Evidence:** every label stores the matched phrases (up to 160 characters of
context each), and the page shows them.

## 8. Error handling and politeness

**Never wipe good data because of a failure:**

- Each register plugin and each board fetch is isolated. A failure is recorded
  in the run report and that source's existing rows are untouched.
- Sponsors are retired (`last_seen` stops advancing; export ignores rows not
  seen in the source's latest successful version) only through a successful
  fetch of their source.
- Postings are deactivated only when their board was fetched successfully.

**Sanity guards:**

- If a register's row count shrinks by more than 20% compared with the
  previous version, the plugin fails and the old data is kept.
- If more than 50% of an ATS's boards fail in one run, it is treated as an ATS
  outage: nothing from that ATS is deactivated.

**HTTP (`http.py`):**

- Per-host concurrency (default 4) and a token-bucket rate limit (default
  5 req/s, configurable per adapter).
- Exponential backoff with jitter on 429/5xx, honouring `Retry-After`. Up to 4
  retries. Explicit 30 s timeouts.
- `User-Agent: sponsorscope/<version> (+https://github.com/BurakBakkar/sponsorscope)`.

**Board lifecycle:** a board that returns 404 in 3 consecutive runs becomes
`gone` and goes back to discovery's backoff schedule.

**Known fragile sources:**

- **Finland (Migri)** blocks automated requests (403). Mitigation: a single
  polite request per week. If it is still blocked, the plugin reports
  `blocked` in the run report and the page notes FI as unavailable. No bypass
  attempts.
- **Recruitee** requires `X-Careers-Sites-Token` from 2027-02-10. Before that
  date: check whether the per-company XML feed (reported as exempt) is enough.
  If it isn't, drop the adapter. Tracked as an open item (§11).
- **Workable** uses an undocumented endpoint behind Cloudflare. The smoke
  workflow catches breakage.

**Run report → visible staleness:**

- `last_run.json` records, per source: status (`ok|unchanged|failed|blocked`),
  version, row count, duration and an error snippet.
- The page footer shows the freshness of each source, e.g. "NL register:
  failed, showing data from 2026-10-05".

**Workflow outcomes:**

- Partial source failures produce a warning annotation, and the page still
  deploys.
- Core failures (DB corrupt, export error) fail the job. Pages keeps the
  previous deploy, and GitHub emails the owner.

## 9. Published page

**Static and dependency-free:** `site/index.html`, `site/app.js`,
`site/style.css`.

- On load, the page fetches `data/index.json`. This holds per-country counts,
  the company list, source freshness and the build time.
- It then fetches the shards for the selected countries
  (`data/{cc}.json.gz`, decompressed with `DecompressionStream`). "All
  countries" loads every shard.
- Shard records are compact arrays (field order in `index.json`):
  `id, title, company, url, country, remote, posted_at, first_seen,
  sponsorship, mixed, langs, evidence, badges, ats`.

**Filters:**

- Country (multi-select)
- Sponsorship: yes / unknown / no (default: yes + unknown)
- Badges: licensed sponsor / sponsorship history (any count)
- Show only / hide "mixed signals" postings
- Hide postings that require a language (multi-select of languages)
- Free-text search over title and company
- Company
- Remote: remote / hybrid / onsite
- Posted within N days
- ATS

**Filter state** is kept in the URL query string, so searches can be shared.

**Each row shows:**

- the title, linked to the original posting
- the company
- the location
- badges
- the sponsorship label, with an expandable "why" that shows the evidence
  phrases
- language chips

**Footer:**

- source freshness, taken from `last_run.json`
- attribution: "Contains public sector information licensed under the Open
  Government Licence v3.0" (UK) and the OGL-Canada notice
- a disclaimer: "Not legal advice. A sponsor licence does not guarantee a
  given role is sponsored."

**Size budget:** each shard ≤ 5 MB gzipped. The export logs a warning above
that. If the budget is exceeded regularly, revisit the format (approach B:
Parquet + DuckDB-WASM).

## 10. Testing

**Unit tests (no network; `pytest` + `respx`):**

- **Register parsers:** trimmed real fixtures in `tests/fixtures/registers/`,
  one per plugin. These include the known quirks: leading spaces, doubled
  quotes, title and footnote rows, Danish "Aa" ordering.
- **ATS adapters:** recorded JSON/XML fixtures, covering:
  - pagination (SmartRecruiters)
  - list → detail flow (SmartRecruiters)
  - dedupe (Greenhouse `internal_job_id`, SmartRecruiters `refNumber`)
  - probe semantics per ATS: 404 vs "200 empty"
- **Matching:** a table-driven file `tests/test_matching.py` covering:
  - suffix stripping, accents, `&`
  - the short-name guard
  - uniqueness rule
  - overrides
  - known pairs, e.g. Booking.com B.V. ↔ booking, Apple Retail UK Limited ↛
    apple

  Each matching bug found later adds a row.
- **Geo:** a table of messy location strings → ISO-2 or NULL.
- **Classifier:** a labelled corpus `tests/fixtures/labels.yaml` with ≥ 60
  real English snippets covering yes/no/unknown and language requirements.
  The test computes precision/recall per class and fails below the thresholds:
  `no` precision ≥ 0.98 (it's the label hidden by default, so false
  positives cost the most), `yes` precision ≥ 0.95, recall ≥ 0.80 for both. This corpus is also the
  evaluation set for any future LLM classifier.

**Integration test:** a full `registers → match → crawl → classify → export`
run against `respx`-mocked HTTP and a temp DB. It asserts the §8 guarantees:

- a failed register keeps its rows
- a failed board doesn't deactivate its postings
- the 20% shrink guard trips
- the ATS-outage rule holds
- re-running with an unchanged DB and sources is a no-op for labels

**Frontend:** the filter and serialisation functions in `app.js` are pure.
A small `node --test` file runs them against a fixture shard. No browser
automation in v1.

**Live smoke (`smoke.yml`, manual dispatch):** hits one known board per ATS
plus the version check of each register. It fails loudly if a schema changes.

## 11. Open items (with v1 defaults)

| # | Item | v1 default |
|---|---|---|
| 1 | NL / DK / FI licence terms are not stated | Publish only derived badges + company names (no raw register dumps); attribute the source. Ask the IND/SIRI if the project gets traction |
| 2 | Recruitee token from 2027-02-10 | Ship the adapter; before Feb 2027 evaluate the XML feed, otherwise remove it |
| 3 | US LCA record layout not inspected | First implementation task for `us.py`: read the FY2026 layout PDF and pin the column names in a fixture |
| 4 | Finland format unknown (403) | Implement the plugin after one manual check of the page format; until then it is marked `blocked` |
| 5 | Repo URL in the User-Agent assumes `github.com/BurakBakkar/sponsorscope` | Change it if the repo lives elsewhere |
| 6 | Australia public sponsor register (bill pending) | Re-check quarterly; add a plugin when it's live |
