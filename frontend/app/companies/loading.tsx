import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";

function CompanyCardSkeleton() {
  return (
    <Card aria-hidden="true" className="min-h-44 gap-0 p-5">
      <div className="w-fit rounded-xl border border-border bg-secondary/40 p-1.5 shadow-soft">
        <Skeleton className="h-14 w-14 rounded-lg" />
      </div>
      <div className="mt-auto space-y-2 pt-6">
        <Skeleton className="h-5 w-3/5" />
        <Skeleton className="h-4 w-24" />
      </div>
    </Card>
  );
}

export default function Loading() {
  return (
    <main
      aria-busy="true"
      className="mx-auto w-full max-w-[1680px] px-4 py-10 sm:px-6 sm:py-14 lg:px-10 xl:px-12"
    >
      <span className="sr-only" role="status">
        Loading companies…
      </span>

      <header className="max-w-3xl" aria-hidden="true">
        <Skeleton className="h-3 w-24" />
        <Skeleton className="mt-3 h-11 w-full max-w-xl sm:h-14" />
        <div className="mt-4 max-w-2xl space-y-2">
          <Skeleton className="h-4 w-full" />
          <Skeleton className="h-4 w-5/6" />
        </div>
      </header>

      <div
        className="mb-5 mt-10 flex items-center justify-between gap-4 border-b border-border pb-4"
        aria-hidden="true"
      >
        <Skeleton className="h-3 w-20" />
        <Skeleton className="h-4 w-28" />
      </div>

      <div
        className="grid grid-cols-1 gap-6 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4"
        aria-hidden="true"
      >
        {Array.from({ length: 8 }).map((_, index) => (
          <CompanyCardSkeleton key={index} />
        ))}
      </div>
    </main>
  );
}
