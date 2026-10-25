import {
  DEFAULT_STATE, INDUSTRY_LABELS, LANG_LABELS, LEVEL_LABELS, chipLabel, countryName, evidenceParts, filterRows, hueFor, initials,
  parseState, relativeDate, safeUrl, serializeState, shardsFor, sourceLine, toObjects,
} from "./filters.js";

const PAGE_SIZE = 200;
const SPONSORSHIP_TEXT = { yes: "Mentions sponsorship", no: "Rules out sponsorship", unknown: "Sponsorship not mentioned" };
const BADGE_TEXT = { licence: "Licensed sponsor", history: "Sponsorship history" };
const REMOTE_TEXT = { remote: "Remote", hybrid: "Hybrid", onsite: "On-site", unknown: "Not stated" };
const DAYS_TEXT = { 0: "Any time", 1: "Last 24 hours", 7: "Last 7 days", 30: "Last 30 days" };
const MIXED_TEXT = { any: "Mixed signals: show", hide: "Mixed signals: hide", only: "Mixed signals: only" };
const ATS_TEXT = { rss: "University feeds", jobtech: "Arbetsförmedlingen (SE)", oracle: "Oracle Recruiting",
  workday: "Workday", smartrecruiters: "SmartRecruiters" };
const shardCache = new Map();
let index = null;
let state = parseState(location.search);
let current = [];
let visible = PAGE_SIZE;
let token = 0;
let chips = [];

const $ = (selector) => document.querySelector(selector);
const titleCase = (s) => s.charAt(0).toUpperCase() + s.slice(1);

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

// ---- filter chips: each is a <details> that opens a small panel ----

function checkboxList(key, options, { searchable = false } = {}) {
  const list = el("div", { class: "options" });
  const rows = options.map(([value, label, count]) => {
    const input = el("input", { type: "checkbox", value });
    input.checked = state[key].includes(value);
    input.addEventListener("change", () => {
      state[key] = input.checked ? [...state[key], value] : state[key].filter((v) => v !== value);
      update();
    });
    const row = el("label", { class: "option" }, input, el("span", { text: label }));
    if (count !== undefined) row.append(el("span", { class: "count", text: count.toLocaleString() }));
    row.dataset.label = label.toLowerCase();
    return row;
  });
  list.append(...rows);
  if (!searchable) return list;
  const find = el("input", { type: "search", class: "find", placeholder: "Find…", "aria-label": "Find an option" });
  find.addEventListener("input", () => {
    const needle = find.value.trim().toLowerCase();
    for (const row of rows) row.hidden = Boolean(needle) && !row.dataset.label.includes(needle);
  });
  return el("div", {}, find, list);
}

function select(label, key, options, parse = String) {
  const node = el("select", { "aria-label": label },
    ...options.map(([v, t]) => el("option", { value: String(v), text: t })));
  node.value = String(state[key]);
  node.addEventListener("change", () => { state[key] = parse(node.value); update(); });
  return el("label", { class: "field" }, el("span", { text: label }), node);
}

function chip(label, body, summarise) {
  const summary = el("summary", { text: label });
  const details = el("details", { class: "chip" }, summary, el("div", { class: "panel" }, body));
  details.addEventListener("toggle", () => {
    if (details.open) for (const other of chips) if (other.details !== details) other.details.open = false;
  });
  chips.push({ details, summary, label, summarise });
  return details;
}

function refreshChips() {
  for (const c of chips) {
    const selected = c.summarise();
    c.summary.textContent = chipLabel(c.label, selected);
    c.details.classList.toggle("on", selected.length > 0);
  }
}

function countries() {
  return Object.entries(index.countries)
    .map(([cc, n]) => [cc, countryName(cc), n])
    .sort(([a, x], [b, y]) => (a === "XX") - (b === "XX") || x.localeCompare(y)); // Unknown last
}

const isDefault = (key) => JSON.stringify(state[key]) === JSON.stringify(DEFAULT_STATE[key]);
const labelled = (key, texts) => (isDefault(key) ? [] : state[key].map((v) => texts[v] ?? v));

