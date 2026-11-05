const DAY = 24 * 60 * 60 * 1000;

export function ago(iso: string, now = Date.now()): string {
  const min = Math.max(0, Math.round((now - new Date(iso).getTime()) / 60000));
  if (min < 60) return `${min} min ago`;
  const h = Math.round(min / 60);
  if (h < 48) return `${h} h ago`;
  return `${Math.round(h / 24)} days ago`;
}

// Workday gives text ("Posted 30+ Days Ago"); other sources give a date
export function posted(value: string, now = Date.now()): string {
  if (/^posted\b/i.test(value)) return value.toLowerCase();
  return Number.isNaN(Date.parse(value)) ? `posted ${value}` : `posted ${ago(value, now)}`;
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
