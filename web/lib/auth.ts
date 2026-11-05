import { createHmac, timingSafeEqual } from "node:crypto";

// One user, one password. The cookie holds an HMAC of the password, never the password
// itself; changing DASHBOARD_PASSWORD logs everyone out.
export const COOKIE = "recon_session";
export const MAX_AGE = 60 * 60 * 24 * 30; // 30 days

function sign(value: string): string {
  return createHmac("sha256", value).update("recon-dashboard-v1").digest("hex");
}

function safeEqual(a: string, b: string): boolean {
  const x = Buffer.from(a);
  const y = Buffer.from(b);
  return x.length === y.length && timingSafeEqual(x, y);
}

export function sessionToken(): string | null {
  const password = process.env.DASHBOARD_PASSWORD;
  return password ? sign(password) : null;
}

export function isValidSession(cookie: string | undefined): boolean {
  const token = sessionToken();
  return !!token && !!cookie && safeEqual(cookie, token);
}

export function isCorrectPassword(attempt: string): boolean {
  const token = sessionToken();
  return !!token && safeEqual(sign(attempt), token);
}
