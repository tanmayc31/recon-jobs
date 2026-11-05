import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Every page reads the database and the login cookie, so plain dynamic rendering
  // is all we need (no cacheComponents / partialPrefetching).
  // Dev only: let a phone on the same Wi-Fi load the dev server (private IPs, Mac's .local name).
  allowedDevOrigins: ["10.*.*.*", "192.168.*.*", "172.*.*.*", "*.local"],
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
};

export default nextConfig;
