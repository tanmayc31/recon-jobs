import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";
import { COOKIE, isValidSession } from "@/lib/auth";

// Every page except /login needs the session cookie.
export function proxy(request: NextRequest) {
  if (isValidSession(request.cookies.get(COOKIE)?.value)) {
    return NextResponse.next();
  }
  return NextResponse.redirect(new URL("/login", request.url));
}

export const config = {
  matcher: ["/((?!login|_next/static|_next/image|favicon.ico).*)"],
};
