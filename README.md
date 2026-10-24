# sponsorscope

A nightly-updated, filterable list of job postings that may offer **visa sponsorship**.

**👉 Browse it here: [burakbakkar.github.io/sponsorscope](https://burakbakkar.github.io/sponsorscope/)**

- **Sponsor data:** UK, NL, DK and FI licence registers, plus US (H-1B LCA), CA (positive LMIA) and IE
  (employment permits) sponsorship history. FI is currently behind a bot challenge and shows as "blocked".
- **Postings:** public ATS job-board APIs: Greenhouse, Lever, Ashby, Workable,
  SmartRecruiters, Recruitee and Personio.
- **PhD and master's offers:** university vacancy feeds (RSS 2.0 / 1.0) listed in `seeds/manual.yaml`
  (only the degree offers are kept; feeds on generic hosts like varbi.com take a `#country=XX` suffix), plus any ATS posting whose title reads like one
  (studentship, doctoral candidate, master thesis, …). The site's *Position* filter picks them out.
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
- `weekly-discover` finds new boards. It probes public slug lists
  ([Riley-Dorrington/job-board-aggregator](https://github.com/Riley-Dorrington/job-board-aggregator),
  [ConorsCode/open-jobs-data](https://github.com/ConorsCode/open-jobs-data) and
  [datascry/openroles](https://github.com/datascry/openroles), all MIT) and guesses slugs from sponsor names. Misses back off from 1 week
  to 4 weeks to 12 weeks.
- `smoke` (run manually) hits one real board per ATS, to catch upstream API
  changes.

## One-time setup

Set **Settings → Pages → Source** to "GitHub Actions" before the first nightly
run.

## Development

```bash
uv sync
uv run pytest                    # Python tests
node --test 'site/*.test.js'     # page filter tests
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
- Canada LMIA list: Open Government Licence – Canada. NL, DK, FI, US and IE sources state no licence;
  only derived badges and company names are published.
- City data: [GeoNames](https://www.geonames.org/), CC BY 4.0.
