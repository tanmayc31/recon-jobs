import "server-only";
import postgres from "postgres";
import { APPLIED_SORTS, type Filters, asState } from "./filters";
import { type Application, DETAILS, type Detail, RESPONDED, STAGES, type Stage } from "./stages";

export * from "./stages";

// Same Postgres the Python poller writes to. DATABASE_URL is server-only (no NEXT_PUBLIC_).
const globalForDb = globalThis as unknown as { sql?: postgres.Sql };

function connect() {
  const url = process.env.DATABASE_URL;
  if (!url) throw new Error("DATABASE_URL is not set");
  // prepare: false -> works with Supabase's pooler; small pool for serverless. Idle connections close
  // after 20 s and are recycled every 5 min (a frozen serverless function's sockets go stale).
  // max_pipeline 1: one query at a time per connection. Pipelined queries hang behind Supabase's
  // transaction pooler (port 6543): the 504s, a query left waiting on ClientRead until its 2-min timeout
  return postgres(url, { prepare: false, max: 5, max_pipeline: 1, idle_timeout: 20, max_lifetime: 5 * 60, connect_timeout: 10 });
}

// The pooler ignores per-connection statement_timeout, so every query gets cancelled (on the server
// too) after QUERY_MS: a slow page shows an error instead of hanging. Dashboard queries take < 100 ms.
export const QUERY_MS = Number(process.env.DB_QUERY_MS) || 4000; // DB_QUERY_MS: for testing the error path

export class QueryTimeout extends Error {}

function timed<T extends readonly (object | undefined)[]>(q: postgres.PendingQuery<T>, ms = QUERY_MS): Promise<T> {
  let timer: ReturnType<typeof setTimeout> | undefined;
  const limit = new Promise<never>((_, reject) => {
    timer = setTimeout(() => {
      q.cancel();
      reject(new QueryTimeout(`Database query took longer than ${ms / 1000} s`));
    }, ms);
  });
  return Promise.race([q, limit]).finally(() => clearTimeout(timer));
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
  via: "list" | "email" | "you" | null; // from a GitHub job list, a Jobright alert email, or added by you
  filings: number | null; // H-1B software filings (sponsors table), null if not a known sponsor
  my_rating: Rating | null; // your 👍 / 👎
  closed_at: string | null; // gone from the company's board
  ids: string[]; // this card's copies (same company + title, other locations) in the tab, itself first
  more: number; // Best bets: this company's jobs past the per-company limit (on its last shown card)
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
  if (f.q) where.push(sql`(j.company ILIKE ${like(f.q)} OR j.title ILIKE ${like(f.q)})`);
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
  // Skipped tab: you moved it there, or Recon's rules skipped it (decision 'skip', still new/backlog)
  if (f.skippedBy === "you") where.push(sql`j.status = 'skipped'`);
  if (f.skippedBy === "auto") where.push(sql`j.status <> 'skipped'`);
  return where.reduce((all, w) => sql`${all} AND ${w}`, sql`TRUE`);
}

function orderBy(sql: postgres.Sql, f: Filters) {
  const asc = f.dir === "asc";
  const by = (col: postgres.Fragment) => (asc ? sql`${col} ASC NULLS LAST` : sql`${col} DESC NULLS LAST`);
  const key = {
    fit: by(sql`j.fit_score`),
    posted: by(sql`j.posted_on`),
    found: asc ? sql`j.first_seen_at ASC` : sql`j.first_seen_at DESC`,
    company: asc ? sql`lower(j.company) ASC` : sql`lower(j.company) DESC`,
    filings: by(sql`sp.filings`),
    // Applied tab (applications a joined): undated applications last either way
    applied: by(sql`a.applied_at::timestamptz`),
    updated: by(sql`COALESCE(a.stage_at, a.applied_at)::timestamptz`),
  }[f.sort];
  return sql`${key}, j.first_seen_at DESC, j.job_id`;
}

// One card per company + title: the same job posted for several locations (Harvey NY and SF)
const groupKey = (sql: postgres.Sql) => sql`j.company || chr(31) || lower(trim(j.title))`;

// Best bets shows at most this many jobs per company (the best by the current sort), with a link
// to the rest; picking companies in the filter lifts it
export const PER_COMPANY = 3;

