import "server-only";
import postgres from "postgres";
import { type Filters, asState } from "./filters";

// Same Postgres the Python poller writes to. DATABASE_URL is server-only (no NEXT_PUBLIC_).
const globalForDb = globalThis as unknown as { sql?: postgres.Sql };

function connect() {
  const url = process.env.DATABASE_URL;
  if (!url) throw new Error("DATABASE_URL is not set");
  // prepare: false -> works with Supabase's pooler; small pool for serverless
  return postgres(url, { prepare: false, max: 5 });
}

function db() {
  globalForDb.sql ??= connect(); // reuse across dev hot-reloads
  return globalForDb.sql;
}

export const TABS = ["best", "new", "backlog", "later", "applied", "skipped"] as const;
export type Tab = (typeof TABS)[number];

export const STATUSES = ["new", "backlog", "later", "applied", "skipped"] as const;
export type Status = (typeof STATUSES)[number];

export type JobRow = {
  job_id: string;
  company: string;
  title: string;
  location: string | null;
  url: string;
  tier: number | null;
  posted_at: string | null; // ISO date, or Workday text "Posted 30+ Days Ago"
  posted_on: string | null; // posted_at as an ISO date (Workday's relative text resolved)
  site_updated_at: string | null; // site's last edit (Greenhouse only)
  first_seen_at: string;
  decision: string;
  reason: string | null;
  min_years: number | null;
  status: Status;
  fit_score: number | null; // AI judge (recon/judge.py); null until judged
  ai_skills: number | null; // rubric parts (0-100) behind fit_score; null if judged before the rubric
  ai_level: number | null;
  ai_domain: number | null;
  ai_why: string | null;
  ai_missing: string | null; // comma-separated
  ai_resume: "ai" | "general" | null;
  ai_max_years: number | null; // most experience the posting allows (null: no cap)
  openings: number | null; // Amazon: identical title + location postings collapsed into this job
  role_type: string | null;
  level: string | null; // entry / ii / unknown (recon/roles.py)
  filings: number | null; // H-1B software filings (sponsors table), null if not a known sponsor
  my_rating: Rating | null; // your 👍 / 👎
  closed_at: string | null; // gone from the company's board
};

export const RATINGS = [1, -1] as const; // 👍, 👎
export type Rating = (typeof RATINGS)[number];


// Best bets: open, entry level or SWE II with at most 2 years required, an H-1B sponsor, fit 70+
const MAX_BEST_YEARS = 2;
const MIN_BEST_FIT = 70;

function tabWhere(sql: postgres.Sql, tab: Tab) {
  return {
    best: sql`j.decision = 'match' AND j.status IN ('new', 'backlog') AND j.closed_at IS NULL
      AND j.level IN ('entry', 'ii') AND COALESCE(j.min_years, j.ai_years, 0) <= ${MAX_BEST_YEARS}
      AND sp.filings > 0 AND j.fit_score >= ${MIN_BEST_FIT}`,
    // closed jobs (gone from the board, recon/store.py track_listings) leave New, Backlog and
    // Later; Applied keeps them with a "closed" badge
    new: sql`j.decision = 'match' AND j.status = 'new' AND j.closed_at IS NULL`,
    // saved in a company's first run: already open when Recon started watching
    backlog: sql`j.decision = 'match' AND j.status = 'backlog' AND j.closed_at IS NULL`,
    later: sql`j.status = 'later' AND j.closed_at IS NULL`,
    applied: sql`j.status = 'applied'`,
    // you skipped it, or Recon auto-skipped it (eligibility/years) and you haven't moved it
    skipped: sql`(j.status = 'skipped' OR (j.decision = 'skip' AND j.status IN ('new', 'backlog')))`,
  }[tab];
}

const like = (text: string) => `%${text.replace(/[\\%_]/g, (c) => "\\" + c)}%`;

function filterWhere(sql: postgres.Sql, f: Filters) {
  const where = [];
  if (f.roles.length) where.push(sql`j.role_type IN ${sql(f.roles)}`);
  if (f.posted) where.push(sql`j.posted_on::date >= current_date - ${f.posted}::int`);
  if (f.found) where.push(sql`j.first_seen_at::timestamptz >= now() - make_interval(days => ${f.found}::int)`);
  if (f.minFit && f.hideUnscored) where.push(sql`j.fit_score >= ${f.minFit}`);
  else if (f.minFit) where.push(sql`(j.fit_score >= ${f.minFit} OR j.fit_score IS NULL)`);
  else if (f.hideUnscored) where.push(sql`j.fit_score IS NOT NULL`);
  if (f.levels.length) where.push(sql`j.level IN ${sql(f.levels)}`);
  if (f.companies.length) where.push(sql`j.company IN ${sql(f.companies)}`);
  if (f.excluded.length) where.push(sql`j.company NOT IN ${sql(f.excluded)}`);
  if (f.location) {
    const state = asState(f.location);
    where.push(
      state // "WA" as a whole word ("US, WA, Seattle"), or "Washington"
        ? sql`(j.location ~ ${"\\m" + state[0] + "\\M"} OR j.location ILIKE ${like(state[1])})`
        : sql`j.location ILIKE ${like(f.location)}`,
    );
  }
  if (f.remote) where.push(sql`j.location ILIKE '%remote%'`);
  if (f.sponsorsOnly || f.minFilings) where.push(sql`sp.filings >= ${f.minFilings ?? 1}`);
  // unknown years count as fine: most postings don't say
  if (f.maxYears) where.push(sql`COALESCE(j.min_years, j.ai_years, 0) <= ${f.maxYears}`);
  if (f.hideCap) where.push(sql`NOT (COALESCE(j.reason, '') LIKE '%exp cap%' OR COALESCE(j.ai_max_years, 99) < 3)`);
  if (f.hideClearance) where.push(sql`COALESCE(j.reason, '') NOT LIKE '%clearance preferred%'`);
  if (f.resume) where.push(sql`j.ai_resume = ${f.resume}`);
  if (f.tiers.length) where.push(sql`j.tier IN ${sql(f.tiers)}`);
  return where.reduce((all, w) => sql`${all} AND ${w}`, sql`TRUE`);
}

