import { Clock, Globe2, MapPin } from "lucide-react";
import Link from "next/link";
import { Badge } from "@/components/ui/badge";
import CompanyFavicon from "@/components/CompanyFavicon";
import type { OpportunityListItem } from "@/lib/types";

const CATEGORY_LABEL: Record<string, string> = {
  internship: "Internship",
  job: "Job",
};

const DAY_IN_MS = 24 * 60 * 60 * 1000;

function getAgeInDays(value: string | null): number | null {
  if (!value) return null;

  const timestamp = new Date(value).getTime();
  if (Number.isNaN(timestamp)) return null;

  return Math.floor((Date.now() - timestamp) / DAY_IN_MS);
}

function formatRelativeTime(value: string): string {
  const ageInDays = getAgeInDays(value);

  if (ageInDays === null || ageInDays <= 0) return "· today";
  if (ageInDays < 7) return `· ${ageInDays}d ago`;
  if (ageInDays < 30) return `· ${Math.floor(ageInDays / 7)}w ago`;
  if (ageInDays < 365) return `· ${Math.floor(ageInDays / 30)}mo ago`;

  return `· ${Math.floor(ageInDays / 365)}y ago`;
}

function formatDeadline(value: string): string {
  const deadline = new Date(value);

  if (Number.isNaN(deadline.getTime())) return value;

  return deadline.toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
    year: deadline.getFullYear() === new Date().getFullYear() ? undefined : "numeric",
  });
}

export default function OpportunityCard({ item }: { item: OpportunityListItem }) {
  const companyName = item.company?.name ?? "Unknown company";
  const location = item.location?.replace(/\s+/g, " ").trim() || null;
  const postedAgeInDays = getAgeInDays(item.posted_at);
  const isNew =
    postedAgeInDays !== null && postedAgeInDays >= 0 && postedAgeInDays < 7;
  const relativeTime = formatRelativeTime(item.posted_at ?? item.last_seen_at);
  const categoryLabel = item.category
    ? CATEGORY_LABEL[item.category] ?? item.category
    : null;

  return (
    <Link
      href={`/opportunity/${item.slug}`}
      className="group flex h-full flex-col gap-3 rounded-xl border border-border bg-card p-5 shadow-soft transition-[transform,box-shadow,border-color] duration-300 ease-premium hover:-translate-y-1 hover:border-primary/50 hover:[box-shadow:var(--shadow-md)] focus-visible:-translate-y-1 focus-visible:border-primary/50 focus-visible:[box-shadow:var(--shadow-md)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
    >
      <div className="flex items-start justify-between gap-3">
        <CompanyFavicon company={item.company} />
        {isNew ? (
          <span className="eyebrow rounded-full border border-heritage/20 bg-heritage/10 px-2 py-1 !text-heritage">
            New
          </span>
        ) : (
          <span className="tnum shrink-0 pt-1 text-xs text-muted-foreground">
            {relativeTime}
          </span>
        )}
      </div>

      <h3 className="line-clamp-2 min-w-0 text-md font-semibold leading-snug text-card-foreground transition-colors duration-300 ease-premium group-hover:text-primary group-focus-visible:text-primary">
        {item.title}
      </h3>

      <p className="truncate text-sm font-medium text-foreground/80">
        {companyName}
      </p>

      {(location || item.is_remote) && (
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted-foreground">
          {location && (
            <span className="inline-flex min-w-0 items-center gap-1.5">
              <MapPin className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
              <span className="min-w-0 break-words">{location}</span>
            </span>
          )}
          {location && item.is_remote && <span aria-hidden="true">·</span>}
          {item.is_remote && (
            <span className="inline-flex items-center gap-1.5">
              <Globe2 className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
              Remote
            </span>
          )}
        </div>
      )}

      <div className="mt-auto flex flex-wrap items-center justify-between gap-2 border-t border-border/60 pt-1">
        <div className="flex min-w-0 flex-wrap items-center gap-1.5">
          {categoryLabel && (
            <Badge
              variant={item.category === "internship" ? "heritage" : "default"}
              className={
                item.category === "job"
                  ? "border border-primary/20 bg-primary/10 text-primary"
                  : undefined
              }
            >
              {categoryLabel}
            </Badge>
          )}
          {item.is_hidden && <Badge variant="heritage">Hidden gem</Badge>}
        </div>

        <div className="ml-auto flex shrink-0 items-center gap-2">
          {item.deadline && (
            <span className="tnum inline-flex items-center gap-1.5 whitespace-nowrap rounded-md border border-warning/25 bg-warning/15 px-2 py-1 text-xs font-medium text-warning-foreground dark:text-warning">
              <Clock className="h-3.5 w-3.5" aria-hidden="true" />
              Closes {item.deadline_confidence !== "explicit" ? "~" : ""}
              {formatDeadline(item.deadline)}
            </span>
          )}
          <span className="whitespace-nowrap text-xs font-medium text-primary opacity-0 transition-opacity duration-300 ease-premium group-hover:opacity-100 group-focus-visible:opacity-100">
            View →
          </span>
        </div>
      </div>
    </Link>
  );
}
