"use client";

import { ROLE_OPTIONS } from "@/lib/roleSignalQuery";
import { cn } from "@/lib/utils";

export default function DomainPicker({
  value, onChange, disabled = false, "aria-labelledby": labelledBy,
}: {
  value: string[];
  onChange: (value: string[]) => void;
  disabled?: boolean;
  "aria-labelledby": string;
}) {
  const selected = value.filter((role) => ROLE_OPTIONS.some((option) => option.value === role));
  return (
    <div role="group" aria-labelledby={labelledBy} className="flex min-w-0 flex-wrap gap-2">
      {[{ value: "", label: "All domains" }, ...ROLE_OPTIONS].map((option) => {
        const pressed = option.value === "" ? selected.length === 0 : selected.includes(option.value);
        return (
          <button key={option.value} type="button" aria-pressed={pressed} disabled={disabled}
            onClick={() => onChange(option.value === "" ? [] : pressed
              ? selected.filter((role) => role !== option.value) : [...selected, option.value])}
            className={cn(
              "min-h-10 rounded-full border px-3 py-2 text-sm transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50",
              pressed ? "border-primary bg-primary text-primary-foreground" : "border-border bg-background text-foreground hover:bg-muted",
            )}>
            {option.label}
          </button>
        );
      })}
    </div>
  );
}
