import { TrendingUp } from "lucide-react";
import HoverPrefetchLink from "@/components/HoverPrefetchLink";
import { programmePath } from "@/lib/programmes";
import { programmeWindow } from "@/lib/programmeWindow";
import type { ProgrammeListItem } from "@/lib/types";

const MONTHS = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"];

const CONFIRMED_DATE = new Intl.DateTimeFormat("en-GB", {
  day: "numeric",
  month: "short",
  year: "numeric",
  timeZone: "UTC",
});

function confirmedDateRange(programme: ProgrammeListItem): string {
  const edition = programme.current_edition;
  if (!edition?.opens_at) return "";
  const opens = CONFIRMED_DATE.format(new Date(edition.opens_at));
  return edition.closes_at
    ? `${opens} to ${CONFIRMED_DATE.format(new Date(edition.closes_at))}`
    : `${opens}; closing date not announced`;
}

export default function ProgrammeAlmanac({ programmes }: { programmes: ProgrammeListItem[] }) {
  const now = new Date();
  const currentMonth = now.getUTCMonth() + 1;
  const rows = programmes.flatMap((programme) => {
    const window = programmeWindow(programme, now);
    return window ? [{ programme, window }] : [];
  }).sort((a, b) => (a.window.segments[0][0] - currentMonth + 12) % 12 - (b.window.segments[0][0] - currentMonth + 12) % 12);
  const uncharted = programmes.length - rows.length;

  return (
    <section className="mb-8 min-w-0 rounded-lg border border-border bg-card p-5 sm:p-6" aria-labelledby="application-windows-heading">
      <h2 id="application-windows-heading" className="flex items-center gap-2 font-serif text-2xl font-bold"><TrendingUp className="size-5 shrink-0 text-primary" aria-hidden="true" />{now.getUTCFullYear()} application windows</h2>
      <p id="almanac-legend" className="mt-3 text-xs leading-5 text-muted-foreground">Dashed: the window it usually opens in, from past editions. Solid: dates confirmed for this edition.</p>
      <div className="mt-5 max-w-full overflow-x-auto rounded-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring" role="region" tabIndex={0} aria-label="Programme application calendar, scroll horizontally for all months" aria-describedby="almanac-legend">
        <div className="min-w-[720px]" role="table" aria-colcount={13} aria-label="Application windows by programme and month">
          <div className="grid grid-cols-[180px_minmax(0,1fr)] border-b border-border pb-3" role="row">
            <span className="sr-only" role="columnheader">Programme</span>
            <div className="col-start-2 grid grid-cols-12" role="presentation">{MONTHS.map((month, index) => <span key={month} role="columnheader" aria-current={index + 1 === currentMonth ? "date" : undefined} className={`py-2 text-center text-xs font-medium ${index + 1 === currentMonth ? "bg-accent text-accent-foreground" : "text-muted-foreground"}`}>{month}</span>)}</div>
          </div>
          {rows.map(({ programme, window }) => <div key={programme.slug} role="row" className="grid grid-cols-[180px_minmax(0,1fr)] border-b border-border last:border-b-0">
            <div role="rowheader" className="min-w-0 pr-3">
              <HoverPrefetchLink href={programmePath(programme.slug)} className="flex min-h-14 items-center gap-2 text-xs font-medium hover:text-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
                <span className="flex size-7 shrink-0 items-center justify-center rounded border border-border bg-secondary text-xs" aria-hidden="true">{programme.name.trim().split(/\s+/).slice(0, 2).map((word) => word[0]).join("").toUpperCase()}</span>
                <span className="truncate" title={programme.name}>{programme.name}</span>
              </HoverPrefetchLink>
            </div>
            <div role="cell" aria-colspan={12} aria-colindex={2} className="relative grid grid-cols-12 items-center py-3">
              <div className="pointer-events-none absolute inset-0 grid grid-cols-12" aria-hidden="true">{MONTHS.map((month, index) => <div key={month} className={`border-l border-border ${index + 1 === currentMonth ? "bg-accent/50" : ""}`} />)}</div>
              <span className="sr-only">{window.label}{window.kind === "confirmed" ? `: ${confirmedDateRange(programme)}` : ""}</span>
              {window.segments.map(([start, end], index) => <div key={index} title={`${programme.name}: ${window.label}${window.kind === "confirmed" ? ` (${confirmedDateRange(programme)})` : ""}`} style={{ gridColumn: `${start} / ${end + 1}`, gridRow: 1 }} className={`relative mx-0.5 flex min-h-7 items-center gap-1 overflow-hidden rounded border px-1.5 text-xs ${window.kind === "typical" ? "border-dashed border-border bg-muted text-muted-foreground" : window.status === "open" ? "border-success/40 bg-success/10 text-success" : window.status === "announced" ? "border-primary/25 bg-accent text-accent-foreground" : "border-border bg-secondary text-muted-foreground"}`} aria-hidden="true">
                {window.status === "open" && <span className="size-1.5 shrink-0 rounded-full bg-success" />}
                <span className="truncate">{window.kind === "typical" ? "Usually" : window.label}</span>
              </div>)}
            </div>
          </div>)}
        </div>
      </div>
      {uncharted > 0 && <p className="mt-4 text-xs leading-5 text-muted-foreground">{uncharted} programmes on this page open on rolling or programme-specific dates and aren&apos;t charted.</p>}
    </section>
  );
}
