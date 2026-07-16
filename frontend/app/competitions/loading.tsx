import BrandLoading from "@/components/BrandLoading";
import OpportunityCardSkeleton from "@/components/OpportunityCardSkeleton";
import { Skeleton } from "@/components/ui/skeleton";

export default function Loading() {
  return (
    <main
      aria-busy="true"
      className="mx-auto w-full max-w-[1680px] px-4 py-10 sm:px-6 sm:py-14 lg:px-10 xl:px-12"
    >
      <span className="sr-only" role="status">
        Loading competitions…
      </span>

      <BrandLoading />

      <header className="max-w-3xl" aria-hidden="true">
        <Skeleton className="h-3 w-24" />
        <Skeleton className="mt-3 h-11 w-full max-w-xl sm:h-14" />
        <div className="mt-4 max-w-2xl space-y-2">
          <Skeleton className="h-4 w-full" />
          <Skeleton className="h-4 w-4/5" />
        </div>
      </header>

      <div
        className="mb-5 mt-10 flex flex-wrap items-center justify-between gap-4 border-b border-border pb-4"
        aria-hidden="true"
      >
        <div className="flex min-w-0 flex-wrap items-center gap-x-4 gap-y-2">
          <Skeleton className="h-3 w-24" />
          <Skeleton className="h-4 w-28" />
        </div>
        <div className="flex min-w-0 flex-wrap items-center justify-end gap-2">
          <Skeleton className="mr-1 h-3 w-8" />
          <Skeleton className="h-7 w-20 rounded-full" />
          <Skeleton className="h-7 w-28 rounded-full" />
        </div>
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
