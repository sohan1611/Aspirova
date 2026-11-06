import { CalendarDays, ExternalLink, Timer } from "lucide-react";
import HoverPrefetchLink from "@/components/HoverPrefetchLink";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { formatProgrammeCategory, getProgrammeStatusDisplay, programmePath } from "@/lib/programmes";
import type { ProgrammeListItem } from "@/lib/types";

export default function ProgrammeCard({ programme }: { programme: ProgrammeListItem }) {
  const status = getProgrammeStatusDisplay(programme.current_edition, programme.typical_window);
  const open = programme.current_edition?.status === "open";
  const closesAt = programme.current_edition?.closes_at;
  const remaining = closesAt ? new Date(closesAt).getTime() - new Date().getTime() : 0;
  const days = Math.ceil(remaining / 86_400_000);
  const path = programmePath(programme.slug);
  const initials = programme.name.trim().split(/\s+/).slice(0, 2).map((word) => word[0]).join("");

  return (
    <article className={`flex min-w-0 flex-col rounded-lg [overflow-wrap:anywhere] border border-border bg-card p-5 ${open ? "border-t-[3px] border-t-success" : ""}`}>
      {open && <p className="mb-3 flex items-center gap-1.5 text-xs font-semibold text-success"><span aria-hidden="true">●</span>Open now</p>}
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 className="break-words font-serif text-xl font-bold leading-tight">
            <HoverPrefetchLink href={path} className="inline-flex min-h-11 items-center hover:text-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">{programme.name}</HoverPrefetchLink>
          </h2>
          <p className="mt-1 text-sm text-muted-foreground">{programme.organiser}</p>
        </div>
        <span className="flex size-10 shrink-0 items-center justify-center rounded border border-border bg-secondary text-sm font-semibold" aria-hidden="true">{initials}</span>
      </div>
      <div className="mt-5 flex flex-wrap gap-2">
        <Badge variant="secondary" className="max-w-full rounded-md bg-accent text-accent-foreground whitespace-normal">{formatProgrammeCategory(programme.category)}</Badge>
        {programme.country && <Badge variant="outline" className="max-w-full rounded-md whitespace-normal">{programme.country}</Badge>}
      </div>
      <div className="mt-5 border-t border-border pt-4">
        <p className="flex items-center gap-1.5 text-xs font-medium uppercase tracking-wide text-muted-foreground"><CalendarDays className="size-3.5" aria-hidden="true" />Application window</p>
        <p className="mt-2 text-sm leading-6">{status.text}</p>
        {remaining > 0 && <p className="mt-2 flex items-center gap-1.5 text-sm text-muted-foreground"><Timer className="size-4" aria-hidden="true" />Closes in {days} {days === 1 ? "day" : "days"}</p>}
      </div>
      <p className="mt-3 line-clamp-2 text-sm leading-6 text-muted-foreground">{programme.description?.trim() || "Programme details vary by annual edition; verify dates and eligibility on the official page."}</p>
      <div className="mt-auto pt-5">
        {open ? <>
          <Button asChild className="min-h-11 w-full"><a href={programme.url} target="_blank" rel="noopener noreferrer">Apply now<ExternalLink className="size-4" aria-hidden="true" /></a></Button>
          <HoverPrefetchLink href={path} className="mt-1 flex min-h-11 items-center justify-center text-sm font-medium text-primary underline-offset-4 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">Details<span className="sr-only"> for {programme.name}</span></HoverPrefetchLink>
        </> : <Button asChild variant="outline" className="min-h-11 w-full"><HoverPrefetchLink href={path}>View programme<span className="sr-only">: {programme.name}</span></HoverPrefetchLink></Button>}
      </div>
    </article>
  );
}
