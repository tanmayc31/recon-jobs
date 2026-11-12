"use client";

import { useRouter } from "next/navigation";
import { useId, useRef, useState, useSyncExternalStore, useTransition } from "react";
import { DAYS, MAX_YEARS, MIN_FILINGS, ROLES, SORTS, TIERS, type Filters, parseFilters, toQuery } from "@/lib/filters";

type Props = { tab: string; filters: Filters; companies: string[]; active: number };

// Collapsible on every screen (phones first). Every filter change is a navigation, and Next.js
// remounts the page for new query params, so "open" lives in sessionStorage (per browser tab).
const OPEN_KEY = "recon:filters-open";
const listeners = new Set<() => void>();
const subscribe = (fn: () => void) => {
  listeners.add(fn);
  return () => listeners.delete(fn);
};
const readOpen = () => {
  try {
    return sessionStorage.getItem(OPEN_KEY) === "1";
  } catch {
    return false; // storage blocked: the panel just starts closed
  }
};
function storeOpen(open: boolean) {
  try {
    sessionStorage.setItem(OPEN_KEY, open ? "1" : "0");
  } catch {}
  listeners.forEach((fn) => fn());
}

export function FilterPanel(props: Props) {
  const open = useSyncExternalStore(subscribe, readOpen, () => false); // server: closed
  return <FilterForm key={toQuery(props.filters, props.tab)} {...props} open={open} setOpen={storeOpen} />;
}

const DAY_LABELS: Record<number, string> = { 1: "Last 24h", 3: "Last 3 days", 7: "Last 7 days", 30: "Last 30 days" };

