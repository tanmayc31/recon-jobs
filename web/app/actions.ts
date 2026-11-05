"use server";

import { cookies } from "next/headers";
import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";
import { COOKIE, MAX_AGE, isCorrectPassword, isValidSession, sessionToken } from "@/lib/auth";
import { STATUSES, type Status, updateStatus } from "@/lib/db";

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
