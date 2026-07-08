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
    item.is_remote ? "Remote" : null,
  ].filter(Boolean);

  return (
    <Link
      href={`/opportunity/${item.slug}`}
      className="group flex h-full gap-3 rounded-lg border border-border bg-card p-4 shadow-xs transition-[transform,box-shadow,border-color] duration-200 ease-premium hover:-translate-y-0.5 hover:border-primary/40 hover:shadow-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
    >
      <CompanyFavicon company={item.company} />

      <div className="min-w-0 flex-1">
        <div className="flex items-start justify-between gap-3">
          <h3 className="min-w-0 flex-1 truncate font-semibold text-card-foreground group-hover:text-primary">
            {item.title}
          </h3>
          <div className="flex shrink-0 flex-wrap justify-end gap-1">
            {item.is_hidden && <Badge variant="outline">Hidden gem</Badge>}
            {item.category && (
              <Badge variant="secondary">
                {CATEGORY_LABEL[item.category] ?? item.category}
              </Badge>
            )}
          </div>
        </div>

        <p className="mt-0.5 truncate text-sm text-muted-foreground">
          {metaParts.join(" · ")}
        </p>

        {item.deadline && (
          <p className="mt-2 inline-flex items-center gap-1 text-xs font-medium text-warning">
            <Clock className="h-3.5 w-3.5" />
            Deadline {new Date(item.deadline).toLocaleDateString()}
            {item.deadline_confidence !== "explicit" ? " (estimated)" : ""}
          </p>
        )}
      </div>
    </Link>
  );
}
