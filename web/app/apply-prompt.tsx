"use client";

import { useEffect, useRef, useState, useTransition } from "react";
import { answerApplied } from "./actions";

// Apply remembers the job (this browser only); coming back to the Recon tab asks "Did you apply?"
const KEY = "recon:applying";
const MIN_AWAY = 3000; // ms: a quick switch back isn't an application
const MAX_AGE = 7 * 24 * 60 * 60 * 1000;

type Pending = { ids: string[]; title: string; company: string; at: number };

function read(): Pending | null {
  try {
    const p = JSON.parse(localStorage.getItem(KEY) ?? "null") as (Pending & { jobId?: string }) | null;
    if (!p || Date.now() - p.at >= MAX_AGE) return null;
    return { ...p, ids: p.ids ?? (p.jobId ? [p.jobId] : []) }; // saved by the one-id version
  } catch {
    return null;
  }
}

function clear() {
  try {
    localStorage.removeItem(KEY);
  } catch {}
}

// YYYY-MM-DD on your own calendar (not UTC): "yesterday" at 11pm is still yesterday
const localDay = (offset = 0) => {
  const d = new Date();
  d.setDate(d.getDate() + offset);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
};

export function ApplyLink({ ids, title, company, url }: { ids: string[]; title: string; company: string; url: string }) {
  return (
    <a
      href={url}
      target="_blank"
      rel="noopener noreferrer"
      onClick={() => {
        try {
          localStorage.setItem(KEY, JSON.stringify({ ids, title, company, at: Date.now() }));
        } catch {}
      }}
      className="rounded-lg bg-zinc-900 px-4 py-2 text-sm font-medium text-white dark:bg-zinc-100 dark:text-zinc-900"
    >
      Apply ↗
    </a>
  );
}

export function ApplyPrompt() {
  const [job, setJob] = useState<Pending | null>(null);
  const [picking, setPicking] = useState(false);
  const [picked, setPicked] = useState(localDay());
  const [pending, startTransition] = useTransition();
  const dialog = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const check = () => {
      const p = read();
      if (document.visibilityState === "visible" && p?.ids.length && Date.now() - p.at >= MIN_AWAY) setJob(p);
    };
    check();
    document.addEventListener("visibilitychange", check);
    window.addEventListener("focus", check);
    return () => {
      document.removeEventListener("visibilitychange", check);
      window.removeEventListener("focus", check);
    };
  }, []);

  useEffect(() => {
    if (!job) return;
    dialog.current?.querySelector("button")?.focus();
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && close();
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [job]);

  function close() {
    clear();
    setJob(null);
    setPicking(false);
  }

  function answer(a: "applied" | "skipped", day: string | null = null) {
    if (!job) return;
    startTransition(async () => {
      await answerApplied(job.ids, a, day);
      close();
    });
  }

  if (!job) return null;
  const secondary =
    "rounded-lg border border-zinc-300 px-3 py-2.5 text-sm font-medium hover:bg-zinc-100 disabled:opacity-50 dark:border-zinc-700 dark:hover:bg-zinc-800";
  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center bg-black/40 p-4 sm:items-center" onClick={close}>
      <div
        ref={dialog}
        role="dialog"
        aria-modal="true"
        aria-labelledby="apply-prompt-title"
        onClick={(e) => e.stopPropagation()}
        className="w-full max-w-sm rounded-2xl bg-white p-5 shadow-xl dark:bg-zinc-900"
      >
        <h2 id="apply-prompt-title" className="font-semibold leading-snug">
          Did you apply to {job.title} at {job.company}?
        </h2>
        <div className="mt-4 grid gap-2">
          <button
            disabled={pending}
            onClick={() => answer("applied")}
            className="rounded-lg bg-zinc-900 px-4 py-2.5 text-sm font-medium text-white disabled:opacity-50 dark:bg-zinc-100 dark:text-zinc-900"
          >
            Applied today
          </button>
          <div className="grid grid-cols-2 gap-2">
            <button disabled={pending} onClick={() => answer("applied", localDay(-1))} className={secondary}>
              Yesterday
            </button>
            <button disabled={pending} onClick={() => setPicking((p) => !p)} aria-expanded={picking} className={secondary}>
              Pick a date
            </button>
          </div>
          {picking && (
            <div className="flex gap-2">
              <label className="sr-only" htmlFor="applied-on">Applied on</label>
              <input
                id="applied-on"
                type="date"
                value={picked}
                max={localDay()}
                onChange={(e) => setPicked(e.target.value)}
                className="min-w-0 flex-1 rounded-lg border border-zinc-300 bg-white px-3 py-2 text-sm dark:border-zinc-700 dark:bg-zinc-950"
              />
              <button disabled={pending || !picked} onClick={() => answer("applied", picked)} className={secondary}>
                Save
              </button>
            </div>
          )}
          <button disabled={pending} onClick={close} className={secondary}>
            Not yet
          </button>
          <button
            disabled={pending}
            onClick={() => answer("skipped")}
            className="rounded-lg px-4 py-2 text-sm font-medium text-red-700 hover:bg-red-50 disabled:opacity-50 dark:text-red-400 dark:hover:bg-red-950/40"
          >
            Not interested
          </button>
        </div>
      </div>
    </div>
  );
}
