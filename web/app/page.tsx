import Link from "next/link";
import { logout, setStatus } from "./actions";
import { StatusButton } from "./status-button";
import { ago, posted, updated } from "@/lib/dates";
import { TABS, type JobRow, type Status, type Tab, listJobs, tabCounts } from "@/lib/db";

const LABELS: Record<Tab, string> = {
  new: "New",
  backlog: "Backlog",
  later: "Later",
  applied: "Applied",
  skipped: "Skipped",
};
const MOVES: [Status, string][] = [
  ["applied", "Applied"],
  ["later", "Later"],
  ["skipped", "Skip"],
  ["new", "Back to New"],
];

export default async function Home({ searchParams }: PageProps<"/">) {
  const requested = (await searchParams).tab;
  const tab: Tab = TABS.includes(requested as Tab) ? (requested as Tab) : "new";
  const [jobs, counts] = await Promise.all([listJobs(tab), tabCounts()]);

  return (
    <div className="mx-auto w-full max-w-2xl px-4 pb-16">
      <header className="sticky top-0 z-10 -mx-4 border-b border-zinc-200 bg-zinc-50/90 px-4 pt-4 backdrop-blur dark:border-zinc-800 dark:bg-zinc-950/90">
        <div className="flex items-center justify-between">
          <h1 className="text-xl font-semibold tracking-tight">Recon</h1>
          <form action={logout}>
            <button className="text-sm text-zinc-500 hover:text-zinc-800 dark:hover:text-zinc-200">Log out</button>
          </form>
        </div>
        <nav className="-mx-4 mt-3 flex gap-1 overflow-x-auto px-4">
          {TABS.map((t) => (
            <Link
              key={t}
              href={t === "new" ? "/" : `/?tab=${t}`}
              className={`shrink-0 border-b-2 px-3 pb-2.5 text-sm font-medium ${
                t === tab
                  ? "border-zinc-900 text-zinc-900 dark:border-zinc-100 dark:text-zinc-100"
                  : "border-transparent text-zinc-500 hover:text-zinc-800 dark:hover:text-zinc-200"
              }`}
            >
              {LABELS[t]} <span className="text-zinc-400">{counts[t]}</span>
            </Link>
          ))}
        </nav>
      </header>

      <ul className="mt-4 space-y-3">
        {jobs.map((job) => (
          <JobCard key={job.job_id} job={job} tab={tab} />
        ))}
      </ul>
      {jobs.length === 0 && <p className="mt-16 text-center text-zinc-500">Nothing here.</p>}
    </div>
  );
}

function JobCard({ job, tab }: { job: JobRow; tab: Tab }) {
  const autoSkipped = job.decision === "skip";
  const flags = !autoSkipped && job.reason ? job.reason.split(", ") : [];
  const edited = updated(job.posted_at, job.site_updated_at);
  // Tab names match statuses: offer every move except "stay here". An auto-skipped job
  // set back to "new" would still sit in Skipped, and backlog isn't news, so no "Back to New".
  const moves = MOVES.filter(([s]) => s !== tab && !(s === "new" && (autoSkipped || tab === "backlog")));

  return (
    <li className="rounded-xl border border-zinc-200 bg-white p-4 shadow-sm dark:border-zinc-800 dark:bg-zinc-900">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-sm font-medium text-zinc-500">{job.company}</p>
          <h2 className="mt-0.5 font-semibold leading-snug">{job.title}</h2>
          {job.location && <p className="mt-1 line-clamp-2 text-sm text-zinc-500">{job.location}</p>}
        </div>
        {job.tier != null && (
          <span
            className={`shrink-0 rounded-md px-2 py-0.5 text-xs font-semibold ${
              job.tier === 1
                ? "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/50 dark:text-emerald-300"
                : "bg-zinc-100 text-zinc-600 dark:bg-zinc-800 dark:text-zinc-300"
            }`}
          >
            T{job.tier}
          </span>
        )}
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-1.5 text-xs">
        {job.posted_at && <span className="text-zinc-500">{posted(job.posted_at)} ·</span>}
        {edited && <span className="text-zinc-500">{edited} ·</span>}
        <span className="text-zinc-500">found {ago(job.first_seen_at)}</span>
        {job.min_years != null && job.min_years > 0 && (
          <span className="rounded-full bg-sky-100 px-2 py-0.5 text-sky-800 dark:bg-sky-900/50 dark:text-sky-300">
            {job.min_years}+ yrs
          </span>
        )}
        {flags.map((f) => (
          <span key={f} className="rounded-full bg-amber-100 px-2 py-0.5 text-amber-800 dark:bg-amber-900/50 dark:text-amber-300">
            {f}
          </span>
        ))}
      </div>

      {tab === "skipped" && (
        <p className="mt-2 text-sm text-red-700 dark:text-red-400">
          {autoSkipped ? `Auto-skipped: ${job.reason}` : "Skipped by you"}
        </p>
      )}

      <div className="mt-4 flex flex-wrap gap-2">
        <a
          href={job.url}
          target="_blank"
          rel="noopener noreferrer"
          className="rounded-lg bg-zinc-900 px-4 py-2 text-sm font-medium text-white dark:bg-zinc-100 dark:text-zinc-900"
        >
          Apply ↗
        </a>
        {moves.map(([status, label]) => (
          <form key={status} action={setStatus}>
            <input type="hidden" name="jobId" value={job.job_id} />
            <input type="hidden" name="status" value={status} />
            <StatusButton className="rounded-lg border border-zinc-300 px-3 py-2 text-sm font-medium hover:bg-zinc-100 dark:border-zinc-700 dark:hover:bg-zinc-800">
              {label}
            </StatusButton>
          </form>
        ))}
      </div>
    </li>
  );
}
