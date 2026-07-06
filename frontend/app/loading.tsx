import { Skeleton } from "@/components/ui/skeleton";

// Next.js's route-segment loading convention - shown automatically while
// the feed/search Server Component re-fetches after a filter change or
// navigation. A real Suspense boundary, not client-side loading state, so
// the page itself stays a Server Component (Doc handoffs/
// PHASE-2.5-HANDOFF.md sec 3.4 acceptance).
export default function Loading() {
  return (
    <main className="mx-auto max-w-3xl px-4 py-8">
      <div className="mb-6 flex flex-wrap items-center gap-3">
        <Skeleton className="h-10 w-64" />
        <Skeleton className="h-10 w-32" />
        <Skeleton className="h-10 w-32" />
      </div>

      <Skeleton className="mb-3 h-4 w-32" />

      <div className="space-y-3">
        {Array.from({ length: 6 }).map((_, i) => (
          <div key={i} className="flex gap-3 rounded-lg border border-border p-4">
            <Skeleton className="h-9 w-9 shrink-0 rounded-md" />
            <div className="flex-1 space-y-2">
              <Skeleton className="h-4 w-1/2" />
              <Skeleton className="h-3 w-1/3" />
            </div>
          </div>
        ))}
      </div>
    </main>
  );
}
