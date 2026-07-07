export function buildPageHref(
  currentParams: Record<string, string | undefined>,
  page: number,
  basePath = "/",
): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(currentParams)) {
    if (value && key !== "page") params.set(key, value);
  }
  params.set("page", String(page));
  return `${basePath}?${params.toString()}`;
}
