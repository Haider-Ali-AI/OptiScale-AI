import { timingSafeEqual } from "node:crypto";
import { NextResponse, type NextRequest } from "next/server";

// Hosted single-owner guard (same contract as the backend middleware:
// username "owner", ADS_ACCESS_PASSWORD >= 32 chars). Local dev without a password is open.
export function proxy(request: NextRequest) {
  // Login-free public demo (BC-3): the backend still refuses deletes/key changes.
  if (process.env.ADS_PUBLIC_DEMO === "1") return NextResponse.next();
  const password = process.env.ADS_ACCESS_PASSWORD || "";
  if (!process.env.VERCEL && !password) return NextResponse.next();
  if (password.length < 32) {
    return new NextResponse("Hosted access is not configured.", {
      status: 503,
      headers: { "Cache-Control": "no-store" },
    });
  }
  const expected = Buffer.from(`Basic ${Buffer.from(`owner:${password}`).toString("base64")}`);
  const actual = Buffer.from(request.headers.get("authorization") || "");
  if (actual.length !== expected.length || !timingSafeEqual(actual, expected)) {
    return new NextResponse("Authentication required.", {
      status: 401,
      headers: {
        "WWW-Authenticate": 'Basic realm="OptiScale", charset="UTF-8"',
        "Cache-Control": "no-store",
      },
    });
  }
  return NextResponse.next();
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|icon.svg).*)"],
};
