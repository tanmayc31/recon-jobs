import Link from "next/link";
import { logout, setRating, setStatus } from "./actions";
import { FilterPanel } from "./filters";
import { GoneButton } from "./gone-button";
import { StatusButton } from "./status-button";
import { ago, posted, updated } from "@/lib/dates";
import { TABS, type JobRow, type Status, type Tab, listCompanies, listJobs, tabCounts } from "@/lib/db";
import { DEFAULT_TAB, MAX_LIMIT, PAGE_SIZE, ROLES, type Role, activeCount, parseFilters, parseLimit, toQuery } from "@/lib/filters";

const LABELS: Record<Tab, string> = {
  best: "Best bets",
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
  const params = new URLSearchParams();
  for (const [k, v] of Object.entries(await searchParams)) {
    for (const value of Array.isArray(v) ? v : v === undefined ? [] : [v]) params.append(k, value);
  }
  const tab: Tab = TABS.includes(params.get("tab") as Tab) ? (params.get("tab") as Tab) : DEFAULT_TAB;
  const filters = parseFilters(params, tab);
  const limit = parseLimit(params.get("limit")); // not a filter: changing a filter starts over at one page
  const [{ jobs, matching }, counts, companies] = await Promise.all([
    listJobs(tab, filters, limit),
    tabCounts(),
    listCompanies(),
  ]);
  const active = activeCount(filters);

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
          {TABS.map((t) => {
            const query = toQuery(filters, t); // filters carry over between tabs
            return (
              <Link
                key={t}
                href={query ? `/?${query}` : "/"}
                className={`shrink-0 border-b-2 px-3 pb-2.5 text-sm font-medium ${
                  t === tab
                    ? "border-zinc-900 text-zinc-900 dark:border-zinc-100 dark:text-zinc-100"
                    : "border-transparent text-zinc-500 hover:text-zinc-800 dark:hover:text-zinc-200"
                }`}
              >
                {LABELS[t]} <span className="text-zinc-400">{counts[t]}</span>
              </Link>
            );
          })}
        </nav>
      </header>

      <FilterPanel key={toQuery(filters, tab)} tab={tab} filters={filters} companies={companies} active={active} />

      <div className="mt-3 flex items-center justify-between gap-3 text-sm text-zinc-500">
        <p>
          Showing <span className="font-medium text-zinc-800 dark:text-zinc-200">{matching.toLocaleString()}</span> of{" "}
          {counts[tab].toLocaleString()}
          {matching > limit && ` (first ${limit.toLocaleString()} listed)`}
        </p>
        {active > 0 && (
          <Link href={tab === DEFAULT_TAB ? "/" : `/?tab=${tab}`} className="font-medium text-zinc-800 underline dark:text-zinc-200">
            Reset filters
          </Link>
        )}
      </div>

      <ul className="mt-3 space-y-3">
        {jobs.map((job) => (
          <JobCard key={job.job_id} job={job} tab={tab} />
        ))}
      </ul>
      {matching > limit && limit < MAX_LIMIT && (
        <Link
          href={`/?${[toQuery(filters, tab), `limit=${limit + PAGE_SIZE}`].filter(Boolean).join("&")}`}
          scroll={false}
          className="mt-4 block rounded-xl border border-zinc-300 py-3 text-center text-sm font-medium hover:bg-zinc-100 dark:border-zinc-700 dark:hover:bg-zinc-900"
        >
          Load more ({Math.min(PAGE_SIZE, matching - limit).toLocaleString()} of {(matching - limit).toLocaleString()} remaining)
        </Link>
      )}
      {jobs.length === 0 && (
        <p className="mt-16 text-center text-zinc-500">{active ? "No jobs match these filters." : "Nothing here."}</p>
      )}
    </div>
  );
}

