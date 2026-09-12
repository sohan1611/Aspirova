"use client";

import NextLink from "next/link";
import { useRouter } from "next/navigation";
import { useRef, type ComponentProps } from "react";

type HoverPrefetchLinkProps = ComponentProps<typeof NextLink>;

/**
 * A Link that prefetches on intent rather than on sight.
 *
 * Next prefetches every `<Link>` the moment it scrolls into view. Measured on
 * production: one visit to /jobs plus a single scroll made 81 requests to the
 * CDN, and 45 of those were prefetches - the header and footer links alone
 * accounted for about 39, several fetched three or four times over for different
 * route segments. That is free on a site with headroom; it is not free on a
 * Hobby plan sitting at ~91% of its 1,000,000 monthly edge requests, spending
 * them on a Pricing page nobody opened.
 *
 * The prefetch is therefore driven by `router.prefetch` on first intent, NOT by
 * flipping the `prefetch` prop from `false` to `null` on hover. That second
 * approach is the one the framework guide shows, and it was tried here first and
 * measured as doing nothing at all: with the prop flipped after mount, neither a
 * real hover nor a directly dispatched mouseenter produced a single request. It
 * silently degrades to "no prefetching ever", which is a different product
 * decision wearing this component's name. `router.prefetch` is documented for
 * exactly this case and, unlike the prop, it was verified to fire.
 *
 * Three signals, because hover alone strands two groups: `onFocus` covers
 * keyboard navigation, and `onTouchStart` fires just before a tap on phones,
 * which have no hover at all. The touch head start is small, but it is the
 * difference between prefetching on tap and never prefetching on a phone.
 *
 * Every other prop is forwarded. These links are used inside Radix `asChild`
 * buttons, which clone the child to inject onClick, ref and aria state - a
 * wrapper that swallows props breaks those with no error at all.
 */
export default function HoverPrefetchLink({
  onMouseEnter,
  onFocus,
  onTouchStart,
  href,
  ...props
}: HoverPrefetchLinkProps) {
  const router = useRouter();
  // A ref, not state: warming twice is the only thing to avoid and it must not
  // cause a render.
  const warmed = useRef(false);

  function warm() {
    // router.prefetch takes a string; the object form of href is unused here and
    // is left unprefetched rather than guessed at.
    if (warmed.current || typeof href !== "string") return;
    warmed.current = true;
    router.prefetch(href);
  }

  return (
    <NextLink
      {...props}
      href={href}
      // After the spread, so it wins: viewport prefetching is what this
      // component exists to switch off.
      prefetch={false}
      onMouseEnter={(event) => {
        warm();
        onMouseEnter?.(event);
      }}
      onFocus={(event) => {
        warm();
        onFocus?.(event);
      }}
      onTouchStart={(event) => {
        warm();
        onTouchStart?.(event);
      }}
    />
  );
}
