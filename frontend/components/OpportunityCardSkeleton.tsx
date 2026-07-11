import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";

export default function OpportunityCardSkeleton() {
  return (
    <Card aria-hidden="true" className="h-full gap-3 p-5">
      <div className="flex items-start justify-between gap-3">
        <Skeleton className="h-11 w-11 shrink-0 rounded-lg" />
        <Skeleton className="mt-1 h-3 w-14" />
      </div>

      <div className="space-y-2">
        <Skeleton className="h-5 w-11/12" />
        <Skeleton className="h-5 w-3/5" />
      </div>

      <Skeleton className="h-4 w-2/5" />

      <div className="flex items-center gap-2">
        <Skeleton className="h-3.5 w-3.5 shrink-0 rounded-full" />
        <Skeleton className="h-3 w-28 max-w-[70%]" />
      </div>

      <div className="mt-auto flex flex-wrap items-center justify-between gap-2 border-t border-border/60 pt-1">
        <Skeleton className="h-6 w-20 rounded-full" />
        <Skeleton className="h-7 w-28" />
      </div>
    </Card>
  );
}
