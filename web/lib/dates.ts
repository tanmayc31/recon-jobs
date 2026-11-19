const DAY = 24 * 60 * 60 * 1000;

export function ago(iso: string, now = Date.now()): string {
  const min = Math.max(0, Math.round((now - new Date(iso).getTime()) / 60000));
  if (min < 60) return `${min} min ago`;
  const h = Math.round(min / 60);
  if (h < 48) return `${h} h ago`;
  return `${Math.round(h / 24)} days ago`;
}

// posted_on (the poller resolves Workday's "Posted 3 Days Ago" against the day it read it):
// "posted Nov 12". Workday's "Posted 30+ Days Ago" is only an upper bound: "posted before Oct 13".
export function posted(postedOn: string, postedAt: string | null, now = Date.now()): string {
  const d = new Date(`${postedOn.slice(0, 10)}T00:00:00Z`);
  if (Number.isNaN(d.getTime())) return "";
  const sameYear = d.getUTCFullYear() === new Date(now).getUTCFullYear();
  const day = d.toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    timeZone: "UTC",
    ...(sameYear ? {} : { year: "numeric" }),
  });
  return /30\+/.test(postedAt ?? "") ? `posted before ${day}` : `posted ${day}`;
}

// "updated X ago" only when the site's edit is more than 2 days after the posted date
// (e.g. posted Oct 9, edited today). Needs real dates for both.
export function updated(postedAt: string | null, updatedAt: string | null, now = Date.now()): string | null {
  if (!postedAt || !updatedAt) return null;
  const p = Date.parse(postedAt);
  const u = Date.parse(updatedAt);
  if (Number.isNaN(p) || Number.isNaN(u) || u - p <= 2 * DAY) return null;
  return `updated ${ago(updatedAt, now)}`;
}

// Applications: calendar days where you are (Boston)
const TZ = "America/New_York";
const dayKey = (t: number) => new Date(t).toLocaleDateString("en-CA", { timeZone: TZ }); // YYYY-MM-DD

/** "Nov 18" (with the year when it isn't this year), in Eastern time. A bare YYYY-MM-DD is that day. */
export function day(iso: string, now = Date.now()): string {
  const bare = /^\d{4}-\d{2}-\d{2}$/.test(iso);
  const t = Date.parse(bare ? `${iso}T12:00:00Z` : iso);
  if (Number.isNaN(t)) return "";
  const sameYear = dayKey(t).slice(0, 4) === dayKey(now).slice(0, 4);
  return new Date(t).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    timeZone: bare ? "UTC" : TZ,
    ...(sameYear ? {} : { year: "numeric" }),
  });
}

/** Whole calendar days (Eastern) from iso to now. */
export function daysSince(iso: string, now = Date.now()): number {
  const t = Date.parse(iso);
  return Math.round((Date.parse(dayKey(now)) - Date.parse(dayKey(t))) / DAY);
}

/** "Applied Nov 18 (3 days ago)"; "(today)", "(yesterday)". */
export function appliedLabel(appliedAt: string | null, now = Date.now()): string {
  if (!appliedAt) return "Applied (date not recorded)";
  const n = daysSince(appliedAt, now);
  const rel = n <= 0 ? "today" : n === 1 ? "yesterday" : `${n} days ago`;
  return `Applied ${day(appliedAt, now)} (${rel})`;
}