/** The tab's jobs after filters (the first `limit`), how many match in all, and how many of those
 *  the per-company limit hides. Copies of a job (same company + title) are one row: the first by
 *  the sort, with every copy's id and location. */
export async function listJobs(
  tab: Tab,
  f: Filters,
  limit: number,
  stage: Stage | null = null, // Applied tab: one stage only
): Promise<{ jobs: JobRow[]; matching: number; hidden: number }> {
  const sql = db();
  const applied = tab === "applied" || APPLIED_SORTS.includes(f.sort);
  // Applied tab: one stage (no application row yet counts as "applied"), a join, not a subquery per row
  const byStage = tab === "applied" && stage ? sql`COALESCE(a.stage, 'applied') = ${stage}` : sql`TRUE`;
  const where = sql`${tabWhere(sql, tab)} AND ${filterWhere(sql, f)} AND ${byStage}`;
  const cap = tab === "best" && f.companies.length === 0 ? PER_COMPANY : 1_000_000;
  const order = orderBy(sql, f);
  const copies = sql`PARTITION BY ${groupKey(sql)}`;
  // ord: place overall; copy_rank: place among its copies (1 = the card)
  const base = sql`
    SELECT j.job_id, j.company, j.title, j.location, j.url, j.tier, j.posted_at, j.posted_on, j.site_updated_at,
           j.first_seen_at, j.decision, j.reason, j.min_years, j.status, j.fit_score, j.ai_skills,
           j.ai_level, j.ai_domain, j.ai_why, j.ai_missing, j.ai_resume, j.ai_max_years, j.openings,
           j.role_type, j.level, j.via, j.my_rating, j.closed_at, sp.filings,
           ROW_NUMBER() OVER (ORDER BY ${order}) AS ord,
           ROW_NUMBER() OVER (${copies} ORDER BY ${order}) AS copy_rank,
           array_agg(j.job_id) OVER (${copies}) AS ids,
           array_agg(j.location) OVER (${copies}) AS locations
    FROM jobs j LEFT JOIN sponsors sp ON sp.company = j.company
         ${applied ? sql`LEFT JOIN applications a ON a.job_id = j.job_id` : sql``}
    WHERE ${where}`;
  // company_rank: the card's place within its company (Best bets' per-company limit)
  const ranked = sql`
    SELECT b.*, ROW_NUMBER() OVER (PARTITION BY b.company ORDER BY b.ord)::int AS company_rank,
           COUNT(*) OVER (PARTITION BY b.company)::int AS company_total
    FROM (${base}) b WHERE b.copy_rank = 1`;
  const [rows, [count]] = await Promise.all([
    timed(sql<(JobRow & { locations: (string | null)[] })[]>`
      SELECT *, CASE WHEN company_rank = ${cap} THEN company_total - ${cap} ELSE 0 END::int AS more
      FROM (${ranked}) t WHERE company_rank <= ${cap} ORDER BY ord LIMIT ${limit}`),
    timed(sql<{ n: number; hidden: number }[]>`
      SELECT COUNT(*) FILTER (WHERE company_rank <= ${cap})::int AS n,
             COUNT(*) FILTER (WHERE company_rank > ${cap})::int AS hidden
      FROM (${ranked}) t`),
  ]);
  const jobs = rows.map((r) => {
    const all = [...new Set(r.locations.flatMap((l) => (l ? l.split("; ") : [])))];
    return { ...r, location: all.join("; ") || r.location };
  });
  return { jobs, matching: count.n, hidden: count.hidden };
}

/** Companies with at least one match, for the company picker. */
export async function listCompanies(): Promise<string[]> {
  const rows = await timed(db()<{ company: string }[]>`
    SELECT DISTINCT company FROM jobs WHERE decision = 'match' ORDER BY company`);
  return rows.map((r) => r.company);
}

/** Cards per tab (copies of a job count once, like the list), in one pass over the table. */
export async function tabCounts(): Promise<Record<Tab, number>> {
  const sql = db();
  // same conditions as the tabs themselves
  const counts = TABS.map((t) => sql`COUNT(DISTINCT ${groupKey(sql)}) FILTER (WHERE ${tabWhere(sql, t)})::int AS ${sql(t)}`);
  const [row] = await timed(sql`
    SELECT ${counts.flatMap((c, i) => (i ? [sql`, `, c] : [c])).reduce((a, b) => sql`${a}${b}`)}
    FROM jobs j LEFT JOIN sponsors sp ON sp.company = j.company`);
  return row as Record<Tab, number>;
}

