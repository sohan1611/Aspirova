import { ArrowRight } from "lucide-react";
import HoverPrefetchLink from "@/components/HoverPrefetchLink";
import { formatCompensation } from "@/lib/compensation";
import { formatDate } from "@/lib/date";
import { summarizeLocation } from "@/lib/location";
import type { OpportunityListItem } from "@/lib/types";

export default function SimilarOpportunitiesList({ items }: { items: OpportunityListItem[] }) {
  if (items.length === 0) return null;
  return (
    <section className="rounded-lg border border-border bg-card p-5 sm:p-6" aria-labelledby="similar-opportunities-heading">
      <h2 id="similar-opportunities-heading" className="border-b border-border pb-4 font-serif text-2xl font-bold">Similar opportunities</h2>
      <ul className="divide-y divide-border">
        {items.slice(0, 5).map((item) => {
          const location = summarizeLocation(item.location).short;
          const detail = item.category === "job" || item.category === "internship"
            ? formatCompensation(item.meta)
            : item.deadline ? `Apply by ${formatDate(item.deadline)}${item.deadline_confidence !== "explicit" ? " (estimated)" : ""}` : null;
          return <li key={item.slug}>
            <HoverPrefetchLink href={`/opportunity/${item.slug}`} className="group relative block min-h-11 py-5 pr-6 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
              <p className="line-clamp-2 text-sm font-semibold transition-colors group-hover:text-primary">{item.title}</p>
              <p className="mt-1 break-words text-sm text-muted-foreground">{[item.company?.name, location].filter(Boolean).join(" · ")}</p>
              {detail && <p className="mt-2 text-xs leading-5 text-muted-foreground">{detail}</p>}
              <ArrowRight className="absolute right-0 top-5 size-4 text-muted-foreground group-hover:text-primary" aria-hidden="true" />
            </HoverPrefetchLink>
          </li>;
        })}
      </ul>
    </section>
  );
}
