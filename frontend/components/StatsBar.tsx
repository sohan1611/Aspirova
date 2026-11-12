import type { StatsResponse } from "@/lib/types";

interface StatsBarProps {
  stats?: Partial<StatsResponse> | null;
}

export default function StatsBar({ stats }: StatsBarProps) {
  const figures = [
    { label: "open opportunities", value: stats?.opportunities, description: "Open, student-facing listings" },
    { label: "companies", value: stats?.companies, description: "Distinct companies with open listings" },
    { label: "sources", value: stats?.sources, description: "Distinct sources with open listings" },
  ];
  const updatedAt = stats?.updated_at ? new Date(stats.updated_at) : null;
  const validUpdatedAt = updatedAt && Number.isFinite(updatedAt.getTime()) ? updatedAt : null;

  return (
    <section
      aria-label="Aspirova open listing statistics"
      className="mt-4 rounded-lg border border-border bg-card px-3 py-3 shadow-soft sm:mt-5 sm:px-5 sm:py-4"
    >
      <div className="grid grid-cols-3 items-start gap-x-3 gap-y-2 sm:flex sm:flex-wrap sm:items-center sm:gap-x-10 sm:gap-y-4">
        {figures.map(({ label, value, description }) => (
          <div key={label} title={description} className="flex min-w-0 flex-col gap-1 sm:flex-row sm:items-baseline sm:gap-2">
            {/* Natural width: a fixed-width box left short counts like "18" floating
                far from their label, nearer the next figure than their own. */}
            <span className="tnum shrink-0 font-serif text-lg font-bold tracking-tight text-foreground sm:text-xl">
              {typeof value === "number" && Number.isFinite(value) && value > 0 ? (
                value.toLocaleString("en-IN")
              ) : (
                <>
                  <span aria-hidden="true">—</span>
                  <span className="sr-only">Count unavailable</span>
                </>
              )}
            </span>
            <span className="text-[0.625rem] font-medium uppercase tracking-[0.06em] text-muted-foreground sm:text-xs sm:tracking-[0.12em]">
              {label}
            </span>
          </div>
        ))}

        {validUpdatedAt && (
          <p className="col-span-3 text-xs text-muted-foreground sm:ml-auto">
            Listings last updated{" "}
            <time dateTime={validUpdatedAt.toISOString()}>
              {validUpdatedAt.toLocaleDateString("en-GB", {
                day: "numeric",
                month: "short",
                year: "numeric",
                timeZone: "UTC",
              })}
            </time>
          </p>
        )}
      </div>
    </section>
  );
}
