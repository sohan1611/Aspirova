import { Clock } from "lucide-react";
import Link from "next/link";
import { Badge } from "@/components/ui/badge";
import CompanyFavicon from "@/components/CompanyFavicon";
import type { OpportunityListItem } from "@/lib/types";

const CATEGORY_LABEL: Record<string, string> = {
  internship: "Internship",
  job: "Job",
};

export default function OpportunityCard({ item }: { item: OpportunityListItem }) {
  const metaParts = [
    item.company?.name ?? "Unknown company",
    item.location,
  ].filter(Boolean);

  return (
    <Link
      href={`/opportunity/${item.slug}`}
      className="group flex h-full gap-4 rounded-xl border border-border bg-card p-5 shadow-soft transition-[transform,box-shadow,border-color] duration-300 ease-premium hover:-translate-y-0.5 hover:border-primary/45 hover:[box-shadow:var(--shadow-md)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
    >
      <div className="flex shrink-0 items-center justify-center rounded-lg border border-border bg-secondary/50 p-1.5">
        <CompanyFavicon company={item.company} />
      </div>

      <div className="min-w-0 flex-1">
        <div className="flex items-start justify-between gap-3">
          <h3 className="line-clamp-2 min-w-0 flex-1 text-md font-semibold tracking-tight text-card-foreground transition-colors duration-300 ease-premium group-hover:text-primary">
            {item.title}
          </h3>
          <div className="flex max-w-[48%] shrink-0 flex-wrap justify-end gap-1.5">
            {item.category && (
              <Badge variant="secondary">
                {CATEGORY_LABEL[item.category] ?? item.category}
              </Badge>
            )}
            {item.is_remote && <Badge variant="outline">Remote</Badge>}
            {item.is_hidden && <Badge variant="heritage">Hidden gem</Badge>}
          </div>
        </div>

        <p className="mt-1 truncate text-sm text-muted-foreground">
          {metaParts.join(" · ")}
        </p>

        {item.deadline && (
          <span className="mt-3 inline-flex items-center gap-1.5 rounded-md border border-warning/25 bg-warning/15 px-2 py-1 text-xs font-medium text-warning-foreground dark:text-warning">
            <Clock className="h-3.5 w-3.5" aria-hidden="true" />
            <span>
              Deadline{" "}
              <span className="tnum">
                {new Date(item.deadline).toLocaleDateString()}
              </span>
              {item.deadline_confidence !== "explicit" ? " (estimated)" : ""}
            </span>
          </span>
        )}
      </div>
    </Link>
  );
}
