"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useActionState, useEffect, useState } from "react";
import { addJob, keepJob } from "./actions";
import type { Added } from "@/lib/db";

const STATE: Record<string, string> = {
  queued: "text-zinc-500",
  added: "text-emerald-700 dark:text-emerald-400",
  kept: "text-emerald-700 dark:text-emerald-400",
  skipped: "text-amber-700 dark:text-amber-400",
  gone: "text-red-700 dark:text-red-400",
  failed: "text-red-700 dark:text-red-400",
  "needs link": "text-amber-700 dark:text-amber-400",
};

// Paste any job link: recon/add.py reads the real posting, runs the filters and the AI judge.
export function AddJob({ recent }: { recent: Added[] }) {
  const [note, action, pending] = useActionState(addJob, null);
  const router = useRouter();
  const waiting = recent.some((a) => a.state === "queued");
  const [open, setOpen] = useState(waiting); // stays open once you open it, even after a refresh
  useEffect(() => {
    if (!waiting) return;
    const t = setInterval(() => router.refresh(), 10000); // until recon.add has handled it
    return () => clearInterval(t);
  }, [waiting, router]);

  return (
    <details
      className="mt-3 rounded-xl border border-zinc-200 bg-white text-sm dark:border-zinc-800 dark:bg-zinc-900"
      open={open}
      onToggle={(e) => setOpen(e.currentTarget.open)}
    >
      <summary className="cursor-pointer px-4 py-2.5 font-medium">Add job</summary>
      <div className="space-y-3 border-t border-zinc-200 p-4 dark:border-zinc-800">
        <form action={action} className="flex gap-2">
          <input
            name="url"
            type="url"
            required
            placeholder="Paste a job link (company site, Greenhouse, Workday…)"
            className="min-w-0 flex-1 rounded-lg border border-zinc-300 bg-transparent px-3 py-2 dark:border-zinc-700"
          />
          <button disabled={pending} className="rounded-lg bg-zinc-900 px-4 py-2 font-medium text-white disabled:opacity-50 dark:bg-zinc-100 dark:text-zinc-900">
            {pending ? "Adding…" : "Add"}
          </button>
        </form>
        {note && <p className="text-zinc-600 dark:text-zinc-400">{note}</p>}
        {recent.length > 0 && (
          <ul className="space-y-2">
            {recent.map((a) => (
              <li key={a.id} className="flex flex-wrap items-center gap-x-2 gap-y-1">
                <span className={`font-medium ${STATE[a.state] ?? ""}`}>{a.state === "queued" ? "adding…" : a.state}</span>
                <span className="min-w-0 flex-1 truncate text-zinc-500" title={a.url}>
                  {a.message ?? a.url}
                </span>
                {a.state === "skipped" && (
                  <form action={keepJob}>
                    <input type="hidden" name="id" value={a.id} />
                    <button className="rounded-lg border border-zinc-300 px-2 py-1 text-xs font-medium hover:bg-zinc-100 dark:border-zinc-700 dark:hover:bg-zinc-800">
                      Keep anyway
                    </button>
                  </form>
                )}
                {(a.state === "added" || a.state === "kept") && a.job_id && (
                  <Link href="/?tab=new&sort=found" className="text-xs underline">
                    see it in New
                  </Link>
                )}
              </li>
            ))}
          </ul>
        )}
      </div>
    </details>
  );
}
