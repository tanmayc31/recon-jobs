import Link from "next/link";
import { logout, setRating, setStatus } from "./actions";
import { AddJob } from "./add-job";
import { ApplicationPanel } from "./application";
import { ApplyLink, ApplyPrompt } from "./apply-prompt";
import { FilterPanel } from "./filters";
import { GoneButton } from "./gone-button";
import { Locations } from "./locations";
import { Menu } from "./menu";
import { SearchBox } from "./search";
import { SetDates } from "./set-dates";
import { StatusButton } from "./status-button";
import { ago, day, posted, updated } from "@/lib/dates";
import {
  type Application,
  PER_COMPANY,
  STAGES,
  STAGE_LABELS,
  TABS,
  type JobRow,
  type Stage,
  type Status,
  type Tab,
  type Due,
  GOOGLE_LIMIT,
  type GoogleQuota,
  applicationStats,
  applicationsFor,
  dueApplications,
  googleQuota,
  listCompanies,
  listJobs,
  recentAdded,
  stageCounts,
  tabCounts,
  undatedApplications,
} from "@/lib/db";
import {
  DEFAULT_TAB,
  type Filters,
  MAX_LIMIT,
  PAGE_SIZE,
  ROLES,
  type Role,
  activeCount,
  defaultDir,
  defaultSort,
  parseFilters,
  sortsFor,
  parseLimit,
  toQuery,
} from "@/lib/filters";

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
  const stage = tab === "applied" && STAGES.includes(params.get("stage") as Stage) ? (params.get("stage") as Stage) : null;
  // each section on its own: a failing (or timed-out, lib/db.ts QUERY_MS) query shows a note there
  // instead of taking the whole page down
  const results = await Promise.allSettled([
    listJobs(tab, filters, limit, stage),
    tabCounts(),
    listCompanies(),
    recentAdded(),
    tab === "applied" ? stageCounts(filters) : null,
    tab === "applied" ? applicationStats(filters) : null,
    tab === "applied" ? undatedApplications() : null,
    dueApplications(),
    googleQuota(),
  ]);
  const failed = new Set<string>();
  const value = <T,>(r: PromiseSettledResult<T>, section: string, fallback: T): T => {
    if (r.status === "fulfilled") return r.value;
    console.error(`dashboard: ${section} failed:`, r.reason instanceof Error ? r.reason.message : r.reason);
    failed.add(section);
    return fallback;
  };
  const { jobs, matching, hidden } = value(results[0], "jobs", { jobs: [] as JobRow[], matching: 0, hidden: 0 });
  const counts = value(results[1], "counts", null);
  const companies = value(results[2], "companies", [] as string[]);
  const added = value(results[3], "added", []);
  const stages = value(results[4], "stages", null);
  const stats = value(results[5], "stats", null);
  const undated = value(results[6], "undated", null);
  const due = value(results[7], "due dates", [] as Due[]);
  const google = value(results[8], "Google count", null as GoogleQuota | null);
  const apps = await applicationsFor(jobs.filter((j) => j.status === "applied").map((j) => j.job_id)).catch((e) => {
    console.error("dashboard: applications failed:", e instanceof Error ? e.message : e);
    failed.add("applications");
    return new Map<string, Application>();
  });
  const active = activeCount(filters); // search included (Reset clears it too)
  const base = toQuery(filters, tab); // this tab with its filters, before the stage
  // other tabs keep the filters; a sort you picked carries over only where it exists, else each tab
  // opens on its own default (Applied: by applied date)
  const forTab = (t: Tab): Filters => {
    const keep = filters.sort !== defaultSort(tab) && sortsFor(t).includes(filters.sort);
    return keep ? filters : { ...filters, sort: defaultSort(t), dir: defaultDir(defaultSort(t)) };
  };
  const withStage = (s: Stage | null) => `/?${[base || "tab=applied", s && `stage=${s}`].filter(Boolean).join("&")}`;

  return (
    <div className="mx-auto w-full max-w-2xl px-4 pb-16">
      <header className="sticky top-0 z-10 -mx-4 border-b border-zinc-200 bg-zinc-50/90 px-4 pt-4 backdrop-blur dark:border-zinc-800 dark:bg-zinc-950/90">
        <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
          <h1 className="flex-1 text-xl font-semibold tracking-tight">Recon</h1>
          <AddJob recent={added} />
          <form action={logout}>
            <button className="text-sm text-zinc-500 hover:text-zinc-800 dark:hover:text-zinc-200">Log out</button>
          </form>
        </div>
        <nav className="-mx-4 mt-3 flex gap-1 overflow-x-auto px-4">
          {TABS.map((t) => {
            const query = toQuery(forTab(t), t); // filters carry over between tabs
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
                {LABELS[t]} {counts && <span className="text-zinc-400">{counts[t]}</span>}
              </Link>
            );
          })}
        </nav>
      </header>

      <ApplyPrompt />
      {failed.size > 0 && (
        <p role="alert" className="mt-3 rounded-xl border border-red-200 bg-red-50 px-4 py-2.5 text-sm text-red-800 dark:border-red-900 dark:bg-red-950/40 dark:text-red-300">
          Couldn&apos;t load {[...failed].join(", ")}: the database didn&apos;t answer in time. The rest of the page works;{" "}
          <Link href={`/?${params.toString()}`} className="font-medium underline">reload</Link> to try again.
        </p>
      )}
      {due.length > 0 && <DueBanner due={due} />}
      <SearchBox key={tab} q={filters.q} tab={tab} />
      {undated && undated.length > 0 && <SetDates rows={undated} />}

      {stats && stages && (
        <section className="mt-3 space-y-2" aria-label="Applications">
          <p className="flex flex-wrap gap-x-4 gap-y-1 rounded-xl border border-zinc-200 bg-white px-4 py-2.5 text-sm dark:border-zinc-800 dark:bg-zinc-900">
            <span>
              <span className="font-semibold tabular-nums">{stats.week}</span> this week
            </span>
            <span>
              <span className="font-semibold tabular-nums">{stats.total}</span> total
            </span>
            <span title="Applications past Applied: assessment, interview, offer or rejected">
              <span className="font-semibold tabular-nums">
                {stats.total ? Math.round((100 * stats.responded) / stats.total) : 0}%
              </span>{" "}
              response rate
            </span>
          </p>
          <nav className="-mx-4 flex gap-1.5 overflow-x-auto px-4 pb-1 text-sm" aria-label="Stage">
            {([null, ...STAGES] as (Stage | null)[]).map((s) => {
              const n = s ? stages[s] : stats.total;
              const on = s === stage;
              return (
                <Link
                  key={s ?? "all"}
                  href={withStage(s)}
                  aria-current={on ? "page" : undefined}
                  className={`shrink-0 rounded-full border px-3 py-1 ${
                    on
                      ? "border-zinc-900 bg-zinc-900 text-white dark:border-zinc-100 dark:bg-zinc-100 dark:text-zinc-900"
                      : n
                        ? "border-zinc-300 hover:bg-zinc-100 dark:border-zinc-700 dark:hover:bg-zinc-800"
                        : "border-zinc-200 text-zinc-400 dark:border-zinc-800"
                  }`}
                >
                  {s ? STAGE_LABELS[s] : "All"} <span className={on ? "opacity-70" : "text-zinc-400"}>{n}</span>
                </Link>
              );
            })}
          </nav>
        </section>
      )}

      {tab === "skipped" && (
        <nav className="mt-3 flex gap-1.5 text-sm" aria-label="Skipped by">
          {([[null, "All"], ["you", "By you"], ["auto", "Auto-skipped"]] as const).map(([by, label]) => {
            const on = filters.skippedBy === by;
            const query = toQuery({ ...filters, skippedBy: by }, tab);
            return (
              <Link
                key={label}
                href={`/?${query}`}
                aria-current={on ? "page" : undefined}
                className={`rounded-full border px-3 py-1 ${
                  on
                    ? "border-zinc-900 bg-zinc-900 text-white dark:border-zinc-100 dark:bg-zinc-100 dark:text-zinc-900"
                    : "border-zinc-300 hover:bg-zinc-100 dark:border-zinc-700 dark:hover:bg-zinc-800"
                }`}
              >
                {label}
              </Link>
            );
          })}
        </nav>
      )}

      {/* search isn't in the key: typing must not remount the panel */}
      <FilterPanel
        key={toQuery({ ...filters, q: "" }, tab)}
        tab={tab}
        filters={filters}
        companies={companies}
        active={activeCount({ ...filters, q: "" })}
      />

      <div className="mt-3 flex items-center justify-between gap-3 text-sm text-zinc-500">
        <p>
          Showing <span className="font-medium text-zinc-800 dark:text-zinc-200">{matching.toLocaleString()}</span>
          {counts && ` of ${counts[tab].toLocaleString()}`}
          {matching > limit && ` (first ${limit.toLocaleString()} listed)`}
          {hidden > 0 && ` · ${hidden.toLocaleString()} more past ${PER_COMPANY} per company`}
        </p>
        {active > 0 && (
          <Link href={tab === DEFAULT_TAB ? "/" : `/?tab=${tab}`} className="font-medium text-zinc-800 underline dark:text-zinc-200">
            Reset filters
          </Link>
        )}
      </div>

      <ul className="mt-3 space-y-3">
        {jobs.map((job) => (
          <JobCard key={job.job_id} job={job} tab={tab} filters={filters} app={apps.get(job.job_id) ?? null} google={google} />
        ))}
      </ul>
      {matching > limit && limit < MAX_LIMIT && (
        <Link
          href={`/?${[toQuery(filters, tab), stage && `stage=${stage}`, `limit=${limit + PAGE_SIZE}`].filter(Boolean).join("&")}`}
          scroll={false}
          className="mt-4 block rounded-xl border border-zinc-300 py-3 text-center text-sm font-medium hover:bg-zinc-100 dark:border-zinc-700 dark:hover:bg-zinc-900"
        >
          Load more ({Math.min(PAGE_SIZE, matching - limit).toLocaleString()} of {(matching - limit).toLocaleString()} remaining)
        </Link>
      )}
      {jobs.length === 0 && (
        <p className="mt-16 text-center text-zinc-500">
          {failed.has("jobs")
            ? "Jobs didn't load. Reload to try again."
            : filters.q
              ? `Nothing here matches “${filters.q}”.`
              : active
                ? "No jobs match these filters."
                : tab === "applied"
                  ? "No applications yet. Apply from Best bets or New; Recon asks when you come back."
                  : "Nothing here."}
        </p>
      )}
    </div>
  );
}