function buildFilters() {
  chips = [];
  const names = Object.fromEntries(countries().map(([cc, name]) => [cc, name]));
  $("#chips").replaceChildren(
    chip("Position", checkboxList("levels", Object.entries(LEVEL_LABELS)), () => labelled("levels", LEVEL_LABELS)),
    chip("Industry", checkboxList("industries", Object.entries(INDUSTRY_LABELS)),
      () => labelled("industries", INDUSTRY_LABELS)),
    chip("Country", checkboxList("countries", countries(), { searchable: true }), () => labelled("countries", names)),
    chip("Sponsor register", checkboxList("badges", Object.entries(BADGE_TEXT)), () => labelled("badges", BADGE_TEXT)),
    chip("Sponsorship", checkboxList("sponsorship", Object.entries(SPONSORSHIP_TEXT)),
      () => labelled("sponsorship", SPONSORSHIP_TEXT)),
    chip("Languages I speak", checkboxList("langs", Object.entries(LANG_LABELS), { searchable: true }),
      () => labelled("langs", LANG_LABELS)),
    chip("More", el("div", { class: "more" },
      select("Company", "company", [["", "Any company"], ...index.companies.map((c) => [c, c])]),
      select("Posted within", "days", Object.entries(DAYS_TEXT), Number),
      select("Mixed signals", "mixed", Object.entries(MIXED_TEXT)),
      el("p", { class: "group", text: "Work mode" }), checkboxList("remote", Object.entries(REMOTE_TEXT)),
      el("p", { class: "group", text: "Source" }),
      checkboxList("ats", index.ats.map((a) => [a, ATS_TEXT[a] ?? titleCase(a)]))),
    () => [state.company, state.days ? DAYS_TEXT[state.days] : "", state.mixed !== "any" ? MIXED_TEXT[state.mixed] : "",
      ...labelled("remote", REMOTE_TEXT), ...labelled("ats", ATS_TEXT)].filter(Boolean)),
  );
  $("#search").value = state.q;
  refreshChips();
}

// ---- active filter tags, each removable ----

function activeTags() {
  const tags = [];
  const names = Object.fromEntries(countries().map(([cc, name]) => [cc, name]));
  const lists = { levels: LEVEL_LABELS, industries: INDUSTRY_LABELS, countries: names, badges: BADGE_TEXT, sponsorship: SPONSORSHIP_TEXT,
    langs: LANG_LABELS, remote: REMOTE_TEXT, ats: ATS_TEXT };
  for (const [key, texts] of Object.entries(lists)) {
    if (isDefault(key)) continue;
    for (const v of state[key]) {
      const prefix = key === "langs" ? "Speaks " : "";
      tags.push([`${prefix}${texts[v] ?? v}`, () => { state[key] = state[key].filter((x) => x !== v); }]);
    }
  }
  if (state.q) tags.push([`“${state.q}”`, () => { state.q = ""; }]);
  if (state.company) tags.push([state.company, () => { state.company = ""; }]);
  if (state.days) tags.push([DAYS_TEXT[state.days], () => { state.days = 0; }]);
  if (state.mixed !== "any") tags.push([MIXED_TEXT[state.mixed], () => { state.mixed = "any"; }]);
  return tags;
}

function renderActive() {
  const tags = activeTags().map(([text, remove]) => {
    const button = el("button", { type: "button", class: "tag", "aria-label": `Remove filter ${text}` },
      el("span", { text }), el("span", { "aria-hidden": "true", text: "×" }));
    button.addEventListener("click", () => { remove(); buildFilters(); update(); });
    return button;
  });
  if (serializeState(state)) {
    const reset = el("button", { type: "button", class: "reset", text: "Clear all" });
    reset.addEventListener("click", () => { state = structuredClone(DEFAULT_STATE); buildFilters(); update(); });
    tags.push(reset);
  }
  $("#active").replaceChildren(...tags);
}

// ---- results ----

function pill(cls, text) {
  return el("span", { class: `pill ${cls}`, text });
}

