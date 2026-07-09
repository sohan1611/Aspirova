"use client";

import { useEffect, useRef } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

const STORAGE_KEY = "aspirova_feed_view";
const COLUMN_OPTIONS = [1, 2, 3, 4];
const ROW_OPTIONS = [5, 10, 15, 20];

interface FeedViewControlsProps {
  cols: number;
  rows: number;
}

export default function FeedViewControls({ cols, rows }: FeedViewControlsProps) {
  const router = useRouter();
  const searchParams = useSearchParams();
  const restoredPreference = useRef(false);

  useEffect(() => {
    if (restoredPreference.current) return;
    restoredPreference.current = true;

    if (searchParams.has("cols") || searchParams.has("rows")) return;

    try {
      const saved = window.localStorage.getItem(STORAGE_KEY);
      if (!saved) return;

      const preference = JSON.parse(saved) as { cols?: number; rows?: number };
      if (
        !COLUMN_OPTIONS.includes(preference.cols ?? 0) ||
        !ROW_OPTIONS.includes(preference.rows ?? 0)
      ) {
        return;
      }

      const params = new URLSearchParams(searchParams.toString());
      params.set("cols", String(preference.cols));
      params.set("rows", String(preference.rows));
      params.delete("page");
      router.replace(`/?${params.toString()}`);
    } catch {
      // Ignore malformed or unavailable local storage.
    }
  }, [router, searchParams]);

  function updateView(key: "cols" | "rows", value: string) {
    const params = new URLSearchParams(searchParams.toString());
    params.set(key, value);
    params.delete("page");

    const nextCols = key === "cols" ? Number(value) : cols;
    const nextRows = key === "rows" ? Number(value) : rows;

    try {
      window.localStorage.setItem(
        STORAGE_KEY,
        JSON.stringify({ cols: nextCols, rows: nextRows }),
      );
    } catch {
      // Continue with URL navigation if local storage is unavailable.
    }

    router.push(`/?${params.toString()}`);
  }

  return (
    <div className="flex items-center gap-3">
      <div className="hidden items-center gap-2 lg:flex">
        <label htmlFor="feed-columns" className="text-xs font-medium text-muted-foreground">
          Columns
        </label>
        <Select value={String(cols)} onValueChange={(value) => updateView("cols", value)}>
          <SelectTrigger id="feed-columns" size="sm" aria-label="Columns">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {COLUMN_OPTIONS.map((option) => (
              <SelectItem key={option} value={String(option)}>
                {option}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      <div className="flex items-center gap-2">
        <label htmlFor="feed-rows" className="text-xs font-medium text-muted-foreground">
          Per page
        </label>
        <Select value={String(rows)} onValueChange={(value) => updateView("rows", value)}>
          <SelectTrigger id="feed-rows" size="sm" aria-label="Rows per page">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {ROW_OPTIONS.map((option) => (
              <SelectItem key={option} value={String(option)}>
                {option}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
    </div>
  );
}
