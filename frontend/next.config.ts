import path from "path";
import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // An unrelated package-lock.json elsewhere on this machine was confusing
  // Turbopack's auto-detected workspace root. This repo's frontend/ is the
  // actual root.
  turbopack: {
    root: path.join(__dirname),
  },
};

export default nextConfig;
