"use server";

import { cookies } from "next/headers";
import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";
import { COOKIE, MAX_AGE, isCorrectPassword, isValidSession, sessionToken } from "@/lib/auth";
import {
  DETAILS,
  type Detail,
  RATINGS,
  type Rating,
  STAGES,
  STATUSES,
  type Stage,
  type Status,
  closeJob,
  jobForCheck,
  keepAdded,
  queueAdded,
  queuePrep,
  updateDetails,
  updatePrep,
  updateRating,
  updateStage,
  updateStatus,
} from "@/lib/db";
import { dispatchAdd } from "@/lib/dispatch";
import { type Verdict, checkOpen } from "@/lib/gone";

async function requireSession() {
  // Actions are public POST endpoints: check the cookie here too, not just in proxy.ts
  if (!isValidSession((await cookies()).get(COOKIE)?.value)) redirect("/login");
}

export async function setStatus(formData: FormData) {
  await requireSession();
  const jobId = String(formData.get("jobId") ?? "");
  const status = String(formData.get("status") ?? "") as Status;
  if (!jobId || !STATUSES.includes(status)) throw new Error("Bad request");
  await updateStatus(jobId, status);
  revalidatePath("/");
}

// "Did you apply?" popup: Yes -> Applied (today's date), Not interested -> Skipped
export async function answerApplied(jobId: string, answer: "applied" | "skipped") {
  await requireSession();
  if (!jobId || !["applied", "skipped"].includes(answer)) throw new Error("Bad request");
  await updateStatus(jobId, answer);
  revalidatePath("/");
}

export async function setStage(jobId: string, stage: Stage) {
  await requireSession();
  if (!jobId || !STAGES.includes(stage)) throw new Error("Bad request");
  await updateStage(jobId, stage);
  revalidatePath("/");
}

const DATE = /^\d{4}-\d{2}-\d{2}$/;
const DATE_FIELDS: Detail[] = ["deadline", "follow_up"];

export async function saveDetails(_prev: string | null, formData: FormData): Promise<string> {
  await requireSession();
  const jobId = String(formData.get("jobId") ?? "");
  if (!jobId) throw new Error("Bad request");
  const details = Object.fromEntries(
    DETAILS.map((d) => {
      const v = String(formData.get(d) ?? "").trim().slice(0, d === "notes" ? 5000 : 500);
      return [d, v && (!DATE_FIELDS.includes(d) || DATE.test(v)) ? v : null];
    }),
  ) as Record<Detail, string | null>;
  const appliedOn = String(formData.get("appliedOn") ?? "");
  await updateDetails(jobId, details, DATE.test(appliedOn) ? appliedOn : null);
  revalidatePath("/");
  return "Saved";
}

// "AI prep": queued for recon/prep.py, started right away when GITHUB_DISPATCH_TOKEN is set
export async function requestPrep(jobId: string): Promise<boolean> {
  await requireSession();
  if (!jobId) throw new Error("Bad request");
  await queuePrep(jobId);
  revalidatePath("/");
  return dispatchAdd();
}

export async function savePrep(_prev: string | null, formData: FormData): Promise<string> {
  await requireSession();
  const jobId = String(formData.get("jobId") ?? "");
  if (!jobId) throw new Error("Bad request");
  await updatePrep(jobId, String(formData.get("prep") ?? "").slice(0, 10000));
  revalidatePath("/");
  return "Saved";
}

// "1" / "-1" sets 👍 / 👎; "" clears it (pressing your current rating again)
export async function setRating(formData: FormData) {
  await requireSession();
  const jobId = String(formData.get("jobId") ?? "");
  const value = String(formData.get("rating") ?? "");
  const rating = value === "" ? null : (Number(value) as Rating);
  if (!jobId || (rating !== null && !RATINGS.includes(rating))) throw new Error("Bad request");
  await updateRating(jobId, rating);
  revalidatePath("/");
}

// "Gone?": ask the site right now. Gone closes the card (it leaves New/Backlog/Later).
export async function checkGone(_prev: Verdict | null, formData: FormData): Promise<Verdict> {
  await requireSession();
  const job = await jobForCheck(String(formData.get("jobId") ?? ""));
  if (!job) throw new Error("Bad request");
  const verdict = await checkOpen(job);
  if (verdict === "gone") {
    await closeJob(job.job_id);
    revalidatePath("/");
  }
  return verdict;
}

// "Add job": queue the URL and start recon.add (it reads, filters and judges it)
export async function addJob(_prev: string | null, formData: FormData): Promise<string> {
  await requireSession();
  const raw = String(formData.get("url") ?? "").trim();
  let url: URL;
  try {
    url = new URL(raw);
  } catch {
    return "That isn't a link.";
  }
  if (!["http:", "https:"].includes(url.protocol)) return "That isn't a web link.";
  await queueAdded(url.toString());
  revalidatePath("/");
  return (await dispatchAdd())
    ? "Adding it: about a minute."
    : "Queued: the next run picks it up (within 30 minutes).";
}

export async function keepJob(formData: FormData) {
  await requireSession();
  if (!(await keepAdded(String(formData.get("id") ?? "")))) throw new Error("Bad request");
  await dispatchAdd(); // judge it now
  revalidatePath("/");
}

export async function login(_prev: string | null, formData: FormData): Promise<string | null> {
  const token = sessionToken();
  if (!token) return "DASHBOARD_PASSWORD is not set on the server.";
  if (!isCorrectPassword(String(formData.get("password") ?? ""))) {
    await new Promise((r) => setTimeout(r, 500)); // slow down guessing
    return "Wrong password.";
  }
  (await cookies()).set(COOKIE, token, {
    httpOnly: true,
    secure: process.env.NODE_ENV === "production",
    sameSite: "lax",
    path: "/",
    maxAge: MAX_AGE,
  });
  redirect("/");
}

export async function logout() {
  (await cookies()).delete(COOKIE);
  redirect("/login");
}
