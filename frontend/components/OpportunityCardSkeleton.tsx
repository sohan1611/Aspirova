import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";

export default function OpportunityCardSkeleton({ competition = false }: { competition?: boolean }) {
  return (
    <Card aria-hidden="true" className="h-full gap-3 overflow-hidden p-4 sm:p-5">
      {competition && <Skeleton className="-mx-4 -mt-4 h-28 rounded-none sm:-mx-5 sm:-mt-5 sm:h-32" />}
      <div className="flex items-start justify-between gap-3">
        <Skeleton className="h-6 w-24 shrink-0 rounded-md" />
        <Skeleton className="mt-1 h-4 w-28" />
      </div>

      <div className="space-y-2">
        <Skeleton className="h-6 w-11/12" />
        <Skeleton className="h-6 w-3/5" />
      </div>

      <Skeleton className="h-4 w-full" />
      <Skeleton className="h-4 w-4/5" />

      <div className="mt-auto flex items-center gap-2 border-t border-border pt-3">
        <Skeleton className="h-3.5 w-3.5 shrink-0 rounded-full" />
        <Skeleton className="h-3 w-28 max-w-[70%]" />
      </div>

      <div className="flex flex-wrap items-center justify-between gap-2 pt-1">
        <Skeleton className="h-6 w-28 rounded-md" />
        <Skeleton className="h-8 w-8 rounded-md" />
      </div>
    </Card>
  );
}