function orderBy(sql: postgres.Sql, f: Filters) {
  const asc = f.dir === "asc";
  const key = {
    fit: asc ? sql`j.fit_score ASC NULLS LAST` : sql`j.fit_score DESC NULLS LAST`,
    posted: asc ? sql`j.posted_on ASC NULLS LAST` : sql`j.posted_on DESC NULLS LAST`,
    found: asc ? sql`j.first_seen_at ASC` : sql`j.first_seen_at DESC`,
    company: asc ? sql`lower(j.company) ASC` : sql`lower(j.company) DESC`,
    filings: asc ? sql`sp.filings ASC NULLS LAST` : sql`sp.filings DESC NULLS LAST`,
  }[f.sort];
  return sql`${key}, j.first_seen_at DESC, j.job_id`;
}

/** The tab's jobs after filters (the first `limit`), and how many match in all. */
export async function listJobs(tab: Tab, f: Filters, limit: number): Promise<{ jobs: JobRow[]; matching: number }> {
  const sql = db();
  const where = sql`${tabWhere(sql, tab)} AND ${filterWhere(sql, f)}`;
  const [jobs, [count]] = await Promise.all([
    sql<JobRow[]>`
      SELECT j.job_id, j.company, j.title, j.location, j.url, j.tier, j.posted_at, j.posted_on, j.site_updated_at,
             j.first_seen_at, j.decision, j.reason, j.min_years, j.status, j.fit_score, j.ai_skills,
             j.ai_level, j.ai_domain, j.ai_why, j.ai_missing, j.ai_resume, j.ai_max_years, j.openings,
             j.role_type, j.level, j.my_rating, j.closed_at, sp.filings
      FROM jobs j LEFT JOIN sponsors sp ON sp.company = j.company
      WHERE ${where}
      ORDER BY ${orderBy(sql, f)}
      LIMIT ${limit}`,
    sql<{ n: number }[]>`
      SELECT COUNT(*)::int AS n FROM jobs j LEFT JOIN sponsors sp ON sp.company = j.company WHERE ${where}`,
  ]);
  return { jobs, matching: count.n };
}

/** Companies with at least one match, for the company picker. */
export async function listCompanies(): Promise<string[]> {
  const rows = await db()<{ company: string }[]>`
    SELECT DISTINCT company FROM jobs WHERE decision = 'match' ORDER BY company`;
  return rows.map((r) => r.company);
}

export async function tabCounts(): Promise<Record<Tab, number>> {
  const sql = db();
  // same conditions as the tabs themselves
  const counts = TABS.map((t) => sql`COUNT(*) FILTER (WHERE ${tabWhere(sql, t)})::int AS ${sql(t)}`);
  const [row] = await sql`
    SELECT ${counts.flatMap((c, i) => (i ? [sql`, `, c] : [c])).reduce((a, b) => sql`${a}${b}`)}
    FROM jobs j LEFT JOIN sponsors sp ON sp.company = j.company`;
  return row as Record<Tab, number>;
}

export async function updateStatus(jobId: string, status: Status) {
  await db()`UPDATE jobs SET status = ${status} WHERE job_id = ${jobId}`;
}

/** For "Gone?": what the site's API needs, read from the database (not from the form). */
export async function jobForCheck(jobId: string) {
  const [row] = await db()<{ job_id: string; source: string; url: string; source_ids: string | null }[]>`
    SELECT job_id, source, url, source_ids FROM jobs WHERE job_id = ${jobId}`;
  return row ?? null;
}

/** The site says it's gone: same as recon/store.py close_jobs. */
export async function closeJob(jobId: string) {
  const at = new Date().toISOString().slice(0, 19) + "+00:00";
  await db()`UPDATE jobs SET closed_at = ${at}, closed_reason = 'api' WHERE job_id = ${jobId} AND closed_at IS NULL`;
}

/** null clears the rating. rated_at uses the poller's format (UTC ISO, seconds). */
export async function updateRating(jobId: string, rating: Rating | null) {
  const at = rating === null ? null : new Date().toISOString().slice(0, 19) + "+00:00";
  await db()`UPDATE jobs SET my_rating = ${rating}, rated_at = ${at} WHERE job_id = ${jobId}`;
}
