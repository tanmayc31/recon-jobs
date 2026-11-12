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

export const TABS = ["new", "backlog", "later", "applied", "skipped"] as const;
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
  site_updated_at: string | null; // site's last edit (Greenhouse only)
  first_seen_at: string;
  decision: string;
  reason: string | null;
  min_years: number | null;
  status: Status;
  fit_score: number | null; // AI judge (recon/judge.py); null until judged
  ai_why: string | null;
  ai_missing: string | null; // comma-separated
  ai_resume: "ai" | "general" | null;
  ai_max_years: number | null; // most experience the posting allows (null: no cap)
  openings: number | null; // Amazon: identical title + location postings collapsed into this job
  role_type: string | null;
  filings: number | null; // H-1B software filings (sponsors table), null if not a known sponsor
};


function tabWhere(sql: postgres.Sql, tab: Tab) {
  return {
    new: sql`j.decision = 'match' AND j.status = 'new'`,
    // saved in a company's first run: already open when Recon started watching
    backlog: sql`j.decision = 'match' AND j.status = 'backlog'`,
    later: sql`j.status = 'later'`,
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
      SELECT j.job_id, j.company, j.title, j.location, j.url, j.tier, j.posted_at, j.site_updated_at,
             j.first_seen_at, j.decision, j.reason, j.min_years, j.status, j.fit_score, j.ai_why,
             j.ai_missing, j.ai_resume, j.ai_max_years, j.openings, j.role_type, sp.filings
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
  const [row] = await db()`
    SELECT
      COUNT(*) FILTER (WHERE decision = 'match' AND status = 'new')::int AS new,
      COUNT(*) FILTER (WHERE decision = 'match' AND status = 'backlog')::int AS backlog,
      COUNT(*) FILTER (WHERE status = 'later')::int AS later,
      COUNT(*) FILTER (WHERE status = 'applied')::int AS applied,
      COUNT(*) FILTER (WHERE status = 'skipped' OR (decision = 'skip' AND status IN ('new', 'backlog')))::int AS skipped
    FROM jobs`;
  return row as Record<Tab, number>;
}

export async function updateStatus(jobId: string, status: Status) {
  await db()`UPDATE jobs SET status = ${status} WHERE job_id = ${jobId}`;
}
