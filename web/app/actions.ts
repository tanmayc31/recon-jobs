"use server";

import { cookies } from "next/headers";
import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";
import { COOKIE, MAX_AGE, isCorrectPassword, isValidSession, sessionToken } from "@/lib/auth";
import { RATINGS, type Rating, STATUSES, type Status, closeJob, jobForCheck, updateRating, updateStatus } from "@/lib/db";
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
