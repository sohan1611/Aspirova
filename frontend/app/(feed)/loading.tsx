import OpportunityCardSkeleton from "@/components/OpportunityCardSkeleton";
import SignedOutHero from "@/components/SignedOutHero";
import { Skeleton } from "@/components/ui/skeleton";

export default function Loading() {
  return (
    <main
      aria-busy="true"
      className="mx-auto max-w-[1680px] px-4 pb-10 sm:px-6 lg:px-10 xl:px-12"
    >
      <span className="sr-only" role="status">
        Loading opportunities…
      </span>

      <SignedOutHero />

      <div className="mb-6 scroll-mt-20 pt-10" aria-hidden="true">
        <div className="flex flex-col gap-3">
          <div className="flex flex-wrap items-center gap-3">
            <div className="flex w-full min-w-0 gap-2 sm:w-auto">
              <Skeleton className="h-9 min-w-0 flex-1 sm:w-72 sm:flex-none" />
              <Skeleton className="h-9 w-20 shrink-0" />
            </div>
            <div className="ml-auto flex w-full items-center justify-end gap-2 sm:w-auto">
              <Skeleton className="h-9 w-24" />
              <Skeleton className="h-9 w-36" />
            </div>
          </div>
        </div>
      </div>

      <div
        className="mb-3 flex flex-wrap items-center justify-between gap-3"
        aria-hidden="true"
      >
        <Skeleton className="h-4 w-32" />
        <Skeleton className="h-8 w-44 max-w-full" />
      </div>

      <div
        className="grid grid-cols-1 gap-6 sm:grid-cols-2 lg:grid-cols-3"
        aria-hidden="true"
      >
        {Array.from({ length: 9 }).map((_, index) => (
          <OpportunityCardSkeleton key={index} />
        ))}
      </div>
    </main>
  );
}
