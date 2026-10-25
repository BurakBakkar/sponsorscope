// Pure filtering/state helpers for the sponsorscope page (tested with node --test).

export const DEFAULT_STATE = {
  countries: [], sponsorship: ["yes", "unknown"], badges: [], langs: [],
  q: "", company: "", remote: [], days: 0, ats: [], mixed: "any", levels: [], industries: [],
};
const LIST_KEYS = ["countries", "sponsorship", "badges", "langs", "remote", "ats", "levels", "industries"];
const MIXED_VALUES = ["any", "only", "hide"];
const DAY_MS = 86_400_000;

export const LANG_LABELS = {
  nl: "Dutch", de: "German", fr: "French", da: "Danish", fi: "Finnish", sv: "Swedish",
  no: "Norwegian", es: "Spanish", it: "Italian", pt: "Portuguese", pl: "Polish",
  ja: "Japanese", zh: "Chinese",
};
const REGION_NAMES = new Intl.DisplayNames(["en"], { type: "region" });

export function countryName(cc) {
  if (!cc || cc === "XX") return "Unknown location";
  try { return REGION_NAMES.of(cc) ?? cc; } catch { return cc; } // malformed code: show it raw
}

export const LEVEL_LABELS = { phd: "PhD", masters: "Master's", job: "Job" };

export const INDUSTRY_LABELS = { biotech: "Biotech & pharma", other: "Other industries" };

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
    if (state.langs.length && !r.langs.every((l) => state.langs.includes(l))) return false;
    if (state.levels.length && !state.levels.includes(r.level ?? "job")) return false;
    if (state.industries.length && !state.industries.includes(r.industry ?? "other")) return false;
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

// ---- display helpers ----

const FILLER = new Set(["of", "the", "and", "for", "de", "der", "van", "&", "-", "–"]);

export function initials(name) {
  const words = (name || "").split(/\s+/).filter((w) => w && !FILLER.has(w.toLowerCase()));
  return words.slice(0, 2).map((w) => w[0].toUpperCase()).join("") || "?";
}

export function hueFor(name) {
  let h = 0;
  for (const ch of name || "") h = (h * 31 + ch.codePointAt(0)) >>> 0;
  return h % 360;
}

export function relativeDate(iso, now = new Date()) {
  if (!iso) return "";
  const days = Math.round((Date.parse(now.toISOString().slice(0, 10)) - Date.parse(iso.slice(0, 10))) / DAY_MS);
  if (days <= 0) return "today";
  if (days === 1) return "yesterday";
  if (days < 14) return `${days} days ago`;
  if (days < 56) return `${Math.round(days / 7)} weeks ago`;
  return new Date(iso.slice(0, 10)).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" });
}

// Display-only highlight of the words the sponsorship rules key on; classification itself happens in Python.
const HIGHLIGHT = /\b(?:visas?|sponsor\w*|work permits?|residence permits?|relocation|right to work|immigration)\b/gi;

export function evidenceParts(snippet) {
  // Evidence is a fixed-width window, so it usually starts and ends mid-word: trim to whole words.
  let text = snippet.replace(/\s+/g, " ").trim();
  const head = text.indexOf(" ");
  const tail = text.lastIndexOf(" ");
  if (head > 0 && tail > head) text = `…${text.slice(head + 1, tail)}…`;
  const parts = [];
  let last = 0;
  for (const m of text.matchAll(HIGHLIGHT)) {
    if (m.index > last) parts.push({ text: text.slice(last, m.index), strong: false });
    parts.push({ text: m[0], strong: true });
    last = m.index + m[0].length;
  }
  if (last < text.length) parts.push({ text: text.slice(last), strong: false });
  return parts;
}

export function chipLabel(label, selected) {
  if (!selected.length) return label;
  return selected.length === 1 ? `${label}: ${selected[0]}` : `${label}: ${selected[0]} +${selected.length - 1}`;
}
