// Opens links from a sandboxed email preview in a new tab. Otherwise the
// destination would try to load inside the frame, which the site refuses.
export function withNewTabLinks(html: string): string {
  const base = '<base target="_blank">';
  return /<head(\s[^>]*)?>/i.test(html)
    ? html.replace(/<head(\s[^>]*)?>/i, (head) => `${head}${base}`)
    : `${base}${html}`;
}