function FilterForm({ tab, filters, companies, active, open, setOpen }: Props & { open: boolean; setOpen: (o: boolean) => void }) {
  const router = useRouter();
  const form = useRef<HTMLFormElement>(null);
  const [pending, startTransition] = useTransition();
  const [fit, setFit] = useState(filters.minFit);
  const [include, setInclude] = useState(filters.companies);
  const [exclude, setExclude] = useState(filters.excluded);

  // Everything goes through parseFilters/toQuery: the URL is always canonical and bookmarkable
  function apply(next?: { include?: string[]; exclude?: string[]; sortChanged?: boolean }) {
    const params = new URLSearchParams();
    for (const [k, v] of new FormData(form.current!).entries()) {
      if (typeof v === "string" && v !== "") params.append(k, v);
    }
    if (next?.sortChanged) params.delete("dir"); // a new sort starts in its own order (Company: A→Z)
    (next?.include ?? include).forEach((c) => params.append("co", c));
    (next?.exclude ?? exclude).forEach((c) => params.append("xco", c));
    const query = toQuery(parseFilters(params, tab), tab);
    startTransition(() => router.push(query ? `/?${query}` : "/", { scroll: false }));
  }

  return (
    <form
      ref={form}
      className="mt-4 rounded-xl border border-zinc-200 bg-white text-sm shadow-sm dark:border-zinc-800 dark:bg-zinc-900"
      onSubmit={(e) => {
        e.preventDefault();
        apply();
      }}
      onChange={(e) => {
        const t = e.target as EventTarget as HTMLInputElement; // the input that changed, not the form
        if (t.type !== "text" && t.type !== "range" && t.name) apply({ sortChanged: t.name === "sort" }); // text: Enter/blur; range: on release
      }}
    >
      <input type="hidden" name="tab" value={tab} />
      <div className="flex flex-wrap items-center gap-2 px-3 py-2">
        <button
          type="button"
          onClick={() => setOpen(!open)}
          aria-expanded={open}
          className="flex flex-1 items-center gap-2 py-1 text-left font-medium"
        >
          <span className={`text-zinc-400 transition-transform ${open ? "rotate-90" : ""}`}>▶</span>
          Filters
          {active > 0 && (
            <span className="rounded-full bg-zinc-900 px-2 py-0.5 text-xs text-white dark:bg-zinc-100 dark:text-zinc-900">{active}</span>
          )}
          {pending && <span className="text-xs font-normal text-zinc-400">updating…</span>}
        </button>
        <label className="sr-only" htmlFor="sort">Sort by</label>
        <select id="sort" name="sort" defaultValue={filters.sort} className={SELECT}>
          {Object.entries(SORTS).map(([k, label]) => (
            <option key={k} value={k}>{label}</option>
          ))}
        </select>
        <label className="sr-only" htmlFor="dir">Order</label>
        <select id="dir" name="dir" defaultValue={filters.dir} className={SELECT} title="Order">
          <option value="desc">↓</option>
          <option value="asc">↑</option>
        </select>
      </div>

      {open && (
        <div className="grid gap-5 border-t border-zinc-200 p-4 dark:border-zinc-800 sm:grid-cols-2">
          <Field label="Role type" wide>
            <div className="flex flex-wrap gap-1.5">
              {Object.entries(ROLES).map(([k, label]) => (
                <Chip key={k} name="role" value={k} checked={filters.roles.includes(k as keyof typeof ROLES)}>
                  {label}
                </Chip>
              ))}
            </div>
          </Field>

          <Field label="Posted">
            <DaysSelect name="posted" value={filters.posted} />
          </Field>
          <Field label="Found by Recon">
            <DaysSelect name="found" value={filters.found} />
          </Field>

          <Field label={`Fit score ≥ ${fit}`}>
            <input
              type="range"
              name="minfit"
              min={0}
              max={100}
              step={5}
              defaultValue={filters.minFit}
              onChange={(e) => setFit(Number(e.target.value))}
              onPointerUp={() => apply()}
              onKeyUp={() => apply()}
              className="w-full accent-zinc-900 dark:accent-zinc-100"
            />
            <Check name="unscored" value="hide" checked={filters.hideUnscored}>Hide unscored jobs</Check>
          </Field>

          <Field label="Tier">
            <div className="flex gap-1.5">
              {TIERS.map((t) => (
                <Chip key={t} name="tier" value={String(t)} checked={filters.tiers.includes(t)}>
                  Tier {t}
                </Chip>
              ))}
            </div>
          </Field>

          <Field label="Company" wide>
            <CompanyPicker
              companies={companies}
              include={include}
              exclude={exclude}
              onChange={(inc, exc) => {
                setInclude(inc);
                setExclude(exc);
                apply({ include: inc, exclude: exc });
              }}
            />
          </Field>

          <Field label="Location">
            <input
              type="text"
              name="loc"
              defaultValue={filters.location}
              placeholder="State or city: WA, Texas, Boston"
              onBlur={(e) => e.target.value.trim() !== filters.location && apply()}
              className={INPUT}
            />
            <Check name="remote" value="1" checked={filters.remote}>Remote only</Check>
          </Field>

          <Field label="H-1B sponsor">
            <Check name="sponsor" value="1" checked={filters.sponsorsOnly}>Sponsors only</Check>
            <select name="minfilings" defaultValue={filters.minFilings ?? ""} className={`${SELECT} mt-2 w-full`}>
              <option value="">Any number of filings</option>
              {MIN_FILINGS.map((n) => (
                <option key={n} value={n}>{n.toLocaleString()}+ SWE filings</option>
              ))}
            </select>
          </Field>

          <Field label="Experience">
            <select name="maxyrs" defaultValue={filters.maxYears ?? ""} className={`${SELECT} w-full`}>
              <option value="">Any years required</option>
              {MAX_YEARS.map((n) => (
                <option key={n} value={n}>Requires ≤ {n} {n === 1 ? "year" : "years"}</option>
              ))}
            </select>
            <Check name="cap" value="hide" checked={filters.hideCap}>Hide jobs with an exp cap</Check>
          </Field>

          <Field label="Flags">
            <select name="resume" defaultValue={filters.resume ?? ""} className={`${SELECT} w-full`}>
              <option value="">Any resume</option>
              <option value="ai">AI resume</option>
              <option value="general">General resume</option>
            </select>
            <Check name="clearance" value="hide" checked={filters.hideClearance}>Hide “clearance preferred”</Check>
          </Field>
        </div>
      )}
    </form>
  );
}

const SELECT =
  "rounded-lg border border-zinc-300 bg-white px-2 py-1.5 text-sm dark:border-zinc-700 dark:bg-zinc-900";
const INPUT =
  "w-full rounded-lg border border-zinc-300 bg-white px-3 py-1.5 text-sm placeholder:text-zinc-400 dark:border-zinc-700 dark:bg-zinc-900";

