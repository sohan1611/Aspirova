"use client";

import { parseEligibilityParams, STAGE_OPTIONS } from "@/lib/eligibility";

export default function EligibilityFilters({ searchParams, onChange, disabled = false, idPrefix }: {
  searchParams: { toString(): string };
  onChange: (params: URLSearchParams) => void;
  disabled?: boolean;
  idPrefix: string;
}) {
  const params = new URLSearchParams(searchParams.toString());
  const selected = parseEligibilityParams(params);
  const year = new Date().getUTCFullYear();
  const years = Array.from({ length: 7 }, (_, index) => year - 1 + index).filter((value) => value >= 2015 && value <= 2035);
  if (selected.grad_year && !years.includes(selected.grad_year)) years.unshift(selected.grad_year);
  function update(key: string, value: string | null) {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value); else next.delete(key);
    if (!next.has("grad_year") && !next.has("stage")) next.delete("eligibility_stated");
    onChange(next);
  }
  function toggleStage(value: string) {
    const next = new URLSearchParams(params);
    const stages = selected.stage ?? [];
    next.delete("stage");
    for (const stage of stages) if (stage !== value) next.append("stage", stage);
    if (!stages.some((stage) => stage === value)) next.append("stage", value);
    if (!next.has("grad_year") && !next.has("stage")) next.delete("eligibility_stated");
    onChange(next);
  }
  return (
    <fieldset className="min-w-0 space-y-3" disabled={disabled}>
      <legend className="eyebrow mb-2">Eligibility</legend>
      <label className="grid gap-2 text-sm" htmlFor={idPrefix + "-grad-year"}>
        Graduation year
        <select id={idPrefix + "-grad-year"} value={selected.grad_year ?? ""} onChange={(event) => update("grad_year", event.target.value || null)} className="min-h-11 w-full rounded-md border border-border bg-background px-3">
          <option value="">Any</option>
          {years.map((value) => <option key={value} value={value}>{value}</option>)}
        </select>
      </label>
      <fieldset>
        <legend className="mb-1 text-sm">Study level</legend>
        <div className="flex flex-wrap gap-x-3">
          {STAGE_OPTIONS.map(({ value, label }) => (
            <label key={value} className="flex min-h-11 items-center gap-2 text-sm">
              <input type="checkbox" checked={selected.stage?.includes(value) ?? false} onChange={() => toggleStage(value)} />{label}
            </label>
          ))}
        </div>
      </fieldset>
      {(selected.grad_year || selected.stage?.length) && (
        <div className="space-y-2">
          <p className="text-xs text-muted-foreground">Listings that don&apos;t state eligibility stay in and are marked.</p>
          <label className="flex min-h-11 items-center gap-2 text-sm">
            <input type="checkbox" checked={selected.eligibility_stated ?? false} onChange={(event) => update("eligibility_stated", event.target.checked ? "1" : null)} />
            Only listings that state it
          </label>
        </div>
      )}
    </fieldset>
  );
}
