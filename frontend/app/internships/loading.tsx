import OpportunityCardSkeleton from "@/components/OpportunityCardSkeleton";
import { Skeleton } from "@/components/ui/skeleton";

export default function Loading() {
  return (
    <main aria-busy="true" className="mx-auto max-w-3xl px-4 py-8">
      <span className="sr-only" role="status">
        Loading internships…
      </span>

      <header className="mb-6" aria-hidden="true">
        <Skeleton className="h-3 w-24" />
        <Skeleton className="mt-3 h-9 w-48" />
        <div className="mt-2 max-w-2xl space-y-2">
          <Skeleton className="h-4 w-full" />
          <Skeleton className="h-4 w-4/5" />
        </div>
      </header>

      <div className="mb-3" aria-hidden="true">
        <Skeleton className="h-4 w-28" />
      </div>

      <div className="space-y-3" aria-hidden="true">
        {Array.from({ length: 5 }).map((_, index) => (
          <OpportunityCardSkeleton key={index} />
        ))}
      </div>
    </main>
  );
}
