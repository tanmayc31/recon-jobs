import "server-only";

// Starts recon.add right away through GitHub Actions (workflow_dispatch, lane "add").
// Needs GITHUB_DISPATCH_TOKEN: a fine-grained token for this repository with Actions: read and
// write, and nothing else. Without it, the next Tier 1-2 run (every 30 minutes) picks it up.
const REPO = process.env.GITHUB_REPO ?? "tanmayc31/recon-jobs";

export async function dispatchAdd(): Promise<boolean> {
  const token = process.env.GITHUB_DISPATCH_TOKEN;
  if (!token) return false;
  const r = await fetch(`https://api.github.com/repos/${REPO}/actions/workflows/recon.yml/dispatches`, {
    method: "POST",
    headers: { Authorization: `Bearer ${token}`, Accept: "application/vnd.github+json", "User-Agent": "recon-jobs" },
    body: JSON.stringify({ ref: "main", inputs: { lane: "add" } }),
    cache: "no-store",
  });
  return r.status === 204;
}
