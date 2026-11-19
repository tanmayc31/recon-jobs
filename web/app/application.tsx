"use client";

import { useActionState, useEffect, useOptimistic, useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import { requestPrep, saveDetails, savePrep, setStage } from "./actions";
import { appliedLabel, day, daysSince } from "@/lib/dates";
import { type Application, type Detail, GHOST_DAYS, STAGES, STAGE_LABELS, type Stage } from "@/lib/stages";

export const STAGE_COLORS: Record<Stage, string> = {
  applied: "bg-zinc-100 text-zinc-700 dark:bg-zinc-800 dark:text-zinc-300",
  assessment: "bg-sky-100 text-sky-800 dark:bg-sky-900/50 dark:text-sky-300",
  interview: "bg-violet-100 text-violet-800 dark:bg-violet-900/50 dark:text-violet-300",
  offer: "bg-emerald-600 text-white dark:bg-emerald-500 dark:text-emerald-950",
  rejected: "bg-red-100 text-red-800 dark:bg-red-900/50 dark:text-red-300",
  ghosted: "bg-zinc-200 text-zinc-600 dark:bg-zinc-700 dark:text-zinc-300",
  withdrawn: "bg-zinc-200 text-zinc-600 dark:bg-zinc-700 dark:text-zinc-300",
};
const FIELDS: [Detail, string, string][] = [
  ["referral", "Referral (who)", "text"],
  ["resume", "Resume version", "text"],
  ["contact", "Recruiter / contact", "text"],
  ["link", "Assessment or interview link", "url"],
  ["deadline", "Deadline", "date"],
  ["follow_up", "Follow up on", "date"],
];
const INPUT =
  "mt-1 w-full rounded-lg border border-zinc-300 bg-white px-3 py-2 text-sm dark:border-zinc-700 dark:bg-zinc-950";

export function StageBadge({ stage }: { stage: Stage }) {
  return <span className={`rounded-full px-2 py-0.5 text-xs font-semibold ${STAGE_COLORS[stage]}`}>{STAGE_LABELS[stage]}</span>;
}

/** ids: the card's copies (same company + title, other locations); stage and details apply to all.
 *  The first id is the card's own job (its AI prep). */
export function ApplicationPanel({ ids, app }: { ids: string[]; app: Application | null }) {
  const jobId = ids[0];
  const [pending, startTransition] = useTransition();
  // a stage change shows at once (badge, timeline); the server's answer replaces it
  const [shown, showStage] = useOptimistic(
    { stage: (app?.stage ?? "applied") as Stage, stageAt: app?.stage_at ?? null, events: app?.events ?? [] },
    (s, next: { stage: Stage; at: string }) => ({ stage: next.stage, stageAt: next.at, events: [...s.events, next] }),
  );
  const stage = shown.stage;
  const changeStage = (next: Stage) =>
    startTransition(async () => {
      showStage({ stage: next, at: new Date().toISOString() });
      await setStage(ids, next);
    });
  // still at Applied: no news since you applied
  const lastChange = stage === "applied" ? (app?.applied_at ?? null) : shown.stageAt;
  const ghostly = stage === "applied" && lastChange != null && daysSince(lastChange) >= GHOST_DAYS;

  return (
    <div className="mt-3 space-y-2 text-sm">
      {/* phones: the date on its own line, then the badge and the stage menu side by side */}
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1.5">
        <span className="basis-full font-medium text-zinc-800 sm:basis-auto dark:text-zinc-200">
          {appliedLabel(app?.applied_at ?? null)}
        </span>
        <StageBadge stage={stage} />
        <label className="ml-auto flex items-center gap-1.5 text-zinc-500">
          <span className="sr-only sm:not-sr-only">Stage</span>
          <select
            value={stage}
            disabled={pending}
            onChange={(e) => changeStage(e.target.value as Stage)}
            className="rounded-lg border border-zinc-300 bg-white px-2 py-1.5 text-sm text-zinc-900 disabled:opacity-50 dark:border-zinc-700 dark:bg-zinc-950 dark:text-zinc-100"
          >
            {STAGES.map((s) => (
              <option key={s} value={s}>
                {STAGE_LABELS[s]}
              </option>
            ))}
          </select>
        </label>
      </div>

      {shown.events.length > 0 && (
        <ol className="flex flex-wrap items-center gap-x-1.5 gap-y-1 text-xs text-zinc-500" aria-label="Timeline">
          {shown.events.map((e, i) => (
            <li key={i} className="flex items-center gap-1.5">
              {i > 0 && <span aria-hidden>→</span>}
              <span>
                <span className="font-medium text-zinc-700 dark:text-zinc-300">{STAGE_LABELS[e.stage]}</span> {day(e.at)}
              </span>
            </li>
          ))}
        </ol>
      )}

      <Dates app={app} />

      {ghostly && (
        <div className="flex flex-wrap items-center gap-2 rounded-lg bg-amber-50 px-3 py-2 text-amber-900 dark:bg-amber-950/40 dark:text-amber-200">
          <span>No change in {daysSince(lastChange)} days. Mark as ghosted?</span>
          <button
            disabled={pending}
            onClick={() => changeStage("ghosted")}
            className="rounded-md border border-amber-400 px-2 py-1 text-xs font-medium hover:bg-amber-100 disabled:opacity-50 dark:hover:bg-amber-900/40"
          >
            Mark as ghosted
          </button>
        </div>
      )}

      {(stage === "assessment" || stage === "interview" || app?.prep) && <Prep jobId={jobId} app={app} stage={stage} />}

      <Details ids={ids} app={app} />
    </div>
  );
}

function Dates({ app }: { app: Application | null }) {
  const today = new Date().toLocaleDateString("en-CA", { timeZone: "America/New_York" });
  const chips = (
    [
      ["deadline", "Deadline"],
      ["follow_up", "Follow up"],
    ] as const
  ).filter(([k]) => app?.[k]);
  if (!chips.length) return null;
  return (
    <div className="flex flex-wrap gap-1.5 text-xs">
      {chips.map(([k, label]) => {
        const due = app![k]! <= today;
        return (
          <span
            key={k}
            className={`rounded-full px-2 py-0.5 font-medium ${
              due ? "bg-red-100 text-red-800 dark:bg-red-900/50 dark:text-red-300" : "bg-zinc-100 text-zinc-700 dark:bg-zinc-800 dark:text-zinc-300"
            }`}
          >
            {label} {day(app![k]!)}
          </span>
        );
      })}
    </div>
  );
}

function Prep({ jobId, app, stage }: { jobId: string; app: Application | null; stage: Stage }) {
  const router = useRouter();
  const [requesting, startTransition] = useTransition();
  const [started, setStarted] = useState<boolean | null>(null);
  const [saved, save, saving] = useActionState(savePrep, null);
  const queued = app?.prep_state === "queued";

  // while recon/prep.py writes it (about a minute when started right away), look again every 15 s
  useEffect(() => {
    if (!queued) return;
    const t = setInterval(() => router.refresh(), 15000);
    return () => clearInterval(t);
  }, [queued, router]);

  const canAsk = stage === "assessment" || stage === "interview";
  return (
    <div className="rounded-lg border border-zinc-200 p-3 dark:border-zinc-800">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-medium">AI prep</span>
        {queued ? (
          <span className="text-zinc-500">
            {started === false ? "Queued: the next run writes it (within 30 minutes)." : "Writing it (about a minute)…"}
          </span>
        ) : (
          canAsk && (
            <button
              disabled={requesting}
              onClick={() => startTransition(async () => setStarted(await requestPrep(jobId)))}
              className="rounded-md border border-zinc-300 px-2 py-1 text-xs font-medium hover:bg-zinc-100 disabled:opacity-50 dark:border-zinc-700 dark:hover:bg-zinc-800"
            >
              {app?.prep ? "Write it again" : `Write an ${stage} checklist`}
            </button>
          )
        )}
        {app?.prep_state === "failed" && !queued && <span className="text-red-700 dark:text-red-400">couldn&apos;t write it, try again</span>}
      </div>
      {app?.prep && (
        <form action={save} className="mt-2">
          <input type="hidden" name="jobId" value={jobId} />
          <textarea
            name="prep"
            defaultValue={app.prep}
            key={app.prep}
            rows={Math.min(16, app.prep.split("\n").length + 1)}
            className={`${INPUT} font-mono text-xs leading-relaxed`}
          />
          <div className="mt-1 flex items-center gap-2">
            <button disabled={saving} className="rounded-md border border-zinc-300 px-2 py-1 text-xs font-medium hover:bg-zinc-100 disabled:opacity-50 dark:border-zinc-700 dark:hover:bg-zinc-800">
              {saving ? "Saving…" : "Save edits"}
            </button>
            {saved && !saving && <span className="text-xs text-emerald-700 dark:text-emerald-400">{saved}</span>}
          </div>
        </form>
      )}
    </div>
  );
}

function Details({ ids, app }: { ids: string[]; app: Application | null }) {
  const [saved, save, saving] = useActionState(saveDetails, null);
  const [open, setOpen] = useState(false);
  const filled = FIELDS.filter(([k]) => app?.[k]).length + (app?.notes ? 1 : 0);
  return (
    <details open={open} onToggle={(e) => setOpen(e.currentTarget.open)} className="rounded-lg border border-zinc-200 dark:border-zinc-800">
      <summary className="cursor-pointer px-3 py-2 font-medium">
        Details{filled > 0 && <span className="ml-1.5 text-zinc-500">({filled})</span>}
        {app?.notes && !open && <span className="ml-2 font-normal text-zinc-500">{app.notes.slice(0, 60)}{app.notes.length > 60 ? "…" : ""}</span>}
      </summary>
      <form action={save} className="space-y-3 px-3 pb-3">
        {ids.map((id) => <input key={id} type="hidden" name="jobId" value={id} />)}
        <label className="block">
          <span className="text-zinc-500">Notes</span>
          <textarea name="notes" defaultValue={app?.notes ?? ""} rows={3} className={INPUT} />
        </label>
        <div className="grid gap-3 sm:grid-cols-2">
          {FIELDS.map(([k, label, type]) => (
            <label key={k} className="block">
              <span className="text-zinc-500">{label}</span>
              <input name={k} type={type} defaultValue={app?.[k] ?? ""} className={INPUT} />
            </label>
          ))}
          <label className="block">
            <span className="text-zinc-500">Applied on</span>
            <input
              name="appliedOn"
              type="date"
              defaultValue={app?.applied_at ? new Date(app.applied_at).toLocaleDateString("en-CA", { timeZone: "America/New_York" }) : ""}
              className={INPUT}
            />
          </label>
        </div>
        <div className="flex items-center gap-2">
          <button
            disabled={saving}
            className="rounded-lg bg-zinc-900 px-3 py-1.5 text-sm font-medium text-white disabled:opacity-50 dark:bg-zinc-100 dark:text-zinc-900"
          >
            {saving ? "Saving…" : "Save"}
          </button>
          {saved && !saving && <span className="text-emerald-700 dark:text-emerald-400">{saved}</span>}
        </div>
      </form>
    </details>
  );
}