function JobCard({ job, tab }: { job: JobRow; tab: Tab }) {
  const autoSkipped = job.decision === "skip";
  const allFlags = !autoSkipped && job.reason ? job.reason.split(", ") : [];
  const flags = allFlags.filter((f) => !f.startsWith("exp cap"));
  const cap = expCap(allFlags, job.ai_max_years);
  const edited = updated(job.posted_at, job.site_updated_at);
  // Tab names match statuses: offer every move except "stay here". An auto-skipped job
  // set back to "new" would still sit in Skipped, and backlog isn't news, so no "Back to New".
  // Best bets mixes New and Backlog: no "Back to New" there either.
  const moves = MOVES.filter(([s]) => s !== tab && !(s === "new" && (autoSkipped || tab === "backlog" || tab === "best")));

  return (
    <li className="rounded-xl border border-zinc-200 bg-white p-4 shadow-sm dark:border-zinc-800 dark:bg-zinc-900">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-sm font-medium text-zinc-500">{job.company}</p>
          <h2 className="mt-0.5 font-semibold leading-snug">{job.title}</h2>
          {job.location && <p className="mt-1 line-clamp-2 text-sm text-zinc-500">{job.location}</p>}
        </div>
        <div className="flex shrink-0 items-center gap-1.5">
          {job.fit_score != null && <FitScore score={job.fit_score} />}
          {job.tier != null && (
            <span
              className={`rounded-md px-2 py-0.5 text-xs font-semibold ${
                job.tier === 1
                  ? "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/50 dark:text-emerald-300"
                  : "bg-zinc-100 text-zinc-600 dark:bg-zinc-800 dark:text-zinc-300"
              }`}
            >
              T{job.tier}
            </span>
          )}
        </div>
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-1.5 text-xs">
        {job.posted_on && <span className="text-zinc-500">{posted(job.posted_on, job.posted_at)} ·</span>}
        {edited && <span className="text-zinc-500">{edited} ·</span>}
        <span className="text-zinc-500">found {ago(job.first_seen_at)}</span>
        {job.via && (
          <span
            title={job.via === "list" ? "From a GitHub new-grad job list (vanshb03/New-Grad-2027)" : "You added this job"}
            className="rounded-full bg-sky-100 px-2 py-0.5 font-medium text-sky-800 dark:bg-sky-900/50 dark:text-sky-300"
          >
            {job.via === "list" ? "from list" : "added by you"}
          </span>
        )}
        {job.closed_at && (
          <span
            title={`No longer on the company's board (closed ${ago(job.closed_at)})`}
            className="rounded-full bg-zinc-800 px-2 py-0.5 font-semibold text-white dark:bg-zinc-200 dark:text-zinc-900"
          >
            closed
          </span>
        )}
        {(job.level === "entry" || job.level === "ii") && (
          <span className="rounded-full bg-emerald-100 px-2 py-0.5 font-medium text-emerald-800 dark:bg-emerald-900/50 dark:text-emerald-300">
            {job.level === "entry" ? "Entry level" : "Level II"}
          </span>
        )}
        {job.role_type && job.role_type !== "other" && (
          <span className="rounded-full bg-zinc-100 px-2 py-0.5 text-zinc-700 dark:bg-zinc-800 dark:text-zinc-300">
            {ROLES[job.role_type as Role] ?? job.role_type}
          </span>
        )}
        {job.filings != null && (
          <span
            title="Certified H-1B software filings, FY2025 (DOL LCA data)"
            className="rounded-full bg-teal-100 px-2 py-0.5 font-medium text-teal-800 dark:bg-teal-900/50 dark:text-teal-300"
          >
            H-1B: {job.filings.toLocaleString()} SWE filings
          </span>
        )}
        {job.openings != null && job.openings > 1 && (
          <span className="rounded-full bg-indigo-100 px-2 py-0.5 text-indigo-800 dark:bg-indigo-900/50 dark:text-indigo-300">
            {job.openings} openings
          </span>
        )}
        {job.min_years != null && job.min_years > 0 && (
          <span className="rounded-full bg-sky-100 px-2 py-0.5 text-sky-800 dark:bg-sky-900/50 dark:text-sky-300">
            {job.min_years}+ yrs
          </span>
        )}
        {cap && (
          <span
            title="The posting caps experience below your ~3 years. Your call."
            className="rounded-full bg-amber-400 px-2 py-0.5 font-semibold text-amber-950 ring-1 ring-amber-500 dark:bg-amber-500 dark:text-amber-950"
          >
            ⚠ {cap}
          </span>
        )}
        {flags.map((f) => (
          <span key={f} className="rounded-full bg-amber-100 px-2 py-0.5 text-amber-800 dark:bg-amber-900/50 dark:text-amber-300">
            {f}
          </span>
        ))}
      </div>

      {job.ai_why && (
        <div className="mt-3 space-y-1 text-sm">
          <p className="text-zinc-700 dark:text-zinc-300">
            {job.ai_resume && (
              <span className="mr-1.5 rounded-full bg-violet-100 px-2 py-0.5 text-xs font-medium text-violet-800 dark:bg-violet-900/50 dark:text-violet-300">
                {job.ai_resume === "ai" ? "AI resume" : "General resume"}
              </span>
            )}
            {job.ai_why}
          </p>
          {job.ai_skills != null && job.ai_level != null && job.ai_domain != null && (
            <p className="text-xs text-zinc-500" title="Fit rubric, 0-100 each. Overall = 50% skills + 30% level + 20% domain">
              Skills <Part n={job.ai_skills} /> · Level <Part n={job.ai_level} /> · Domain <Part n={job.ai_domain} />
            </p>
          )}
          {job.ai_missing && <p className="text-zinc-500">Missing: {job.ai_missing}</p>}
        </div>
      )}

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
        <Rate job={job} />
        {!job.closed_at && <GoneButton jobId={job.job_id} />}
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

function Rate({ job }: { job: JobRow }) {
  return (
    <div className="flex gap-1" role="group" aria-label="Your rating">
      {([[1, "👍", "Good match"], [-1, "👎", "Bad match"]] as const).map(([value, emoji, label]) => {
        const on = job.my_rating === value;
        return (
          <form key={value} action={setRating}>
            <input type="hidden" name="jobId" value={job.job_id} />
            <input type="hidden" name="rating" value={on ? "" : value} />
            <StatusButton
              label={on ? `${label} (yours, press to clear)` : label}
              pressed={on}
              className={`rounded-lg border px-3 py-2 text-sm ${
                on
                  ? value === 1
                    ? "border-emerald-500 bg-emerald-100 dark:border-emerald-400 dark:bg-emerald-900/60"
                    : "border-red-400 bg-red-100 dark:border-red-400 dark:bg-red-900/60"
                  : "border-zinc-300 opacity-60 grayscale hover:bg-zinc-100 hover:opacity-100 hover:grayscale-0 dark:border-zinc-700 dark:hover:bg-zinc-800"
              }`}
            >
              {emoji}
            </StatusButton>
          </form>
        );
      })}
    </div>
  );
}

// a rubric part, colored like the overall score
function Part({ n }: { n: number }) {
  const color = n >= 80 ? "text-emerald-700 dark:text-emerald-400" : n >= 50 ? "text-amber-700 dark:text-amber-400" : "text-zinc-500";
  return <span className={`font-semibold tabular-nums ${color}`}>{n}</span>;
}

function FitScore({ score }: { score: number }) {
  const color =
    score >= 80
      ? "bg-emerald-600 text-white dark:bg-emerald-500 dark:text-emerald-950"
      : score >= 50
        ? "bg-amber-100 text-amber-900 dark:bg-amber-900/50 dark:text-amber-200"
        : "bg-zinc-100 text-zinc-500 dark:bg-zinc-800 dark:text-zinc-400";
  return (
    <span title="AI fit score" className={`rounded-md px-2 py-0.5 text-xs font-bold tabular-nums ${color}`}>
      {score}
    </span>
  );
}

// Rule filter's flag ("exp cap: max 18 mo") if it found one, else the AI's cap (under 3 years)
function expCap(flags: string[], aiMaxYears: number | null): string | null {
  const rule = flags.find((f) => f.startsWith("exp cap"));
  if (rule) return rule;
  if (aiMaxYears == null || aiMaxYears >= 3) return null;
  return `exp cap: max ${aiMaxYears} ${aiMaxYears === 1 ? "yr" : "yrs"}`;
}
