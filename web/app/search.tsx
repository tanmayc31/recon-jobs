"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useEffect, useRef, useState, useTransition } from "react";

// Instant search on company and title, kept in the URL (?q=) with the other filters. Outside the
// filter panel's form so typing never remounts it (lib/filters.ts q).
const WAIT = 250; // ms after the last key

export function SearchBox({ q, tab }: { q: string; tab: string }) {
  const router = useRouter();
  const path = usePathname();
  const params = useSearchParams();
  const [text, setText] = useState(q);
  const [pending, startTransition] = useTransition();
  const timer = useRef<ReturnType<typeof setTimeout>>(undefined);

  useEffect(() => () => clearTimeout(timer.current), []);

  function go(value: string) {
    const next = new URLSearchParams(params.toString());
    const v = value.trim();
    if (v) next.set("q", v);
    else next.delete("q");
    next.delete("limit"); // a new search starts at the first page
    const query = next.toString();
    startTransition(() => router.replace(query ? `${path}?${query}` : path, { scroll: false }));
  }

  return (
    <div className="relative mt-4">
      <label htmlFor="search" className="sr-only">Search company or title</label>
      <input
        id="search"
        type="search"
        value={text}
        autoComplete="off"
        enterKeyHint="search"
        placeholder={tab === "applied" ? "Search your applications: company or title" : "Search company or title"}
        onChange={(e) => {
          setText(e.target.value);
          clearTimeout(timer.current);
          const value = e.target.value;
          timer.current = setTimeout(() => go(value), WAIT);
        }}
        onKeyDown={(e) => {
          if (e.key === "Enter") {
            clearTimeout(timer.current);
            go(text);
          }
          if (e.key === "Escape" && text) {
            setText("");
            go("");
          }
        }}
        className="w-full rounded-xl border border-zinc-200 bg-white py-2.5 pl-10 pr-20 text-sm shadow-sm placeholder:text-zinc-400 dark:border-zinc-800 dark:bg-zinc-900"
      />
      <span aria-hidden className="pointer-events-none absolute left-3.5 top-1/2 -translate-y-1/2 text-zinc-400">
        <svg width="16" height="16" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="2">
          <circle cx="9" cy="9" r="6" />
          <path d="m14 14 4 4" strokeLinecap="round" />
        </svg>
      </span>
      {pending && <span className="absolute right-3 top-1/2 -translate-y-1/2 text-xs text-zinc-400">searching…</span>}
    </div>
  );
}
