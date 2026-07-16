const LEADING_SEPARATORS = /^[\s,;/|·–—-]+/;
const TRAILING_SEPARATORS = /[\s,;/|·–—-]+$/;

/**
 * Normalizes a crawled `location` string for display. Some sources emit values
 * with a dangling separator or stray comma (e.g. "Peterlee,"), which otherwise
 * render as "Peterlee, - Remote" once joined with other meta. This collapses
 * internal whitespace and strips leading/trailing separators (commas,
 * semicolons, slashes, pipes, dashes, middots) while PRESERVING internal ones
 * like the hyphen in "Winston-Salem". Returns "" when nothing meaningful
 * remains, so callers can treat the result as falsy.
 */
export function cleanLocation(value: string | null | undefined): string {
  if (!value) {
    return "";
  }
  return value
    .replace(/\s+/g, " ")
    .replace(LEADING_SEPARATORS, "")
    .replace(TRAILING_SEPARATORS, "")
    .trim();
}
