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
