import type { NextConfig } from "next";

// /api/* is served by app/api/[...path]/route.ts, which caches reads and forwards to FastAPI (API_ORIGIN).
const nextConfig: NextConfig = {
  output: "standalone",
};

export default nextConfig;