function JobCard({ job, tab, filters, app, google }: {
  job: JobRow;
  tab: Tab;
  filters: Filters;
  app: Application | null;
  google: GoogleQuota | null;
}) {
  const autoSkipped = job.decision === "skip";
  const allFlags = !autoSkipped && job.reason ? job.reason.split(", ") : [];
  const flags = allFlags.filter((f) => !f.startsWith("exp cap"));
  const cap = expCap(allFlags, job.ai_max_years);
  const edited = updated(job.posted_at, job.site_updated_at);
  // Tab names match statuses: offer every move except "stay here". An auto-skipped job
  // set back to "new" would still sit in Skipped, and backlog isn't news, so no "Back to New".
  // Best bets mixes New and Backlog: no "Back to New" there either.
  const moves = MOVES.filter(([s]) => s !== tab && !(s === "new" && (autoSkipped || tab === "backlog" || tab === "best")));
  // Applied cards: the application first (date, stage, timeline, details); the rest behind "⋯"
  const applied = job.status === "applied";
  const ids = job.ids?.length ? job.ids : [job.job_id];
  // behind "⋯" on every card: Gone? and the moves (Applied cards: the rating too)
  const more = (
    <>
      {applied && <Rate job={job} />}
      {!job.closed_at && <GoneButton jobId={job.job_id} />}
      {moves.map(([status, label]) => (
        <form key={status} action={setStatus}>
          {ids.map((id) => <input key={id} type="hidden" name="jobId" value={id} />)}
          <input type="hidden" name="status" value={status} />
          <StatusButton className="rounded-lg border border-zinc-300 px-3 py-2 text-sm font-medium hover:bg-zinc-100 dark:border-zinc-700 dark:hover:bg-zinc-800">
            {label}
          </StatusButton>
        </form>
      ))}
    </>
  );

  return (
    <li id={`job-${job.job_id}`} className="scroll-mt-32 rounded-xl border border-zinc-200 bg-white p-4 shadow-sm target:ring-2 target:ring-amber-400 dark:border-zinc-800 dark:bg-zinc-900">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-sm font-medium text-zinc-500">{job.company}</p>
          <h2 className="mt-0.5 font-semibold leading-snug">{job.title}</h2>
          {job.location && <Locations text={job.location} />}
        </div>
        {!applied && <div className="flex shrink-0 items-center gap-1.5">
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
        </div>}
      </div>

      {job.company === "Google" && google && <GoogleChip quota={google} />}

      {applied && job.closed_at && (
        <div className="mt-2 text-xs">
          <Closed at={job.closed_at} />
        </div>
      )}

      {!applied && <div className="mt-3 flex flex-wrap items-center gap-1.5 text-xs">
        {job.posted_on && <span className="text-zinc-500">{posted(job.posted_on, job.posted_at)} ·</span>}
        {edited && <span className="text-zinc-500">{edited} ·</span>}
        <span className="text-zinc-500">found {ago(job.first_seen_at)}</span>
        {job.via && (
          <span
            title={
              job.via === "list"
                ? "From a GitHub new-grad job list (vanshb03/New-Grad-2027)"
                : job.via === "email"
                  ? "From a Jobright alert email"
                  : "You added this job"
            }
            className="rounded-full bg-sky-100 px-2 py-0.5 font-medium text-sky-800 dark:bg-sky-900/50 dark:text-sky-300"
          >
            {job.via === "list" ? "from list" : job.via === "email" ? "from email" : "added by you"}
          </span>
        )}
        {job.closed_at && <Closed at={job.closed_at} />}
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
      </div>}

      {job.ai_why && applied && (
        <details className="mt-2 text-sm">
          <summary className="cursor-pointer text-zinc-500">
            AI fit{job.fit_score != null && <span className="ml-1 font-semibold tabular-nums">{job.fit_score}</span>}
          </summary>
          <AiWhy job={job} />
        </details>
      )}
      {job.ai_why && !applied && <AiWhy job={job} />}


      {job.more > 0 && (
        <Link
          href={`/?${toQuery({ ...filters, companies: [job.company] }, tab)}`}
          className="mt-3 block text-sm font-medium text-zinc-600 underline hover:text-zinc-900 dark:text-zinc-400 dark:hover:text-zinc-100"
        >
          +{job.more} more from {job.company} →
        </Link>
      )}

      {applied && <ApplicationPanel ids={ids} app={app} />}

      {tab === "skipped" && (
        <p className="mt-2 text-sm text-red-700 dark:text-red-400">
          {autoSkipped ? `Auto-skipped: ${job.reason}` : "Skipped by you"}
        </p>
      )}

      <div className="mt-4 flex flex-wrap gap-2">
        {applied ? (
          <a
            href={job.url}
            target="_blank"
            rel="noopener noreferrer"
            className="rounded-lg border border-zinc-300 px-4 py-2 text-sm font-medium hover:bg-zinc-100 dark:border-zinc-700 dark:hover:bg-zinc-800"
          >
            View posting ↗
          </a>
        ) : (
          <ApplyLink ids={ids} title={job.title} company={job.company} url={job.url} />
        )}
        {!applied && <Rate job={job} />}
        <Menu>{more}</Menu>
      </div>
    </li>
  );
}

