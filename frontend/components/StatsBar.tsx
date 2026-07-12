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
      className="mt-5 rounded-xl border border-border bg-secondary/25 px-4 py-4 shadow-soft sm:px-5"
    >
      <div className="flex flex-wrap items-center gap-x-8 gap-y-4 sm:justify-between">
        {figures.map(({ label, value }) => (
          <div key={label} className="flex items-baseline gap-2">
            <span className="tnum font-serif text-xl font-semibold tracking-tight text-foreground">
              {value.toLocaleString()}
            </span>
            <span className="text-xs font-medium uppercase tracking-[0.12em] text-muted-foreground">
              {label}
            </span>
          </div>
        ))}

        <p className="eyebrow flex items-center gap-2 sm:ml-auto">
          <span className="size-1.5 rounded-full bg-heritage" aria-hidden="true" />
          Updated daily
        </p>
      </div>
    </section>
  );
}
