import type { NextConfig } from "next";

// Legacy deep links from the reference UI keep working via temporary redirects.
const legacy: Record<string, string> = {
  "/data-studio": "/data",
  "/budget-optimizer": "/budget",
  "/ml-studio": "/models",
  "/big-data-lab": "/lab",
  "/ai-assistant": "/assistant",
  "/help": "/methodology",
};

const config: NextConfig = {
  devIndicators: false,
  poweredByHeader: false,
  async redirects() {
    return Object.entries(legacy).map(([source, destination]) => ({ source, destination, permanent: false }));
  },
  async rewrites() {
    // On Vercel, vercel.json routes /api/v1/* to the Python function instead.
    if (process.env.VERCEL) return [];
    return [
      {
        source: "/api/v1/:path*",
        destination: `${process.env.API_ORIGIN || "http://127.0.0.1:8000"}/api/v1/:path*`,
      },
    ];
  },
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "Referrer-Policy", value: "same-origin" },
          { key: "X-Frame-Options", value: "DENY" },
        ],
      },
    ];
  },
};
export default config;
