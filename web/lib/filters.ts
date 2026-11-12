// Dashboard filters <-> URL query, so a filtered view can be bookmarked. Shared by the server
// (SQL in db.ts) and the filter panel. Unknown or out-of-range values fall back to the default.

export const ROLES = {
  swe: "SWE/SDE",
  fullstack: "Full-Stack",
  backend: "Backend",
  frontend: "Frontend",
  cloud: "Cloud/DevOps/SRE",
  fde: "Forward Deployed",
  ml: "ML/AI",
  other: "Other",
} as const;
export type Role = keyof typeof ROLES;

export const DAYS = [1, 3, 7, 30] as const; // "last 24h / 3 days / 7 days / 30 days"
export const MAX_YEARS = [1, 2, 3, 4] as const;
export const MIN_FILINGS = [10, 50, 100, 500, 1000] as const;
export const TIERS = [1, 2, 3] as const;
export const SORTS = { // short: the sort menu shares a row with "Filters" on phones
  fit: "Fit score",
  posted: "Posted",
  found: "Found",
  company: "Company",
  filings: "H-1B filings",
} as const;
export type Sort = keyof typeof SORTS;

export type Filters = {
  roles: Role[];
  posted: number | null; // days
  found: number | null;
  minFit: number; // 0-100
  hideUnscored: boolean;
  companies: string[]; // include only these
  excluded: string[]; // never these
  location: string; // state or city text
  remote: boolean;
  sponsorsOnly: boolean;
  minFilings: number | null;
  maxYears: number | null;
  hideCap: boolean; // jobs flagged "exp cap"
  hideClearance: boolean; // jobs flagged "clearance preferred"
  resume: "ai" | "general" | null;
  tiers: number[];
  sort: Sort;
  dir: "asc" | "desc";
};

type Params = { get(name: string): string | null; getAll(name: string): string[] };

/** New and Backlog sort by fit (best first); the other tabs by when Recon found the job. */
export function defaultSort(tab: string): Sort {
  return tab === "new" || tab === "backlog" ? "fit" : "found";
}

/** Company reads A→Z; everything else best / newest / most first. */
export function defaultDir(sort: Sort): "asc" | "desc" {
  return sort === "company" ? "asc" : "desc";
}

// "Load more": the list grows in pages of PAGE_SIZE, up to MAX_LIMIT
export const PAGE_SIZE = 500;
export const MAX_LIMIT = 5000;

/** ?limit=1000 -> 1000; anything else -> the first page. */
export function parseLimit(value: string | null): number {
  const n = Number(value);
  return Number.isInteger(n) && n > PAGE_SIZE && n <= MAX_LIMIT && n % PAGE_SIZE === 0 ? n : PAGE_SIZE;
}

const oneOf = <T>(value: string | null, allowed: readonly T[]): T | null =>
  allowed.find((a) => String(a) === value) ?? null;

export function parseFilters(p: Params, tab: string): Filters {
  const fit = Number(p.get("minfit"));
  const sort = oneOf(p.get("sort"), Object.keys(SORTS) as Sort[]) ?? defaultSort(tab);
  return {
    roles: p.getAll("role").filter((r): r is Role => r in ROLES),
    posted: oneOf(p.get("posted"), DAYS),
    found: oneOf(p.get("found"), DAYS),
    minFit: Number.isInteger(fit) && fit > 0 && fit <= 100 ? fit : 0,
    hideUnscored: p.get("unscored") === "hide",
    companies: p.getAll("co").filter(Boolean),
    excluded: p.getAll("xco").filter(Boolean),
    location: (p.get("loc") ?? "").trim().slice(0, 60),
    remote: p.get("remote") === "1",
    sponsorsOnly: p.get("sponsor") === "1",
    minFilings: oneOf(p.get("minfilings"), MIN_FILINGS),
    maxYears: oneOf(p.get("maxyrs"), MAX_YEARS),
    hideCap: p.get("cap") === "hide",
    hideClearance: p.get("clearance") === "hide",
    resume: oneOf(p.get("resume"), ["ai", "general"] as const),
    tiers: p.getAll("tier").map(Number).filter((t) => (TIERS as readonly number[]).includes(t)),
    sort,
    dir: oneOf(p.get("dir"), ["asc", "desc"] as const) ?? defaultDir(sort),
  };
}

