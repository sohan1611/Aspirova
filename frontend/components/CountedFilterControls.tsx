"use client";

import { X } from "lucide-react";
import { useId, type ReactNode } from "react";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

export interface CountedFilterOption {
  value: string;
  label: string;
  count: number;
}

export interface ActiveFilterChip {
  id: string;
  label: ReactNode;
  humanLabel: string;
  onRemove: () => void;
}

export function FilterPanelSection({
  title,
  children,
}: {
  title: string;
  children: ReactNode;
}) {
  const headingId = useId();

  return (
    <section className="space-y-2.5" aria-labelledby={headingId}>
      <p id={headingId} className="eyebrow">
        {title}
      </p>
      {children}
    </section>
  );
}

export function CountedMultiSelectGroup({
  label,
  options,
  values,
  onToggle,
  disabled = false,
  emptyLabel = "No available options",
}: {
  label: string;
  options: CountedFilterOption[];
  values: string[];
  onToggle: (value: string) => void;
  disabled?: boolean;
  emptyLabel?: string;
}) {
  if (options.length === 0) {
    return <p className="text-sm text-muted-foreground">{emptyLabel}</p>;
  }

  return (
    <div className="grid gap-2" role="group" aria-label={label}>
      {options.map((option) => {
        const isActive = values.includes(option.value);
        const isDisabled = disabled || option.count <= 0;

        return (
          <label
            key={option.value}
            className={cn(
              "flex min-h-11 cursor-pointer items-center gap-3 rounded-md border border-border bg-background px-3 py-2 text-sm transition-[background-color,border-color,box-shadow,color] duration-200 ease-[var(--ease-premium)]",
              "hover:border-heritage/30 hover:bg-secondary/40",
              isActive && "border-heritage/30 bg-heritage/10 text-heritage",
              isDisabled && "cursor-not-allowed opacity-55 hover:border-border hover:bg-background",
            )}
          >
            <input
              type="checkbox"
              checked={isActive}
              disabled={isDisabled}
              onChange={() => onToggle(option.value)}
              className="h-4 w-4 shrink-0 rounded border-border bg-background accent-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background disabled:cursor-not-allowed"
            />
            <span className="min-w-0 flex-1 truncate">{option.label}</span>
            <span className="tnum shrink-0 rounded-sm bg-muted px-1.5 py-0.5 text-xs text-muted-foreground">
              {option.count}
            </span>
          </label>
        );
      })}
    </div>
  );
}

export function CountedSingleSelectGroup({
  label,
  options,
  value,
  onSelect,
  disabled = false,
  emptyLabel = "No available options",
}: {
  label: string;
  options: CountedFilterOption[];
  value: string | null;
  onSelect: (value: string | null) => void;
  disabled?: boolean;
  emptyLabel?: string;
}) {
  if (options.length === 0) {
    return <p className="text-sm text-muted-foreground">{emptyLabel}</p>;
  }

  return (
    <div className="grid gap-2" role="group" aria-label={label}>
      {options.map((option) => {
        const isActive = option.value === value;
        const isDisabled = disabled || option.count <= 0;

        return (
          <button
            key={option.value}
            type="button"
            aria-pressed={isActive}
            disabled={isDisabled}
            onClick={() => onSelect(isActive ? null : option.value)}
            className={cn(
              "flex min-h-11 items-center gap-3 rounded-md border border-border bg-background px-3 py-2 text-left text-sm transition-[background-color,border-color,box-shadow,color] duration-200 ease-[var(--ease-premium)] disabled:cursor-wait",
              "hover:border-heritage/30 hover:bg-secondary/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background",
              isActive && "border-heritage/30 bg-heritage/10 text-heritage",
              isDisabled && "opacity-55 hover:border-border hover:bg-background",
            )}
          >
            <span className="min-w-0 flex-1 truncate">{option.label}</span>
            <span className="tnum shrink-0 rounded-sm bg-muted px-1.5 py-0.5 text-xs text-muted-foreground">
              {option.count}
            </span>
          </button>
        );
      })}
    </div>
  );
}

export function ActiveFilterChips({
  filters,
  disabled = false,
  onClearAll,
  showClearAll = true,
}: {
  filters: ActiveFilterChip[];
  disabled?: boolean;
  onClearAll: () => void;
  showClearAll?: boolean;
}) {
  if (filters.length === 0) return null;

  return (
    <div className="mb-5 flex min-w-0 flex-wrap items-center gap-2">
      {filters.map(({ id, label, humanLabel, onRemove }) => (
        <Badge
          key={id}
          variant="secondary"
          className="max-w-full gap-1 py-0.5 pr-0.5 pl-2 text-sm font-medium tracking-normal normal-case"
        >
          <span className="min-w-0 truncate">{label}</span>
          <button
            type="button"
            aria-label={`Remove ${humanLabel} filter`}
            disabled={disabled}
            onClick={onRemove}
            className="inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-sm text-muted-foreground transition-[color,background-color,box-shadow] duration-200 ease-[var(--ease-premium)] hover:bg-background/60 hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring disabled:cursor-wait"
          >
            <X className="h-3.5 w-3.5" aria-hidden="true" />
          </button>
        </Badge>
      ))}
      {showClearAll && (
        <button
          type="button"
          disabled={disabled}
          onClick={onClearAll}
          className="min-h-7 whitespace-nowrap rounded-sm px-1.5 py-1 text-sm font-medium text-muted-foreground transition-colors duration-200 ease-[var(--ease-premium)] hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background disabled:cursor-wait"
        >
          Clear all
        </button>
      )}
    </div>
  );
}