function Field({ label, wide, children }: { label: string; wide?: boolean; children: React.ReactNode }) {
  return (
    <fieldset className={wide ? "sm:col-span-2" : ""}>
      <legend className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-zinc-500">{label}</legend>
      {children}
    </fieldset>
  );
}

function Chip({ name, value, checked, children }: { name: string; value: string; checked: boolean; children: React.ReactNode }) {
  return (
    <label className="cursor-pointer">
      <input type="checkbox" name={name} value={value} defaultChecked={checked} className="peer sr-only" />
      <span className="inline-block rounded-full border border-zinc-300 px-3 py-1 peer-checked:border-zinc-900 peer-checked:bg-zinc-900 peer-checked:text-white peer-focus-visible:ring-2 peer-focus-visible:ring-zinc-400 dark:border-zinc-700 dark:peer-checked:border-zinc-100 dark:peer-checked:bg-zinc-100 dark:peer-checked:text-zinc-900">
        {children}
      </span>
    </label>
  );
}

function Check({ name, value, checked, children }: { name: string; value: string; checked: boolean; children: React.ReactNode }) {
  return (
    <label className="mt-2 flex cursor-pointer items-center gap-2">
      <input type="checkbox" name={name} value={value} defaultChecked={checked} className="h-4 w-4 accent-zinc-900 dark:accent-zinc-100" />
      {children}
    </label>
  );
}

function DaysSelect({ name, value }: { name: string; value: number | null }) {
  return (
    <select name={name} defaultValue={value ?? ""} className={`${SELECT} w-full`}>
      <option value="">Any time</option>
      {DAYS.map((d) => (
        <option key={d} value={d}>{DAY_LABELS[d]}</option>
      ))}
    </select>
  );
}

function CompanyPicker({ companies, include, exclude, onChange }: {
  companies: string[];
  include: string[];
  exclude: string[];
  onChange: (include: string[], exclude: string[]) => void;
}) {
  const listId = useId();
  const [text, setText] = useState("");
  const match = companies.find((c) => c.toLowerCase() === text.trim().toLowerCase());

  function add(to: "include" | "exclude") {
    if (!match) return;
    const inc = include.filter((c) => c !== match);
    const exc = exclude.filter((c) => c !== match);
    onChange(to === "include" ? [...inc, match] : inc, to === "exclude" ? [...exc, match] : exc);
    setText("");
  }

  return (
    <div>
      <div className="flex flex-wrap gap-2 sm:flex-nowrap">
        {/* no name: typing must not trigger the form's auto-apply */}
        <input
          list={listId}
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              add("include");
            }
          }}
          placeholder={`Search ${companies.length.toLocaleString()} companies`}
          className={`${INPUT} basis-full sm:basis-auto`}
        />
        <datalist id={listId}>
          {companies.map((c) => (
            <option key={c} value={c} />
          ))}
        </datalist>
        <button type="button" disabled={!match} onClick={() => add("include")} className={PICK}>
          Include
        </button>
        <button type="button" disabled={!match} onClick={() => add("exclude")} className={PICK}>
          Exclude
        </button>
      </div>
      {(include.length > 0 || exclude.length > 0) && (
        <div className="mt-2 flex flex-wrap gap-1.5">
          {include.map((c) => (
            <button
              key={c}
              type="button"
              onClick={() => onChange(include.filter((x) => x !== c), exclude)}
              className="rounded-full bg-emerald-100 px-2.5 py-0.5 text-emerald-800 dark:bg-emerald-900/50 dark:text-emerald-300"
              aria-label={`Stop including ${c}`}
            >
              {c} ×
            </button>
          ))}
          {exclude.map((c) => (
            <button
              key={c}
              type="button"
              onClick={() => onChange(include, exclude.filter((x) => x !== c))}
              className="rounded-full bg-red-100 px-2.5 py-0.5 text-red-800 line-through dark:bg-red-900/50 dark:text-red-300"
              aria-label={`Stop excluding ${c}`}
            >
              {c} ×
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

const PICK =
  "shrink-0 rounded-lg border border-zinc-300 px-3 py-1.5 font-medium enabled:hover:bg-zinc-100 disabled:opacity-40 dark:border-zinc-700 dark:enabled:hover:bg-zinc-800";
