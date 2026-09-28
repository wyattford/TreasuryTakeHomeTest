import path from "node:path";
import type { NextConfig } from "next";

// Set at build time in the Docker image (see docker-compose.yml): the
// backend's address on the internal network. When set, the frontend serves
// the API under its own origin at /api, so the whole app is one port behind
// the reverse proxy and the browser never needs CORS.
const backendUrl = process.env.BACKEND_INTERNAL_URL;

const nextConfig: NextConfig = {
  // Pins the workspace root explicitly so Turbopack doesn't try to infer it
  // from a package-lock.json elsewhere on disk (e.g. in a parent directory).
  turbopack: {
    root: path.join(__dirname),
  },
  output: "standalone",
  experimental: {
    // POST /reviews can wait on a label that's still being read, and
    // extraction status requests long-poll for 25 s; Next's default proxy
    // timeout is 30 s.
    proxyTimeout: 120_000,
  },
  async rewrites() {
    return backendUrl ? [{ source: "/api/:path*", destination: `${backendUrl}/:path*` }] : [];
  },
};

export default nextConfig;
