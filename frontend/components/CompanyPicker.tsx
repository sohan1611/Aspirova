"use client";

import { useEffect, useId, useRef, useState } from "react";
import CompanyFavicon from "@/components/CompanyFavicon";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { searchCompanies } from "@/lib/api";
import type { CompanyListItem } from "@/lib/types";
import { cn } from "@/lib/utils";

export default function CompanyPicker({
  value, onChange, followingSlugs = [], maxSelectable, disabled = false,
}: {
  value: CompanyListItem[];
  onChange: (companies: CompanyListItem[]) => void;
  followingSlugs?: string[];
  maxSelectable?: number | null;
  disabled?: boolean;
}) {
  const id = useId();
  const inputRef = useRef<HTMLInputElement>(null);
  const controllerRef = useRef<AbortController | null>(null);
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(-1);
  const [retry, setRetry] = useState(0);
  const [result, setResult] = useState<{
    query: string; retry: number; items: CompanyListItem[]; error: boolean;
  } | null>(null);
  const trimmed = query.trim();
  const capacity = Math.min(20, maxSelectable ?? 20);
  const atLimit = value.length >= capacity;
  const current = result?.query === trimmed && result.retry === retry ? result : null;
  const loading = trimmed.length >= 2 && !current;
  const items = current?.items ?? [];
  const expanded = open && !disabled && trimmed.length >= 2;

  useEffect(() => {
    const searchQuery = query.trim();
    if (searchQuery.length < 2) return;
    const controller = new AbortController();
    controllerRef.current = controller;
    const timer = setTimeout(() => {
      searchCompanies(searchQuery, controller.signal).then((companies) => {
        if (!controller.signal.aborted) {
          setResult({ query: searchQuery, retry, items: companies, error: false });
        }
      }).catch(() => {
        if (!controller.signal.aborted) {
          setResult({ query: searchQuery, retry, items: [], error: true });
        }
      });
    }, 250);
    return () => { clearTimeout(timer); controller.abort(); };
  }, [query, retry]);

  useEffect(() => {
    if (expanded && active >= 0) {
      document.getElementById(`${id}-option-${active}`)?.scrollIntoView({ block: "nearest" });
    }
  }, [active, expanded, id]);

  function isUnavailable(company: CompanyListItem) {
    return disabled || atLimit || followingSlugs.includes(company.slug) || value.some((item) => item.slug === company.slug);
  }

  function pick(company: CompanyListItem) {
    if (isUnavailable(company)) return;
    onChange([...value, company]);
    controllerRef.current?.abort();
    setQuery("");
    setResult(null);
    setOpen(false);
    setActive(-1);
    inputRef.current?.focus();
  }

  return (
    <div className="min-w-0 space-y-3" onBlur={(event) => {
      if (!event.currentTarget.contains(event.relatedTarget)) { setOpen(false); setActive(-1); }
    }}>
      <label htmlFor={`${id}-input`} className="text-sm font-medium">Companies</label>
      {value.length > 0 && (
        <ul aria-label="Selected companies" className="flex min-w-0 flex-wrap gap-2">
          {value.map((company) => (
            <li key={company.slug} className="flex min-w-0 max-w-full items-center gap-1 rounded-full border border-border bg-muted pl-3 text-sm">
              <span className="min-w-0 truncate">{company.name}</span>
              <button type="button" disabled={disabled} aria-label={`Remove ${company.name}`}
                className="min-h-10 min-w-10 shrink-0 rounded-full focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50"
                onClick={() => onChange(value.filter((item) => item.slug !== company.slug))}>×</button>
            </li>
          ))}
        </ul>
      )}
      <Input ref={inputRef} id={`${id}-input`} role="combobox" aria-autocomplete="list"
        aria-expanded={expanded} aria-controls={`${id}-results`} autoComplete="off"
        aria-activedescendant={expanded && items[active] ? `${id}-option-${active}` : undefined}
        aria-describedby={atLimit ? `${id}-limit` : undefined}
        placeholder="Search companies" value={query} disabled={disabled} className="min-h-10"
        onChange={(event) => {
          controllerRef.current?.abort();
          setQuery(event.target.value); setResult(null); setOpen(true); setActive(-1);
        }}
        onFocus={() => setOpen(true)}
        onKeyDown={(event) => {
          if (event.key === "Escape") { event.preventDefault(); setOpen(false); setActive(-1); }
          else if (event.key === "ArrowDown" || event.key === "ArrowUp") {
            event.preventDefault(); setOpen(true);
            if (items.length > 0) setActive((index) => event.key === "ArrowDown"
              ? (index + 1) % items.length : (index <= 0 ? items.length - 1 : index - 1));
          } else if (event.key === "Enter") {
            event.preventDefault();
            if (expanded) {
              const company = active >= 0 ? items[active] : items.find((item) => !isUnavailable(item));
              if (company) pick(company);
            }
          }
        }} />
      {expanded && (
        <div className="min-w-0 rounded-md border border-border bg-background p-1">
          {loading && <p role="status" className="p-3 text-sm text-muted-foreground">Searching companies…</p>}
          {current?.error && (
            <div role="alert" className="flex flex-wrap items-center gap-2 p-3 text-sm text-destructive">
              Couldn&apos;t search companies.
              <Button type="button" size="sm" variant="outline" onClick={() => { setRetry((count) => count + 1); setActive(-1); }}>Retry</Button>
            </div>
          )}
          {current && !current.error && items.length === 0 && <p role="status" className="p-3 text-sm text-muted-foreground">No companies found</p>}
          <ul id={`${id}-results`} role="listbox" aria-label="Company results" aria-busy={loading} className="max-h-72 overflow-y-auto">
            {items.map((company, index) => {
              const following = followingSlugs.includes(company.slug);
              const chosen = value.some((item) => item.slug === company.slug);
              return (
                <li key={company.slug} id={`${id}-option-${index}`} role="option" aria-selected={chosen}
                  aria-disabled={isUnavailable(company)}
                  onMouseDown={(event) => event.preventDefault()}
                  onMouseMove={() => setActive(index)} onClick={() => pick(company)}
                  className={cn("flex min-h-12 min-w-0 items-center gap-3 rounded px-2 py-3 text-sm", active === index && "bg-muted", isUnavailable(company) ? "cursor-default opacity-60" : "cursor-pointer")}>
                  <CompanyFavicon company={company} size={32} />
                  <div className="min-w-0 flex-1">
                    <p className="break-words [overflow-wrap:anywhere]">{company.name}</p>
                    <p className="text-xs text-muted-foreground">{company.active_count === 0 ? "No open roles right now" : `${company.active_count} open ${company.active_count === 1 ? "role" : "roles"}`}</p>
                    {(following || chosen) && <p className="text-xs font-medium">{following ? "Following" : "Chosen"}</p>}
                  </div>
                </li>
              );
            })}
          </ul>
        </div>
      )}
      {atLimit && <p id={`${id}-limit`} role="status" className="text-sm text-muted-foreground">
        {maxSelectable === 0
          ? "You've reached your plan's company limit. Remove a company below or see plans."
          : maxSelectable != null && maxSelectable > 0 && value.length >= maxSelectable
            ? "That's as many as your plan has room for."
            : "You can create up to 20 company alerts at once. Save these before adding more."}
      </p>}
    </div>
  );
}
