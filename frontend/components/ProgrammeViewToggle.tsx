import { CalendarDays, LayoutGrid } from "lucide-react";
import HoverPrefetchLink from "@/components/HoverPrefetchLink";
import type { ProgrammeSearchParams } from "@/lib/programmesQuery";

export type ProgrammeViewQuery = ProgrammeSearchParams & { view?: string | string[] };

function viewHref(query: ProgrammeViewQuery, browse: boolean): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (key === "view") continue;
    for (const item of Array.isArray(value) ? value : value ? [value] : []) search.append(key, item);
  }
  if (browse) search.set("view", "browse");
  return `/programmes${search.size ? `?${search}` : ""}`;
}

export default function ProgrammeViewToggle({ query }: { query: ProgrammeViewQuery }) {
  const browse = (Array.isArray(query.view) ? query.view[0] : query.view) === "browse";
  return (
    <nav aria-label="Programme view" className="inline-flex shrink-0 rounded-lg border border-border bg-secondary p-1">
      {[{ label: "Almanac", browse: false, Icon: CalendarDays }, { label: "Browse", browse: true, Icon: LayoutGrid }].map(({ label, browse: next, Icon }) => (
        <HoverPrefetchLink key={label} href={viewHref(query, next)} aria-current={browse === next ? "page" : undefined} className={`inline-flex min-h-11 items-center gap-2 rounded-md px-3 text-sm font-medium focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring ${browse === next ? "bg-card text-primary shadow-sm" : "text-muted-foreground hover:text-foreground"}`}>
          <Icon className="size-4" aria-hidden="true" />{label}
        </HoverPrefetchLink>
      ))}
    </nav>
  );
}
