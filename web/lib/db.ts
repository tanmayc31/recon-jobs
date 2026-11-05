import "server-only";
import postgres from "postgres";

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
};

export async function listJobs(tab: Tab): Promise<JobRow[]> {
  const sql = db();
  const where = {
    new: sql`decision = 'match' AND status = 'new'`,
    // saved in a company's first run: already open when Recon started watching
    backlog: sql`decision = 'match' AND status = 'backlog'`,
    later: sql`status = 'later'`,
    applied: sql`status = 'applied'`,
    // you skipped it, or Recon auto-skipped it (eligibility/years) and you haven't moved it
    skipped: sql`status = 'skipped' OR (decision = 'skip' AND status IN ('new', 'backlog'))`,
  }[tab];
  return sql<JobRow[]>`
    SELECT job_id, company, title, location, url, tier, posted_at, site_updated_at, first_seen_at,
           decision, reason, min_years, status
    FROM jobs WHERE ${where}
    ORDER BY first_seen_at DESC, tier, company
    LIMIT 1000`;
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
