"use client";

import { useActionState } from "react";
import { saveAppliedDates } from "./actions";

// One-time helper: jobs applied before Recon tracked dates. Gone once every one has a date.
export function SetDates({ rows }: { rows: { ids: string[]; company: string; title: string }[] }) {
  const [saved, save, saving] = useActionState(saveAppliedDates, null);
  const today = new Date().toLocaleDateString("en-CA"); // your calendar: no applied dates in the future
  return (
    <details className="mt-3 rounded-xl border border-amber-300 bg-amber-50 text-sm dark:border-amber-800 dark:bg-amber-950/30">
      <summary className="cursor-pointer px-4 py-2.5 font-medium text-amber-900 dark:text-amber-200">
        Set dates for {rows.length} {rows.length === 1 ? "application" : "applications"} without one
        <span className="ml-1.5 font-normal text-amber-800/80 dark:text-amber-300/80">(sorting and stats need them)</span>
      </summary>
      <form action={save} className="border-t border-amber-200 px-4 pb-3 pt-1 dark:border-amber-900">
        <ul className="divide-y divide-amber-200/70 dark:divide-amber-900/60">
          {rows.map((r) => (
            <li key={r.ids.join(",")} className="flex items-center gap-3 py-2">
              <label htmlFor={`d-${r.ids[0]}`} className="min-w-0 flex-1">
                <span className="block truncate font-medium">{r.company}</span>
                <span className="block truncate text-zinc-600 dark:text-zinc-400">{r.title}</span>
              </label>
              <input
                id={`d-${r.ids[0]}`}
                type="date"
                name={`d:${r.ids.join(",")}`}
                max={today}
                className="w-36 shrink-0 rounded-lg border border-zinc-300 bg-white px-2 py-1.5 dark:border-zinc-700 dark:bg-zinc-950"
              />
            </li>
          ))}
        </ul>
        <div className="mt-2 flex items-center gap-2">
          <button
            disabled={saving}
            className="rounded-lg bg-zinc-900 px-3 py-1.5 font-medium text-white disabled:opacity-50 dark:bg-zinc-100 dark:text-zinc-900"
          >
            {saving ? "Saving…" : "Save dates"}
          </button>
          <span className="text-zinc-600 dark:text-zinc-400">{saved ?? "Leave any you don't remember empty."}</span>
        </div>
      </form>
    </details>
  );
}
