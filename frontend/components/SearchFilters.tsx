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

const TOP_OPTIONS = [
  { value: null, label: "Any" },
  { value: "10", label: "Top 10" },
  { value: "50", label: "50" },
  { value: "100", label: "100" },
  { value: "500", label: "500" },
  { value: "1000", label: "1000" },
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
    <div
      role="group"
      aria-label={label}
      className="inline-flex max-w-full flex-wrap rounded-md border border-border bg-muted p-1"
    >
      {options.map((option) => {
        const isActive = option.value === active;
        return (
          <button
            key={option.label}
            type="button"
            aria-pressed={isActive}
            onClick={() => onSelect(option.value)}
            className={cn(
              "whitespace-nowrap rounded-sm px-3 py-1.5 text-sm font-medium transition-[background-color,color,box-shadow] duration-200 ease-[var(--ease-premium)]",
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
  const [location, setLocation] = useState(searchParams.get("location") ?? "");
  const [company, setCompany] = useState(searchParams.get("company") ?? "");
  const top = searchParams.get("top");
  const hasFilters = ["q", "category", "remote", "location", "company", "top"].some((key) =>
    searchParams.has(key),
  );

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

  function commitTextParam(key: string, value: string) {
    const nextValue = value.trim() || null;
    if ((searchParams.get(key) ?? "") === (nextValue ?? "")) return;
    updateParam(key, nextValue);
  }

  function handleSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    updateParam("q", q || null);
  }

  function handleLocationSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    commitTextParam("location", location);
  }

  function handleCompanySubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    commitTextParam("company", company);
  }

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-3">
        <form onSubmit={handleSubmit} className="flex w-full flex-wrap gap-2 sm:w-auto">
          <div className="relative min-w-0 flex-1 sm:flex-none">
            <Search className="pointer-events-none absolute top-1/2 left-3 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              type="search"
              aria-label="Search opportunities"
              placeholder="Search opportunities..."
              value={q}
              onChange={(e) => setQ(e.target.value)}
              className="w-full pl-9 sm:w-72"
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
          label="Remote"
          options={REMOTE_OPTIONS}
          active={searchParams.get("remote")}
          onSelect={(value) => updateParam("remote", value)}
        />
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <span className="eyebrow">REFINE</span>

        <form onSubmit={handleLocationSubmit} className="min-w-0">
          <Input
            aria-label="Location"
            placeholder="City, country…"
            value={location}
            onBlur={() => commitTextParam("location", location)}
            onChange={(e) => setLocation(e.target.value)}
            className="w-44 max-w-full"
          />
        </form>

        <form onSubmit={handleCompanySubmit} className="min-w-0">
          <Input
            aria-label="Company"
            placeholder="Company name…"
            value={company}
            onBlur={() => commitTextParam("company", company)}
            onChange={(e) => setCompany(e.target.value)}
            className="w-52 max-w-full"
          />
        </form>

        <SegmentedGroup
          label="Top companies"
          options={TOP_OPTIONS}
          active={TOP_OPTIONS.some((option) => option.value === top) ? top : null}
          onSelect={(value) => updateParam("top", value)}
        />

        {hasFilters && (
          <button
            type="button"
            onClick={() => router.push("/")}
            className="text-sm font-medium text-muted-foreground transition-colors duration-200 ease-[var(--ease-premium)] hover:text-foreground"
          >
            Clear all
          </button>
        )}
      </div>
    </div>
  );
}
