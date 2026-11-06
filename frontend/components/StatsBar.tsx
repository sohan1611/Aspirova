import type { StatsResponse } from "@/lib/types";

interface StatsBarProps {
  stats: StatsResponse;
}

export default function StatsBar({ stats }: StatsBarProps) {
  const figures = [
    { label: "live opportunities", value: stats.opportunities },
    { label: "companies", value: stats.companies },
    { label: "sources", value: stats.sources },
  ].filter(({ value }) => Number.isFinite(value) && value > 0);

  if (figures.length === 0) {
    return null;
  }

  return (
    <section
      aria-label="Aspirova live statistics"
      className="mt-4 rounded-lg border border-border bg-card px-3 py-3 shadow-soft sm:mt-5 sm:px-5 sm:py-4"
    >
      <div className="grid grid-cols-3 items-start gap-x-3 gap-y-2 sm:flex sm:flex-wrap sm:items-center sm:justify-between sm:gap-x-8 sm:gap-y-4">
        {figures.map(({ label, value }) => (
          <div key={label} className="flex min-w-0 flex-col gap-1 sm:flex-row sm:items-baseline sm:gap-2">
            <span className="tnum font-serif text-lg font-bold tracking-tight text-foreground sm:text-xl">
              {value.toLocaleString()}
            </span>
            <span className="text-[0.625rem] font-medium uppercase tracking-[0.06em] text-muted-foreground sm:text-xs sm:tracking-[0.12em]">
              {label}
            </span>
          </div>
        ))}

        <p className="eyebrow col-span-3 flex items-center gap-2 sm:ml-auto">
          <span className="size-1.5 rounded-full bg-primary" aria-hidden="true" />
          Updated daily
        </p>
      </div>
    </section>
  );
}