/** Moves a card: every copy of it in that tab (ids). Applied: on appliedOn (YYYY-MM-DD), or now. */
export async function updateStatus(ids: string[], status: Status, appliedOn: string | null = null) {
  await timed(db()`UPDATE jobs SET status = ${status} WHERE job_id IN ${db()(ids)}`);
  if (status === "applied") await startApplication(ids, appliedOn);
}

// --- Applications: stages, dates and your details for Applied jobs (tables `applications` and
// `application_events`, recon/store.py). jobs.status still drives the tabs.

const eventId = () => crypto.randomUUID().replace(/-/g, "");
// a picked day is stored at noon UTC: the same calendar day in every US time zone
const onDay = (day: string) => `${day}T12:00:00+00:00`;

/** Marked Applied (the popup or the Applied button): the day you picked, else now. Without a picked
 *  day an application that already has a date keeps it (applied again after moving it away). */
async function startApplication(ids: string[], appliedOn: string | null) {
  const sql = db();
  const at = appliedOn ? onDay(appliedOn) : now();
  for (const jobId of ids) {
    const [row] = await timed(sql<{ applied_at: string | null }[]>`
      INSERT INTO applications (job_id, stage, applied_at, stage_at) VALUES (${jobId}, 'applied', ${at}, ${at})
      ON CONFLICT (job_id) DO UPDATE SET applied_at = ${appliedOn ? sql`EXCLUDED.applied_at` : sql`COALESCE(applications.applied_at, EXCLUDED.applied_at)`},
        stage_at = COALESCE(applications.stage_at, EXCLUDED.stage_at)
      RETURNING applied_at`);
    if (row.applied_at === at) await setFirstApplied(jobId, at);
  }
}

/** The timeline starts on the applied day: move its first "applied" event, or add one. */
async function setFirstApplied(jobId: string, at: string) {
  const sql = db();
  const [first] = await timed(sql<{ id: string }[]>`SELECT id FROM application_events
    WHERE job_id = ${jobId} AND stage = 'applied' ORDER BY at LIMIT 1`);
  if (first) await timed(sql`UPDATE application_events SET at = ${at} WHERE id = ${first.id}`);
  else await timed(sql`INSERT INTO application_events (id, job_id, stage, at) VALUES (${eventId()}, ${jobId}, 'applied', ${at})`);
}

/** Sets the applied day (YYYY-MM-DD) on every copy, e.g. for jobs applied before Recon tracked dates. */
export async function setAppliedOn(ids: string[], appliedOn: string) {
  const sql = db();
  const at = onDay(appliedOn);
  for (const jobId of ids) {
    const changed = await timed(sql`
      INSERT INTO applications (job_id, stage, applied_at) VALUES (${jobId}, 'applied', ${at})
      ON CONFLICT (job_id) DO UPDATE SET applied_at = EXCLUDED.applied_at
      WHERE COALESCE(substr(applications.applied_at, 1, 10), '') <> ${appliedOn} RETURNING job_id`);
    if (changed.length) await setFirstApplied(jobId, at);
  }
}

export async function updateStage(ids: string[], stage: Stage) {
  const sql = db();
  const at = now();
  for (const jobId of ids) {
    await timed(sql`INSERT INTO applications (job_id, stage, stage_at) VALUES (${jobId}, ${stage}, ${at})
              ON CONFLICT (job_id) DO UPDATE SET stage = EXCLUDED.stage, stage_at = EXCLUDED.stage_at`);
    await timed(sql`INSERT INTO application_events (id, job_id, stage, at) VALUES (${eventId()}, ${jobId}, ${stage}, ${at})`);
  }
}

/** Your details on every copy; empty fields are cleared. */
export async function updateDetails(ids: string[], details: Record<Detail, string | null>, appliedOn: string | null) {
  const sql = db();
  for (const jobId of ids) {
    await timed(sql`INSERT INTO applications (job_id) VALUES (${jobId}) ON CONFLICT (job_id) DO NOTHING`);
    await timed(sql`UPDATE applications SET ${sql(details, ...DETAILS)} WHERE job_id = ${jobId}`);
  }
  if (appliedOn) await setAppliedOn(ids, appliedOn);
}

