import "server-only";

// "Gone?" on a card: the same check as recon/linkcheck.py is_open, through the site's own API.
// HTTP status of the job page can't tell (Workday answers 200 for a taken-down job).

export type OpenCheck = { job_id: string; source: string; url: string; source_ids: string | null };
export type Verdict = "open" | "gone" | "unknown";

const HEADERS = { "User-Agent": "recon-jobs/0.2" };
// public job URL -> [tenant, wdN, site, path]
const WORKDAY: [RegExp, (m: RegExpMatchArray) => string[]][] = [
  [
    /^https:\/\/([^./]+)\.(wd\d+)\.myworkdayjobs\.com\/(?:[a-z]{2}-[A-Z]{2}\/)?([^/]+)(\/job\/.+)$/,
    (m) => [m[1], m[2], m[3], m[4]],
  ],
  [
    /^https:\/\/(wd\d+)\.myworkdaysite\.com\/(?:[a-z]{2}-[A-Z]{2}\/)?recruiting\/([^/]+)\/([^/]+)(\/job\/.+)$/,
    (m) => [m[2], m[1], m[3], m[4]],
  ],
];
// boards whose Ashby job pages are switched off but whose own site has them (recon/sources/ashby.py CAREERS)
const ASHBY_CAREERS = new Set(["cursor"]);

export function workdayApi(url: string): string | null {
  for (const [rx, parts] of WORKDAY) {
    const m = url.match(rx);
    if (m) {
      const [tenant, wd, site, path] = parts(m);
      return `https://${tenant}.${wd}.myworkdayjobs.com/wday/cxs/${tenant}/${site}${path}`;
    }
  }
  return null;
}

async function get(url: string): Promise<Response> {
  return fetch(url, { headers: HEADERS, cache: "no-store", signal: AbortSignal.timeout(15000) });
}

export async function checkOpen(job: OpenCheck): Promise<Verdict> {
  // "greenhouse:stripe:7012345": source, board slug, the site's own ID (which may contain ":")
  const a = job.job_id.indexOf(":");
  const b = job.job_id.indexOf(":", a + 1);
  const [source, slug, id] = [job.job_id.slice(0, a), job.job_id.slice(a + 1, b), job.job_id.slice(b + 1)];
  try {
    if (source === "workday") {
      const api = workdayApi(job.url);
      if (!api) return "unknown";
      const r = await get(api);
      if (r.status === 200) return "jobPostingInfo" in (await r.json()) ? "open" : "unknown";
      return [403, 404, 410].includes(r.status) ? "gone" : "unknown";
    }
    if (source === "greenhouse" || source === "lever") {
      const r = await get(
        source === "greenhouse"
          ? `https://boards-api.greenhouse.io/v1/boards/${slug}/jobs/${id}`
          : `https://api.lever.co/v0/postings/${slug}/${id}`,
      );
      return r.status === 200 ? "open" : r.status === 404 ? "gone" : "unknown";
    }
    if (source === "ashby") {
      const r = await get(`https://api.ashbyhq.com/posting-api/job-board/${slug}`);
      if (r.status !== 200) return "unknown";
      const jobs: { id: string; isListed?: boolean }[] = (await r.json()).jobs ?? [];
      if (!jobs.some((j) => j.id === id && j.isListed !== false)) return "gone";
      if (!ASHBY_CAREERS.has(slug) && (await get(`https://jobs.ashbyhq.com/${slug}`)).status === 404) return "gone";
      return "open";
    }
    if (source === "amazon") {
      for (const req of (job.source_ids ?? "").split(",").filter(Boolean)) {
        if ((await get(`https://www.amazon.jobs/en/jobs/${req}`)).status === 200) return "open";
      }
      return "gone";
    }
  } catch {
    return "unknown";
  }
  return "unknown";
}
