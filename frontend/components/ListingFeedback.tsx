"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";
import type { Facets } from "@/lib/types";
import { emptyFilterLinks, relativeResultTime } from "@/lib/listState";

function useResultClock() {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 60_000);
    return () => clearInterval(timer);
  }, []);
  return now;
}

export function ListingFailure({ retry, loadedAt, pending = false }: { retry: () => void; loadedAt?: number | null; pending?: boolean }) {
  const now = useResultClock();
  return <div role="status" aria-live="polite" className="my-4 rounded-lg border border-border bg-secondary/40 p-4">
    <p className="text-sm">{loadedAt ? `Couldn't refresh. Showing results from ${relativeResultTime(loadedAt, now)}. These results are stale and may not match your current filters.` : "Couldn't load results. Check your connection and try again."}</p>
    <Button variant="outline" className="mt-3 min-h-11 min-w-11" disabled={pending} onClick={retry}>{pending ? "Retrying…" : "Retry"}</Button>
  </div>;
}

export function ListingSnapshotNotice({ loadedAt, expiresAt }: { loadedAt: number; expiresAt?: number }) {
  const router = useRouter();
  const now = useResultClock();
  if (expiresAt === undefined || now < expiresAt) return null;
  return <div className="my-3 text-sm text-muted-foreground" role="status" aria-live="polite" suppressHydrationWarning>
    <p>These results were last updated <time dateTime={new Date(loadedAt).toISOString()}>{relativeResultTime(loadedAt, now)}</time> and couldn&apos;t be refreshed.</p>
    <Button type="button" variant="outline" className="mt-3 min-h-11" onClick={() => router.refresh()}>Retry</Button>
  </div>;
}

export function ListingUnavailable() {
  const router = useRouter();
  return <ListingFailure retry={() => router.refresh()} />;
}

export function ListingEmpty({ pathname = "/", query = "", title = "No opportunities match this view.", description = "Try dropping the location or search term to broaden your search.", navigate, facets }: { pathname?: string; query?: string; title?: string; description?: string; navigate?: (href: string) => void; facets?: Facets | null }) {
  const chips = emptyFilterLinks(pathname, new URLSearchParams(query), facets);
  return <section className="rounded-lg border border-border bg-card px-5 py-12 text-center" role="status" aria-live="polite">
    <h2 className="font-serif text-xl font-bold">{title}</h2>
    <p className="mx-auto mt-3 max-w-lg text-sm leading-6 text-muted-foreground">{description}</p>
    {chips.length > 0 && <div className="mt-4 flex flex-wrap justify-center gap-2" aria-label="Active filters">{chips.map(chip => <Link key={chip.key} href={chip.href} onClick={navigate ? event => { event.preventDefault(); navigate(chip.href); } : undefined} aria-label={`Remove ${chip.label}`} className="inline-flex min-h-11 items-center gap-2 rounded-full border border-border px-3 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">{chip.label} ×</Link>)}</div>}
    <div className="mt-4 flex flex-wrap justify-center gap-3">
      <Button asChild variant="outline" className="min-h-11"><Link href={pathname} onClick={navigate ? event => { event.preventDefault(); navigate(pathname); } : undefined}>Clear all filters</Link></Button>
      <Button asChild variant="outline" className="min-h-11"><Link href="/calendar">Explore recurring programmes</Link></Button>
    </div>
  </section>;
}
