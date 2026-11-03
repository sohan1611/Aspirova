"use client";

import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";

export default function RoleSignalFilters({
  searchParams, onChange, internships, disabled, idPrefix,
}: {
  searchParams: { get(key: string): string | null };
  onChange: (key: string, value: string | null) => void;
  internships: boolean;
  disabled: boolean;
  idPrefix: string;
}) {
  const toggles = [
    { key: "paid", label: "Paid only" },
    { key: "part_time", label: "Part-time" },
    ...(internships ? [{ key: "job_offer", label: "Job offer possible" }] : []),
  ];
  const selects = [
    ...(internships ? [
      { key: "min_stipend", label: "Minimum stipend", options: [
        ["all", "Any"], ["5000", "₹5,000 per month"], ["10000", "₹10,000 per month"],
        ["20000", "₹20,000 per month"],
      ] },
      { key: "max_duration", label: "Duration", options: [
        ["all", "Any"], ["3", "Up to 3 months"], ["6", "Up to 6 months"],
      ] },
    ] : []),
    { key: "posted_within", label: "Posted within", options: [
      ["all", "Any"], ["1", "24 hours"], ["3", "3 days"], ["7", "7 days"], ["30", "30 days"],
    ] },
  ];

  return (
    <div className="space-y-5">
      {toggles.map(({ key, label }) => (
        <div key={key} className="space-y-1.5">
          <Label htmlFor={`${idPrefix}-${key}`} className="flex cursor-pointer items-center gap-2 text-sm">
            <input
              id={`${idPrefix}-${key}`}
              type="checkbox"
              checked={searchParams.get(key) === "true"}
              disabled={disabled}
              onChange={(event) => onChange(key, event.target.checked ? "true" : null)}
              className="h-4 w-4 rounded border-border accent-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            />
            {label}
          </Label>
          {key === "paid" && <p className="text-xs text-muted-foreground">Only listings that state pay</p>}
        </div>
      ))}
      {selects.map(({ key, label, options }) => (
        <div key={key} className="space-y-2">
          <Label htmlFor={`${idPrefix}-${key}`} className="eyebrow">{label}</Label>
          <Select
            value={searchParams.get(key) ?? "all"}
            disabled={disabled}
            onValueChange={(value) => onChange(key, value === "all" ? null : value)}
          >
            <SelectTrigger id={`${idPrefix}-${key}`} aria-label={label} className="w-full">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {options.map(([value, text]) => <SelectItem key={value} value={value}>{text}</SelectItem>)}
            </SelectContent>
          </Select>
          {key === "min_stipend" && <p className="text-xs text-muted-foreground">Only listings that state pay</p>}
        </div>
      ))}
    </div>
  );
}