function quoteParts(snippet) {
  return evidenceParts(snippet).map((p) => (p.strong ? el("strong", { text: p.text }) : p.text));
}

function evidence(r) {
  if (!r.evidence.length || r.sponsorship === "unknown") return [];
  const quote = el("blockquote", { class: "evidence" },
    el("span", { class: "why", text: `Why “${SPONSORSHIP_TEXT[r.sponsorship]}”: ` }), ...quoteParts(r.evidence[0]));
  if (r.evidence.length === 1) return [quote];
  const more = el("details", { class: "more-evidence" },
    el("summary", { text: `${r.evidence.length - 1} more quote${r.evidence.length > 2 ? "s" : ""}` }),
    ...r.evidence.slice(1).map((e) => el("blockquote", { class: "evidence" }, ...quoteParts(e))));
  return [quote, more];
}

function industryEvidence(r) {
  if (r.industry !== "biotech" || !r.industry_evidence?.length) return [];
  return [el("details", { class: "more-evidence" },
    el("summary", { text: `Why “${INDUSTRY_LABELS.biotech}”` }),
    ...r.industry_evidence.map((e) => el("blockquote", { class: "evidence" }, ...quoteParts(e))))];
}

function renderRow(r) {
  const href = safeUrl(r.url);
  const title = href
    ? el("a", { href, target: "_blank", rel: "noopener noreferrer", text: r.title })
    : el("span", { text: r.title });
  const pills = el("div", { class: "pills" });
  if (r.level) pills.append(pill(`level ${r.level}`, LEVEL_LABELS[r.level] ?? r.level));
  if (r.industry === "biotech") pills.append(pill("industry", INDUSTRY_LABELS.biotech));
  for (const [type, text, weak] of r.badges) pills.append(pill(`badge ${type}${weak ? " weak" : ""}`, text));
  pills.append(pill(`label ${r.sponsorship}`, SPONSORSHIP_TEXT[r.sponsorship]));
  if (r.mixed) pills.append(pill("label mixed", "Mixed signals"));
  for (const lang of r.langs) pills.append(pill("lang", `Requires ${LANG_LABELS[lang] ?? lang}`));
  const meta = [r.company, countryName(r.country), r.remote ? REMOTE_TEXT[r.remote] : "",
    relativeDate(r.posted_at ?? r.first_seen)];
  const logo = el("div", { class: "logo", "aria-hidden": "true", text: initials(r.company) });
  logo.style.setProperty("--hue", hueFor(r.company));
  return el("li", { class: "card" }, logo, el("div", { class: "body" },
    el("h2", {}, title), el("p", { class: "meta", text: meta.filter(Boolean).join(" · ") }), pills, ...evidence(r), ...industryEvidence(r)));
}

function render() {
  $("#summary").textContent = `${current.length.toLocaleString()} posting${current.length === 1 ? "" : "s"}`;
  $("#results").replaceChildren(...current.slice(0, visible).map(renderRow));
  $("#more").hidden = current.length <= visible;
  renderActive();
  refreshChips();
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

function closeChipsOnOutsideClickOrEscape() {
  document.addEventListener("click", (event) => {
    for (const c of chips) if (c.details.open && !c.details.contains(event.target)) c.details.open = false;
  });
  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape") return;
    for (const c of chips) {
      if (c.details.open) { c.details.open = false; c.summary.focus(); }
    }
  });
}

async function main() {
  const resp = await fetch("data/index.json");
  if (!resp.ok) {
    $("#summary").textContent = "No data published yet.";
    return;
  }
  index = await resp.json();
  buildFilters();
  closeChipsOnOutsideClickOrEscape();
  $("#search").addEventListener("input", (event) => { state.q = event.target.value; update(); });
  $("#sources").replaceChildren(...Object.entries(index.sources).map(([name, info]) => el("li", { text: sourceLine(name, info) })));
  $("#more").addEventListener("click", () => { visible += PAGE_SIZE; render(); });
  await update();
}

main();
