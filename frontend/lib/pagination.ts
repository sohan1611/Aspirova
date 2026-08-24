// Path-based pagination for the ISR landing pages. A page that reads
// `searchParams` can never be statically rendered, so `?page=N` is what forced
// those routes to be per-request; moving the page number into the path is what
// makes them cacheable. Page 1 stays on the bare basePath so the canonical URL
// is unchanged. Mirrors the same shape used by /companies/[slug]/page/[n].
export function buildPagePath(basePath: string, page: number): string {
  return page <= 1 ? basePath : `${basePath}/page/${page}`;
}

export function buildPageHref(
  currentParams: Record<string, string | string[] | undefined>,
  page: number,
  basePath = "/",
): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(currentParams)) {
    if (!value || key === "page") continue;
    const values = Array.isArray(value) ? value : [value];
    for (const item of values) {
      if (item) params.append(key, item);
    }
  }
  params.set("page", String(page));
  return `${basePath}?${params.toString()}`;
}
