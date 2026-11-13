"use client";

import { useActionState } from "react";
import { checkGone } from "./actions";

// Checks the site right away: a gone job's card closes (the page refreshes); otherwise says so.
export function GoneButton({ jobId }: { jobId: string }) {
  const [verdict, action, pending] = useActionState(checkGone, null);
  return (
    <form action={action} className="flex items-center gap-2">
      <input type="hidden" name="jobId" value={jobId} />
      <button
        disabled={pending}
        title="Check with the company's site whether this job is still open"
        className="rounded-lg border border-zinc-300 px-3 py-2 text-sm font-medium hover:bg-zinc-100 disabled:opacity-50 dark:border-zinc-700 dark:hover:bg-zinc-800"
      >
        {pending ? "Checking…" : "Gone?"}
      </button>
      {!pending && verdict === "open" && <span className="text-sm text-emerald-700 dark:text-emerald-400">still open</span>}
      {!pending && verdict === "unknown" && <span className="text-sm text-zinc-500">couldn&apos;t tell</span>}
      {!pending && verdict === "gone" && <span className="text-sm text-red-700 dark:text-red-400">gone, closed</span>}
    </form>
  );
}
