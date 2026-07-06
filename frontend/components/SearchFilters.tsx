"use client";

import { Search } from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

const CATEGORY_OPTIONS = [
  { value: null, label: "All" },
  { value: "internship", label: "Internships" },
  { value: "job", label: "Jobs" },
];

const REMOTE_OPTIONS = [
  { value: null, label: "Any" },
  { value: "true", label: "Remote" },
  { value: "false", label: "On-site" },
];

function SegmentedGroup({
  label,
  options,
  active,
  onSelect,
}: {
  label: string;
  options: { value: string | null; label: string }[];
  active: string | null;
  onSelect: (value: string | null) => void;
}) {
  return (
    <div role="group" aria-label={label} className="inline-flex rounded-md border border-border bg-muted p-1">
      {options.map((option) => {
        const isActive = option.value === active;
        return (
          <button
            key={option.label}
            type="button"
            aria-pressed={isActive}
            onClick={() => onSelect(option.value)}
            className={cn(
              "rounded-sm px-3 py-1.5 text-sm font-medium transition-colors duration-150",
              isActive
                ? "bg-background text-foreground shadow-xs"
                : "text-muted-foreground hover:text-foreground",
            )}
          >
            {option.label}
          </button>
        );
      })}
    </div>
  );
}

export default function SearchFilters() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [q, setQ] = useState(searchParams.get("q") ?? "");

  function updateParam(key: string, value: string | null) {
    const params = new URLSearchParams(searchParams.toString());
    if (value) {
      params.set(key, value);
    } else {
      params.delete(key);
    }
    params.delete("page");
    router.push(`/?${params.toString()}`);
  }

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    updateParam("q", q || null);
  }

  return (
    <div className="flex flex-wrap items-center gap-3">
      <form onSubmit={handleSubmit} className="flex gap-2">
        <div className="relative">
          <Search className="pointer-events-none absolute top-1/2 left-3 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            type="search"
            placeholder="Search opportunities..."
            value={q}
            onChange={(e) => setQ(e.target.value)}
            className="w-64 pl-9"
          />
        </div>
        <Button type="submit">Search</Button>
      </form>

      <SegmentedGroup
        label="Category"
        options={CATEGORY_OPTIONS}
        active={searchParams.get("category")}
        onSelect={(value) => updateParam("category", value)}
      />

      <SegmentedGroup
        label="Location"
        options={REMOTE_OPTIONS}
        active={searchParams.get("remote")}
        onSelect={(value) => updateParam("remote", value)}
      />
    </div>
  );
}
