import { timingSafeEqual } from "node:crypto";

import { revalidatePath } from "next/cache";

import { LANDING_PATHS } from "@/lib/landing";

const MAX_BATCH_SIZE = 500;
const MAX_SLUG_LENGTH = 120;
// Slugs come from `_slugify`; anything outside this shape is not a real slug and
// could invalidate another path when interpolated.
const SLUG_PATTERN = /^[a-z0-9][a-z0-9-]*$/;
// List paths are matched by exact membership, never interpolated. The caller only
// ever gets to pick from this set, so a compromised or buggy crawler cannot
// invalidate arbitrary routes - the same reasoning as SLUG_PATTERN above.
const ALLOWED_PATHS: ReadonlySet<string> = new Set(LANDING_PATHS);

function isAuthorized(request: Request, secret: string): boolean {
  const authorization = request.headers.get("authorization");

  if (!authorization?.startsWith("Bearer ")) {
    return false;
  }

  const suppliedSecret = Buffer.from(authorization.slice("Bearer ".length));
  const expectedSecret = Buffer.from(secret);

  return (
    suppliedSecret.length === expectedSecret.length &&
    timingSafeEqual(suppliedSecret, expectedSecret)
  );
}

export async function POST(request: Request) {
  const secret = process.env.REVALIDATE_SECRET;

  if (!secret) {
    return Response.json({ error: "Revalidation is not configured" }, { status: 503 });
  }

  if (!isAuthorized(request, secret)) {
    return Response.json({ error: "Unauthorized" }, { status: 401 });
  }

  let body: unknown;

  try {
    body = await request.json();
  } catch {
    return Response.json({ error: "Invalid request body" }, { status: 400 });
  }

  if (typeof body !== "object" || body === null) {
    return Response.json({ error: "Invalid request body" }, { status: 400 });
  }

  // `slugs` stays optional so an existing slugs-only caller is unaffected, and
  // `paths` can be sent on its own. A payload carrying neither is still a 400.
  const rawSlugs = "slugs" in body && Array.isArray(body.slugs) ? body.slugs : null;
  const rawPaths = "paths" in body && Array.isArray(body.paths) ? body.paths : null;

  if (rawSlugs === null && rawPaths === null) {
    return Response.json({ error: "Invalid request body" }, { status: 400 });
  }

  const uniqueSlugs = new Set<string>();

  for (const slug of (rawSlugs ?? []).slice(0, MAX_BATCH_SIZE)) {
    if (typeof slug !== "string" || slug.trim().length === 0) {
      continue;
    }

    if (slug.length > MAX_SLUG_LENGTH || !SLUG_PATTERN.test(slug)) {
      continue;
    }

    uniqueSlugs.add(slug);
  }

  const uniquePaths = new Set<string>();

  for (const path of (rawPaths ?? []).slice(0, MAX_BATCH_SIZE)) {
    if (typeof path === "string" && ALLOWED_PATHS.has(path)) {
      uniquePaths.add(path);
    }
  }

  for (const slug of uniqueSlugs) {
    revalidatePath(`/opportunity/${slug}`);
  }

  for (const path of uniquePaths) {
    revalidatePath(path);
    // Revalidating "/jobs" does not touch "/jobs/page/2" - a dynamic segment has
    // to be invalidated by its route pattern. Without this the paginated pages
    // would stay stale until their own 6h window expired.
    revalidatePath(`${path}/page/[n]`, "page");
  }

  return Response.json({
    revalidated: uniqueSlugs.size,
    paths: uniquePaths.size,
  });
}
