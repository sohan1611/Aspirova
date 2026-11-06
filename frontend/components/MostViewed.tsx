import HoverPrefetchLink from "@/components/HoverPrefetchLink";
import CompanyFavicon from "@/components/CompanyFavicon";
import { getCountry } from "@/lib/countries";
import { isSinglePlace } from "@/lib/location";
import type { OpportunityListItem } from "@/lib/types";

interface MostViewedProps {
  items: OpportunityListItem[];
}

export default function MostViewed({ items }: MostViewedProps) {
  if (items.length < 4) return null;

  return (
    <section className="mt-6" aria-labelledby="most-viewed-heading">
      <p id="most-viewed-heading" className="eyebrow">
        Most viewed
      </p>

      <div className="mt-3 flex snap-x snap-mandatory gap-3 overflow-x-auto pb-2">
        {items.slice(0, 8).map((item) => {
          const companyName = item.company?.name ?? "Independent listing";
          const countryFlag = isSinglePlace(item.location) ? getCountry(item.country)?.flag : null;

          return (
            <HoverPrefetchLink
              key={item.slug}
              href={`/opportunity/${item.slug}`}
              className="group flex w-56 shrink-0 snap-start items-start gap-3 rounded-lg border border-border bg-card p-3 shadow-soft transition-colors duration-300 ease-premium hover:border-primary/50 focus-visible:border-primary/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
            >
              <CompanyFavicon company={item.company} size={36} />
              <div className="min-w-0">
                <h3 className="line-clamp-2 font-serif text-sm font-bold leading-snug text-card-foreground transition-colors duration-300 ease-premium group-hover:text-primary group-focus-visible:text-primary">
                  {item.title}
                </h3>
                <p className="mt-1 truncate text-xs font-medium text-muted-foreground">
                  {companyName}
                  {countryFlag && <span aria-hidden="true"> · {countryFlag}</span>}
                </p>
              </div>
            </HoverPrefetchLink>
          );
        })}
      </div>
    </section>
  );
}