/** Applied jobs without a date (applied before Recon tracked dates), one row per card. */
export async function undatedApplications(): Promise<{ ids: string[]; company: string; title: string }[]> {
  const sql = db();
  return timed(sql<{ ids: string[]; company: string; title: string }[]>`
    SELECT array_agg(j.job_id) AS ids, min(j.company) AS company, min(j.title) AS title
    FROM jobs j LEFT JOIN applications a ON a.job_id = j.job_id
    WHERE j.status = 'applied' AND a.applied_at IS NULL
    GROUP BY ${groupKey(sql)} ORDER BY lower(min(j.company)), lower(min(j.title))`);
}

/** "AI prep": recon/prep.py writes it (GitHub Actions, the judge's Gemini key and profile). */
export async function queuePrep(jobId: string) {
  await timed(db()`UPDATE applications SET prep_state = 'queued' WHERE job_id = ${jobId}`);
}

export async function updatePrep(jobId: string, prep: string) {
  await timed(db()`UPDATE applications SET prep = ${prep || null} WHERE job_id = ${jobId}`);
}

export async function applicationsFor(jobIds: string[]): Promise<Map<string, Application>> {
  if (!jobIds.length) return new Map();
  const sql = db();
  const [apps, events] = await Promise.all([
    timed(sql<Omit<Application, "events">[]>`
      SELECT job_id, stage, applied_at, stage_at, notes, referral, resume, contact, link, deadline, follow_up,
             prep, prep_state
      FROM applications WHERE job_id IN ${sql(jobIds)}`),
    timed(sql<{ job_id: string; stage: Stage; at: string }[]>`
      SELECT job_id, stage, at FROM application_events WHERE job_id IN ${sql(jobIds)} ORDER BY at`),
  ]);
  const out = new Map(apps.map((a) => [a.job_id, { ...a, events: [] as Application["events"] }]));
  for (const e of events) out.get(e.job_id)?.events.push({ stage: e.stage, at: e.at });
  return out;
}

/** Applied tab: cards per stage (no application row yet: "applied"), after the search and filters. */
export async function stageCounts(f: Filters): Promise<Record<Stage, number>> {
  const sql = db();
  const rows = await timed(sql<{ stage: Stage; n: number }[]>`
    SELECT COALESCE(a.stage, 'applied') AS stage, COUNT(DISTINCT ${groupKey(sql)})::int AS n
    FROM jobs j LEFT JOIN applications a ON a.job_id = j.job_id LEFT JOIN sponsors sp ON sp.company = j.company
    WHERE j.status = 'applied' AND ${filterWhere(sql, f)} GROUP BY 1`);
  const counts = Object.fromEntries(STAGES.map((s) => [s, 0])) as Record<Stage, number>;
  for (const r of rows) if (r.stage in counts) counts[r.stage] = r.n;
  return counts;
}

/** Applications (cards) this week (since Monday, Eastern), in all, and how many got an answer,
 *  after the search and filters. */
export async function applicationStats(f: Filters): Promise<{ week: number; total: number; responded: number }> {
  const sql = db();
  const [row] = await timed(sql<{ week: number; total: number; responded: number }[]>`
    SELECT COUNT(DISTINCT ${groupKey(sql)}) FILTER (WHERE a.applied_at::timestamptz >=
             date_trunc('week', now() AT TIME ZONE 'America/New_York') AT TIME ZONE 'America/New_York')::int AS week,
           COUNT(DISTINCT ${groupKey(sql)})::int AS total,
           COUNT(DISTINCT ${groupKey(sql)}) FILTER (WHERE a.stage IN ${sql(RESPONDED)})::int AS responded
    FROM jobs j LEFT JOIN applications a ON a.job_id = j.job_id LEFT JOIN sponsors sp ON sp.company = j.company
    WHERE j.status = 'applied' AND ${filterWhere(sql, f)}`);
  return row;
}

// Google allows 3 applications per 30 days: yours, counted from the Applied tab (dated ones)
export const GOOGLE_LIMIT = 3;
export type GoogleQuota = { used: number; nextFree: string | null }; // nextFree: when a slot opens, if all used

