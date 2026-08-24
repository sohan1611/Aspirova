import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

// Keep this list in sync with every dynamic route intentionally registered for ISR.
const REQUIRED_ISR_ROUTES = [
  "/companies/[slug]",
  "/companies/[slug]/page/[n]",
  "/internships/page/[n]",
  "/jobs/page/[n]",
  "/opportunity/[slug]",
  "/programme/[slug]",
  "/remote/page/[n]",
];

const scriptDirectory = path.dirname(fileURLToPath(import.meta.url));
const frontendDirectory = path.resolve(scriptDirectory, "..");
const manifestPath = path.join(
  frontendDirectory,
  ".next",
  "prerender-manifest.json",
);

if (!fs.existsSync(manifestPath)) {
  console.error(
    "ISR registration check failed: prerender manifest not found. Run `pnpm build` first.",
  );
  process.exit(1);
}

let manifest;

try {
  manifest = JSON.parse(fs.readFileSync(manifestPath, "utf8"));
} catch {
  console.error("ISR registration check failed: could not read prerender manifest.");
  process.exit(1);
}

// The landing pages are static routes, not dynamic segments, so they never appear
// in dynamicRoutes and the check above cannot see them. They regress a different
// way: re-introducing `searchParams` makes them per-request again and silently
// drops the cache entirely, which is exactly how they were found broken. Assert
// the ISR window instead. The value must match `export const revalidate` in each
// page and LANDING_REVALIDATE in lib/landing.ts.
const REQUIRED_STATIC_ISR_ROUTES = {
  "/internships": 21600,
  "/jobs": 21600,
  "/remote": 21600,
};

const staticRoutes = manifest.routes ?? {};
const staticProblems = [];

for (const [route, expected] of Object.entries(REQUIRED_STATIC_ISR_ROUTES)) {
  const entry = staticRoutes[route];

  if (!entry) {
    staticProblems.push(`${route} is not statically prerendered (likely reads searchParams)`);
    continue;
  }

  if (entry.initialRevalidateSeconds !== expected) {
    staticProblems.push(
      `${route} has initialRevalidateSeconds=${entry.initialRevalidateSeconds}, expected ${expected}`,
    );
  }
}

if (staticProblems.length > 0) {
  console.error("ISR registration check failed: static landing routes:");

  for (const problem of staticProblems) {
    console.error(problem);
  }

  console.error(
    "A route that awaits `searchParams` cannot be static, and a fetch revalidate lower than the page's caps its ISR window.",
  );
  process.exit(1);
}

const dynamicRoutes = manifest.dynamicRoutes ?? {};
const missingRoutes = REQUIRED_ISR_ROUTES.filter(
  (route) => !Object.prototype.hasOwnProperty.call(dynamicRoutes, route),
);

if (missingRoutes.length > 0) {
  console.error("ISR registration check failed: missing dynamic routes:");

  for (const route of missingRoutes) {
    console.error(route);
  }

  console.error(
    "These routes are no longer ISR-registered. The usual cause is a removed or renamed `generateStaticParams` export.",
  );
  process.exit(1);
}

console.log(
  `ISR registration check passed: verified ${REQUIRED_ISR_ROUTES.length} dynamic routes ` +
    `and ${Object.keys(REQUIRED_STATIC_ISR_ROUTES).length} static landing routes.`,
);
