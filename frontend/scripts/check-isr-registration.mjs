import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

// Keep this list in sync with every dynamic route intentionally registered for ISR.
const REQUIRED_ISR_ROUTES = [
  "/companies/[slug]",
  "/companies/[slug]/opengraph-image",
  "/companies/[slug]/page/[n]",
  "/opportunity/[slug]",
  "/opportunity/[slug]/opengraph-image",
  "/programme/[slug]",
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

console.log(`ISR registration check passed: verified ${REQUIRED_ISR_ROUTES.length} routes.`);