// Deadlines and follow-ups due today or overdue, on every tab; each links to its card in Applied
function DueBanner({ due }: { due: Due[] }) {
  const today = new Date().toLocaleDateString("en-CA", { timeZone: "America/New_York" });
  return (
    <section aria-label="Due" className="mt-3 rounded-xl border border-red-200 bg-red-50 px-4 py-2.5 text-sm dark:border-red-900 dark:bg-red-950/30">
      <p className="font-medium text-red-900 dark:text-red-200">
        Due {due.some((d) => d.due_on < today) ? "now" : "today"}
      </p>
      <ul className="mt-1 space-y-0.5">
        {due.map((d) => (
          <li key={`${d.job_id}:${d.kind}`}>
            {/* a full page load: the browser scrolls to and highlights the card (:target) */}
            <a
              href={`/?tab=applied&q=${encodeURIComponent(d.title)}#job-${encodeURIComponent(d.job_id)}`}
              className="text-red-800 underline decoration-red-300 underline-offset-2 hover:decoration-red-700 dark:text-red-300"
            >
              {d.kind === "deadline" ? "Deadline" : "Follow up"}: {d.company}, {d.title}
            </a>{" "}
            <span className="ml-1.5 text-red-700/80 dark:text-red-400/80">
              {d.due_on === today ? "today" : `overdue since ${day(d.due_on)}`}
            </span>
          </li>
        ))}
      </ul>
    </section>
  );
}