/** Canonical query string: only what differs from the defaults, so URLs stay short. */
export function toQuery(f: Filters, tab: string): string {
  const q = new URLSearchParams();
  if (tab !== "new") q.set("tab", tab);
  f.roles.forEach((r) => q.append("role", r));
  if (f.posted) q.set("posted", String(f.posted));
  if (f.found) q.set("found", String(f.found));
  if (f.minFit) q.set("minfit", String(f.minFit));
  if (f.hideUnscored) q.set("unscored", "hide");
  f.companies.forEach((c) => q.append("co", c));
  f.excluded.forEach((c) => q.append("xco", c));
  if (f.location) q.set("loc", f.location);
  if (f.remote) q.set("remote", "1");
  if (f.sponsorsOnly) q.set("sponsor", "1");
  if (f.minFilings) q.set("minfilings", String(f.minFilings));
  if (f.maxYears) q.set("maxyrs", String(f.maxYears));
  if (f.hideCap) q.set("cap", "hide");
  if (f.hideClearance) q.set("clearance", "hide");
  if (f.resume) q.set("resume", f.resume);
  f.tiers.forEach((t) => q.append("tier", String(t)));
  if (f.sort !== defaultSort(tab)) q.set("sort", f.sort);
  if (f.dir !== defaultDir(f.sort)) q.set("dir", f.dir);
  return q.toString();
}

/** How many filters are on (for the panel's summary line). Sort doesn't count. */
export function activeCount(f: Filters): number {
  return [
    f.roles.length > 0,
    f.posted,
    f.found,
    f.minFit > 0,
    f.hideUnscored,
    f.companies.length > 0,
    f.excluded.length > 0,
    f.location,
    f.remote,
    f.sponsorsOnly || f.minFilings,
    f.maxYears,
    f.hideCap,
    f.hideClearance,
    f.resume,
    f.tiers.length > 0,
  ].filter(Boolean).length;
}

// "WA" or "Washington" should find both "US, WA, Seattle" and "Seattle, Washington"
export const STATES: Record<string, string> = {
  AL: "Alabama", AK: "Alaska", AZ: "Arizona", AR: "Arkansas", CA: "California", CO: "Colorado",
  CT: "Connecticut", DE: "Delaware", DC: "District of Columbia", FL: "Florida", GA: "Georgia",
  HI: "Hawaii", ID: "Idaho", IL: "Illinois", IN: "Indiana", IA: "Iowa", KS: "Kansas", KY: "Kentucky",
  LA: "Louisiana", ME: "Maine", MD: "Maryland", MA: "Massachusetts", MI: "Michigan", MN: "Minnesota",
  MS: "Mississippi", MO: "Missouri", MT: "Montana", NE: "Nebraska", NV: "Nevada", NH: "New Hampshire",
  NJ: "New Jersey", NM: "New Mexico", NY: "New York", NC: "North Carolina", ND: "North Dakota",
  OH: "Ohio", OK: "Oklahoma", OR: "Oregon", PA: "Pennsylvania", RI: "Rhode Island",
  SC: "South Carolina", SD: "South Dakota", TN: "Tennessee", TX: "Texas", UT: "Utah", VT: "Vermont",
  VA: "Virginia", WA: "Washington", WV: "West Virginia", WI: "Wisconsin", WY: "Wyoming",
};

/** A state code or name -> [code, name]; anything else (a city) -> null. */
export function asState(text: string): [string, string] | null {
  const t = text.trim();
  const code = Object.keys(STATES).find((c) => c === t.toUpperCase() || STATES[c].toLowerCase() === t.toLowerCase());
  return code ? [code, STATES[code]] : null;
}
