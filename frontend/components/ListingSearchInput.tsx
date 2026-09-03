"use client";

import { Search } from "lucide-react";
import { useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";
import { useFeedNavigation } from "@/components/FeedNavigation";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

const DEBOUNCE_MS = 300;

function hrefFor(path: string, params: URLSearchParams): string {
  const query = params.toString();
  return query ? `${path}?${query}` : path;
}

export default function ListingSearchInput({
  path,
  placeholder,
  ariaLabel,
  className,
}: {
  path: string;
  placeholder: string;
  ariaLabel: string;
  className?: string;
}) {
  const searchParams = useSearchParams();
  const { navigate, isFeedPending: isPending } = useFeedNavigation();
  const paramsSignature = searchParams.toString();
  const [value, setValue] = useState(searchParams.get("q") ?? "");
  const [syncedSignature, setSyncedSignature] = useState(paramsSignature);

  if (paramsSignature !== syncedSignature) {
    setSyncedSignature(paramsSignature);
    setValue(searchParams.get("q") ?? "");
  }

  function commitSearch(nextValue: string) {
    const params = new URLSearchParams(paramsSignature);
    const trimmedValue = nextValue.trim();

    if (trimmedValue) {
      params.set("q", trimmedValue);
    } else {
      params.delete("q");
    }

    params.delete("page");
    navigate(hrefFor(path, params));
  }

  useEffect(() => {
    const currentValue = searchParams.get("q") ?? "";
    const trimmedValue = value.trim();
    if (trimmedValue === currentValue) return;

    const timeout = window.setTimeout(() => {
      commitSearch(value);
    }, DEBOUNCE_MS);

    return () => window.clearTimeout(timeout);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [paramsSignature, value]);

  return (
    <form
      className={cn("min-w-0 flex-1 sm:flex-none", className)}
      onSubmit={(event) => {
        event.preventDefault();
        commitSearch(value);
      }}
    >
      <div className="relative min-w-0">
        <Search
          className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground"
          aria-hidden="true"
        />
        <Input
          type="search"
          aria-label={ariaLabel}
          placeholder={placeholder}
          value={value}
          disabled={isPending}
          onChange={(event) => setValue(event.target.value)}
          className="w-full pl-9 sm:w-72"
        />
      </div>
    </form>
  );
}
