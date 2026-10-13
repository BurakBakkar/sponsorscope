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
  for (const [type, text, weak] of r.badges) chips.append(el("span", { class: `badge ${type}${weak ? " weak" : ""}`, text }));
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
