import Link from "next/link";
import { Badge } from "@/components/ui/badge";
import {
  formatProgrammeCategory,
  getProgrammeStatusDisplay,
  programmePath,
} from "@/lib/programmes";
import type { ProgrammeListItem } from "@/lib/types";

function truncateText(value: string | null | undefined, maxLength = 170): string {
  const trimmed = value?.trim();
  if (!trimmed) {
    return "Programme details vary by annual edition; verify dates and eligibility on the official page.";
  }
  if (trimmed.length <= maxLength) return trimmed;
  return `${trimmed.slice(0, maxLength - 1).trimEnd()}...`;
}

export default function ProgrammeCard({ programme }: { programme: ProgrammeListItem }) {
  const status = getProgrammeStatusDisplay(
    programme.current_edition,
    programme.typical_window,
  );
  const statusClass =
    status.tone === "primary"
      ? "border-primary/20 bg-primary text-primary-foreground"
      : "border-border bg-secondary/50 text-muted-foreground";

  return (
    <Link
      href={programmePath(programme.slug)}
      className="group flex min-h-72 flex-col rounded-xl border border-border bg-card p-5 shadow-soft transition-[transform,box-shadow,border-color] duration-300 ease-premium hover:-translate-y-1 hover:border-primary/45 hover:[box-shadow:var(--shadow-md)] focus-visible:-translate-y-1 focus-visible:border-primary/45 focus-visible:[box-shadow:var(--shadow-md)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
    >
      <div className="flex flex-wrap items-center gap-2">
        <Badge variant="secondary" className="eyebrow rounded-full px-2.5 py-1">
          {formatProgrammeCategory(programme.category)}
        </Badge>
        {programme.country && (
          <Badge variant="outline" className="eyebrow rounded-full px-2.5 py-1">
            {programme.country}
          </Badge>
        )}
      </div>

      <div className="mt-5">
        <h2 className="break-words font-serif text-2xl font-semibold leading-tight text-card-foreground transition-colors duration-300 ease-premium group-hover:text-primary group-focus-visible:text-primary">
          {programme.name}
        </h2>
        <p className="mt-2 text-sm font-medium text-muted-foreground">
          {programme.organiser}
        </p>
      </div>

      <div
        className={`mt-5 inline-flex w-fit items-center rounded-md border px-3 py-1.5 text-sm font-medium ${statusClass}`}
      >
        {status.text}
      </div>

      <p className="mt-5 line-clamp-4 text-sm leading-6 text-muted-foreground">
        {truncateText(programme.description)}
      </p>
    </Link>
  );
}