// Google: at most 3 applications in 30 days, counted from your Applied tab
function GoogleChip({ quota }: { quota: GoogleQuota }) {
  const full = quota.used >= GOOGLE_LIMIT;
  return (
    <p className="mt-2 text-xs">
      <span
        title="Google accepts at most 3 applications per 30 days. Counted from your Applied tab (applications with a date)."
        className={`rounded-full px-2 py-0.5 font-medium ${
          full
            ? "bg-red-100 text-red-800 dark:bg-red-900/50 dark:text-red-300"
            : "bg-zinc-100 text-zinc-700 dark:bg-zinc-800 dark:text-zinc-300"
        }`}
      >
        {quota.used} of {GOOGLE_LIMIT} Google applications used in the last 30 days
        {full && quota.nextFree && ` · next slot ${day(quota.nextFree)}`}
      </span>
    </p>
  );
}

function Closed({ at }: { at: string }) {
  return (
    <span
      title={`No longer on the company's board (closed ${ago(at)})`}
      className="rounded-full bg-zinc-800 px-2 py-0.5 font-semibold text-white dark:bg-zinc-200 dark:text-zinc-900"
    >
      posting closed
    </span>
  );
}

// the AI judge's reasoning, rubric and missing skills
function AiWhy({ job }: { job: JobRow }) {
  return (
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
