import { timingSafeEqual } from "node:crypto";

import { revalidatePath } from "next/cache";

const MAX_BATCH_SIZE = 500;

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

  if (
    typeof body !== "object" ||
    body === null ||
    !("slugs" in body) ||
    !Array.isArray(body.slugs)
  ) {
    return Response.json({ error: "Invalid request body" }, { status: 400 });
  }

  const uniqueSlugs = new Set<string>();

  for (const slug of body.slugs.slice(0, MAX_BATCH_SIZE)) {
    if (typeof slug !== "string" || slug.trim().length === 0) {
      continue;
    }

    uniqueSlugs.add(slug);
  }

  for (const slug of uniqueSlugs) {
    revalidatePath(`/opportunity/${slug}`);
  }

  return Response.json({ revalidated: uniqueSlugs.size });
}
