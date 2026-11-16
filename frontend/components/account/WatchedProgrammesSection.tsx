"use client";

import { BellRing } from "lucide-react";
import Link from "next/link";
import { EmptyState, SectionHeader, SettingsCard } from "@/components/account/primitives";
import { useProgrammeWatches } from "@/components/calendar/ProgrammeWatches";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { WATCH_UPDATES_COPY } from "@/lib/programmeWatches";

export default function WatchedProgrammesSection() {
  const { ready, items, error, pending, reload, toggle } = useProgrammeWatches();

  return (
    <section aria-labelledby="account-watched-programmes-heading" className="grid gap-6">
      <SectionHeader id="account-watched-programmes-heading" eyebrow="Alerts" title="Watched programmes" description={WATCH_UPDATES_COPY} />
      <SettingsCard icon={BellRing} title="Your programme watches">
        {error ? (
          <div role="alert" className="flex flex-wrap items-center justify-between gap-3">
            <p className="text-sm text-destructive-text">{error}</p>
            <Button type="button" variant="outline" className="min-h-11" onClick={reload}>Try again</Button>
          </div>
        ) : !ready ? (
          <div role="status" aria-label="Loading watched programmes" className="space-y-3">
            <Skeleton className="h-14 w-full" />
            <Skeleton className="h-14 w-full" />
          </div>
        ) : items.length === 0 ? (
          <EmptyState compact icon={BellRing} title="You aren't watching any programmes yet." description="Find programmes on the hiring calendar and choose Watch & notify." action={<Button asChild className="min-h-11"><Link href="/calendar">Explore the calendar</Link></Button>} />
        ) : (
          <ul className="divide-y divide-border">
            {items.map((item) => (
              <li key={item.id} className="flex min-w-0 flex-wrap items-center justify-between gap-3 py-3 first:pt-0 last:pb-0">
                <Link href={`/programme/${encodeURIComponent(item.programme_slug)}`} className="inline-flex min-h-11 min-w-0 flex-1 basis-48 items-center break-words text-sm font-medium text-primary underline underline-offset-4 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">{item.programme_name}</Link>
                <Button type="button" variant="outline" className="min-h-11" disabled={pending !== null} aria-label={`Stop watching ${item.programme_name}`} onClick={() => void toggle(item.programme_slug)}>Stop watching</Button>
              </li>
            ))}
          </ul>
        )}
      </SettingsCard>
    </section>
  );
}
