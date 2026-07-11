import { Clock, Globe2, MapPin } from "lucide-react";
import Link from "next/link";
import { Badge } from "@/components/ui/badge";
import CompanyFavicon from "@/components/CompanyFavicon";
import { formatDate } from "@/lib/date";
import type { OpportunityListItem } from "@/lib/types";

const CATEGORY_LABEL: Record<string, string> = {
  internship: "Internship",
  job: "Job",
  hackathon: "Hackathon",
  competition: "Competition",
};

const DAY_IN_MS = 24 * 60 * 60 * 1000;
const COMPETITION_CATEGORIES = new Set(["hackathon", "competition"]);
const COMPETITION_MODES = new Set(["online", "offline", "hybrid"]);

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

function getPrizeText(
  meta: Record<string, unknown> | null | undefined,
): string | null {
  if (!meta) return null;

  if (typeof meta.prize === "string" && meta.prize.trim()) {
    return meta.prize.trim();
  }

  if (!Array.isArray(meta.prizes)) return null;

  const cashValues = meta.prizes.flatMap((prize) => {
    if (!prize || typeof prize !== "object" || Array.isArray(prize)) return [];

    const cash = (prize as Record<string, unknown>).cash;
    return typeof cash === "number" && Number.isFinite(cash) && cash > 0
      ? [cash]
      : [];
  });
  if (cashValues.length === 0) return null;

  return `₹${Math.max(...cashValues).toLocaleString("en-IN")}`;
}

function getCompetitionMode(
  meta: Record<string, unknown> | null | undefined,
): string | null {
  if (typeof meta?.mode !== "string") return null;

  const mode = meta.mode.trim().toLowerCase();
  if (!COMPETITION_MODES.has(mode)) return null;

  return `${mode.charAt(0).toUpperCase()}${mode.slice(1)}`;
}

function isDeadlineUrgent(value: string): boolean {
  const timestamp = new Date(value).getTime();
  if (Number.isNaN(timestamp)) return false;

  const timeUntilDeadline = timestamp - Date.now();
  return timeUntilDeadline >= 0 && timeUntilDeadline <= 7 * DAY_IN_MS;
}

function isDeadlinePast(value: string): boolean {
  const timestamp = new Date(value).getTime();
  return !Number.isNaN(timestamp) && timestamp < Date.now();
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
  const isCompetition =
    item.category !== null && COMPETITION_CATEGORIES.has(item.category);
  const prizeText = isCompetition ? getPrizeText(item.meta) : null;
  const competitionMode = isCompetition
    ? getCompetitionMode(item.meta)
    : null;
  const urgentDeadline =
    isCompetition && item.deadline ? isDeadlineUrgent(item.deadline) : false;
  const registrationsClosed =
    isCompetition && item.deadline ? isDeadlinePast(item.deadline) : false;

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

      {prizeText && (
        <p className="flex min-w-0 items-start gap-2 text-xs text-foreground/80">
          <span className="eyebrow shrink-0 pt-0.5 !text-heritage">Prize</span>
          <span className="line-clamp-2 min-w-0 break-words font-medium">
            {prizeText}
          </span>
        </p>
      )}

      <div className="mt-auto flex flex-wrap items-center justify-between gap-2 border-t border-border/60 pt-1">
        <div className="flex min-w-0 flex-wrap items-center gap-1.5">
          {categoryLabel && (
            <Badge
              variant={
                item.category === "internship"
                  ? "heritage"
                  : isCompetition
                    ? "secondary"
                    : "default"
              }
              className={
                item.category === "job"
                  ? "border border-primary/20 bg-primary/10 text-primary"
                  : undefined
              }
            >
              {categoryLabel}
            </Badge>
          )}
          {competitionMode && (
            <Badge variant="outline">{competitionMode}</Badge>
          )}
          {item.is_hidden && <Badge variant="heritage">Hidden gem</Badge>}
        </div>

        <div className="ml-auto flex shrink-0 items-center gap-2">
          {item.deadline && (
            isCompetition ? (
              registrationsClosed ? (
                <Badge
                  variant="secondary"
                  className="tnum border border-border px-2 py-1 normal-case text-muted-foreground"
                >
                  <Clock className="h-3.5 w-3.5" aria-hidden="true" />
                  Registrations closed
                </Badge>
              ) : (
                <span
                  className={`tnum inline-flex items-center gap-1.5 whitespace-nowrap rounded-md border px-2 py-1 text-xs font-medium ${
                    urgentDeadline
                      ? "border-heritage/30 bg-heritage/10 font-semibold text-heritage"
                      : "border-border bg-secondary text-secondary-foreground"
                  }`}
                  aria-label={
                    urgentDeadline
                      ? `Urgent: registers by ${formatDate(item.deadline, "long")}`
                      : undefined
                  }
                >
                  <Clock className="h-3.5 w-3.5" aria-hidden="true" />
                  Registers by {formatDate(item.deadline, "long")}
                </span>
              )
            ) : (
              <span className="tnum inline-flex items-center gap-1.5 whitespace-nowrap rounded-md border border-warning/25 bg-warning/15 px-2 py-1 text-xs font-medium text-warning-foreground dark:text-warning">
                <Clock className="h-3.5 w-3.5" aria-hidden="true" />
                Closes {item.deadline_confidence !== "explicit" ? "~" : ""}
                {formatDate(item.deadline, "long")}
              </span>
            )
          )}
          <span className="whitespace-nowrap text-xs font-medium text-primary opacity-0 transition-opacity duration-300 ease-premium group-hover:opacity-100 group-focus-visible:opacity-100">
            View →
          </span>
        </div>
      </div>
    </Link>
  );
}
