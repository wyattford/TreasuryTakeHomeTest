import path from "node:path";
import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Pins the workspace root explicitly so Turbopack doesn't try to infer it
  // from a package-lock.json elsewhere on disk (e.g. in a parent directory).
  turbopack: {
    root: path.join(__dirname),
  },
};

export default nextConfig;