export async function googleQuota(): Promise<GoogleQuota> {
  const sql = db();
  const rows = await timed(sql<{ applied_at: string }[]>`
    SELECT min(a.applied_at) AS applied_at
    FROM jobs j JOIN applications a ON a.job_id = j.job_id
    WHERE j.company = 'Google' AND j.status = 'applied'
      AND a.applied_at::timestamptz >= now() - interval '30 days'
    GROUP BY ${groupKey(sql)} ORDER BY 1`);
  const used = rows.length;
  const nextFree =
    used >= GOOGLE_LIMIT ? new Date(Date.parse(rows[0].applied_at) + 30 * 24 * 3600 * 1000).toISOString() : null;
  return { used, nextFree };
}

export type Due = { job_id: string; company: string; title: string; kind: "deadline" | "follow_up"; due_on: string };

/** Deadlines and follow-ups due today or overdue (Eastern), for applications still in play. */
export async function dueApplications(): Promise<Due[]> {
  const sql = db();
  return timed(sql<Due[]>`
    SELECT DISTINCT ON (${groupKey(sql)}, d.kind) j.job_id, j.company, j.title, d.kind, d.due_on
    FROM jobs j JOIN applications a ON a.job_id = j.job_id
    CROSS JOIN LATERAL (VALUES ('deadline', a.deadline), ('follow_up', a.follow_up)) AS d(kind, due_on)
    WHERE j.status = 'applied' AND a.stage NOT IN ('rejected', 'ghosted', 'withdrawn')
      AND d.due_on IS NOT NULL AND d.due_on <= to_char(now() AT TIME ZONE 'America/New_York', 'YYYY-MM-DD')
    ORDER BY ${groupKey(sql)}, d.kind, j.job_id
    LIMIT 20`);
}

// "Add job": URLs you pasted, handled by recon/add.py (the same `added` table)
export type Added = { id: string; url: string; added_at: string; state: string; message: string | null; job_id: string | null };

const now = () => new Date().toISOString().slice(0, 19) + "+00:00";

export async function queueAdded(url: string) {
  await timed(db()`INSERT INTO added (id, url, added_at, state) VALUES (${crypto.randomUUID().replace(/-/g, "")}, ${url}, ${now()}, 'queued')`);
}

export async function recentAdded(limit = 5): Promise<Added[]> {
  return timed(db()<Added[]>`SELECT id, url, added_at, state, message, job_id FROM added ORDER BY added_at DESC LIMIT ${limit}`);
}

/** "Keep anyway": the filters skipped it, you want it. recon/store.py keeps your matches matches. */
export async function keepAdded(id: string): Promise<boolean> {
  const sql = db();
  const [row] = await timed(sql<{ job_id: string | null }[]>`SELECT job_id FROM added WHERE id = ${id} AND state = 'skipped'`);
  if (!row?.job_id) return false;
  await timed(sql`UPDATE jobs SET decision = 'match', status = 'new', via = 'you', closed_at = NULL,
            reason = 'kept: ' || COALESCE(reason, ''), ai_skip = NULL WHERE job_id = ${row.job_id}`);
  await timed(sql`UPDATE added SET state = 'kept', message = 'Kept in New (the AI judges it next)' WHERE id = ${id}`);
  return true;
}

/** For "Gone?": what the site's API needs, read from the database (not from the form). */
export async function jobForCheck(jobId: string) {
  const [row] = await timed(db()<{ job_id: string; source: string; url: string; source_ids: string | null }[]>`
    SELECT job_id, source, url, source_ids FROM jobs WHERE job_id = ${jobId}`);
  return row ?? null;
}

/** The site says it's gone: same as recon/store.py close_jobs. */
export async function closeJob(jobId: string) {
  const at = new Date().toISOString().slice(0, 19) + "+00:00";
  await timed(db()`UPDATE jobs SET closed_at = ${at}, closed_reason = 'api' WHERE job_id = ${jobId} AND closed_at IS NULL`);
}

/** null clears the rating. rated_at uses the poller's format (UTC ISO, seconds). */
export async function updateRating(jobId: string, rating: Rating | null) {
  const at = rating === null ? null : new Date().toISOString().slice(0, 19) + "+00:00";
  await timed(db()`UPDATE jobs SET my_rating = ${rating}, rated_at = ${at} WHERE job_id = ${jobId}`);
}
