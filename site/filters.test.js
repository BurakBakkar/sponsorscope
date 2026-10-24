import { test } from "node:test";
import assert from "node:assert/strict";
import {
  DEFAULT_STATE, chipLabel, countryName, evidenceParts, filterRows, hueFor, initials, parseState, relativeDate, safeUrl, serializeState, shardsFor, sourceLine, toObjects,
} from "./filters.js";

const FIELDS = ["id", "title", "company", "url", "country", "remote", "posted_at", "first_seen",
  "sponsorship", "mixed", "langs", "evidence", "badges", "ats", "level"];
const ROWS = toObjects(FIELDS, [
  ["greenhouse:a:1", "Backend Engineer", "Acme", "https://x/1", "GB", "remote", "2026-10-10", "2026-10-10T03:00:00+00:00", "yes", false, [], ["We offer visa sponsorship"], [["licence", "Licensed sponsor (UK)"]], "greenhouse", "phd"],
  ["greenhouse:a:2", "Data Analyst", "Acme", "https://x/2", "GB", null, "2026-09-01", "2026-09-01T03:00:00+00:00", "no", false, [], [], [["licence", "Licensed sponsor (UK)"]], "greenhouse", null],
  ["lever:b:3", "Product Designer", "Beta", "https://x/3", "NL", "hybrid", null, "2026-10-12T03:00:00+00:00", "unknown", true, ["nl"], [], [], "lever", "masters"],
  ["lever:b:4", "Support Agent", "Beta", "https://x/4", null, "onsite", "2026-10-11", "2026-10-11T03:00:00+00:00", "unknown", false, [], [], [], "lever", null],
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
test("language filter hides postings requiring a language the user doesn't speak", () => {
  assert.deepEqual(run({ langs: ["nl"] }), ["greenhouse:a:1", "lever:b:3", "lever:b:4"]);
  assert.deepEqual(run({ langs: ["de"] }), ["greenhouse:a:1", "lever:b:4"]);
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

test("countryName spells out ISO codes", () => {
  assert.equal(countryName("GB"), "United Kingdom");
  assert.equal(countryName("NL"), "Netherlands");
  assert.equal(countryName("XX"), "Unknown location");
  assert.equal(countryName(null), "Unknown location");
  assert.equal(countryName("1"), "1");
});

test("position filter treats postings without a level as jobs", () => {
  assert.deepEqual(run({ levels: ["phd"] }), ["greenhouse:a:1"]);
  assert.deepEqual(run({ levels: ["phd", "masters"] }), ["greenhouse:a:1", "lever:b:3"]);
  assert.deepEqual(run({ levels: ["job"] }), ["lever:b:4"]);
});

test("initials skip filler words and cap at two letters", () => {
  assert.equal(initials("Delft University of Technology"), "DU");
  assert.equal(initials("the Francis Crick Institute"), "FC");
  assert.equal(initials("Bosch Group"), "BG");
  assert.equal(initials("ZEISS"), "Z");
  assert.equal(initials(""), "?");
});

test("hueFor is stable per name and within 0..359", () => {
  assert.equal(hueFor("Bosch Group"), hueFor("Bosch Group"));
  assert.notEqual(hueFor("Bosch Group"), hueFor("Airbus"));
  for (const name of ["a", "Airbus", "Technical University of Denmark"]) {
    const h = hueFor(name);
    assert.ok(Number.isInteger(h) && h >= 0 && h < 360);
  }
});

test("relativeDate", () => {
  const now = new Date("2026-10-24T12:00:00Z");
  assert.equal(relativeDate("2026-10-24", now), "today");
  assert.equal(relativeDate("2026-10-23", now), "yesterday");
  assert.equal(relativeDate("2026-10-19", now), "5 days ago");
  assert.equal(relativeDate("2026-10-01", now), "3 weeks ago");
  assert.equal(relativeDate("2026-07-01", now), "1 Jul 2026");
  assert.equal(relativeDate(null, now), "");
});

test("evidenceParts trims to word edges and marks sponsorship words", () => {
  const parts = evidenceParts("ng date. The University is unable to sponsor employment visas for this vac");
  assert.equal(parts.map((p) => p.text).join(""), "…date. The University is unable to sponsor employment visas for this…");
  assert.deepEqual(parts.filter((p) => p.strong).map((p) => p.text), ["sponsor", "visas"]);
});

test("chipLabel summarises the selection", () => {
  assert.equal(chipLabel("Country", []), "Country");
  assert.equal(chipLabel("Country", ["Netherlands"]), "Country: Netherlands");
  assert.equal(chipLabel("Country", ["Netherlands", "Denmark", "Finland"]), "Country: Netherlands +2");
});
