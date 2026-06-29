"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";

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
        <input
          type="search"
          placeholder="Search opportunities..."
          value={q}
          onChange={(e) => setQ(e.target.value)}
          className="w-64 rounded border px-3 py-2 text-sm"
        />
        <button type="submit" className="rounded bg-black px-4 py-2 text-sm text-white">
          Search
        </button>
      </form>

      <select
        defaultValue={searchParams.get("category") ?? ""}
        onChange={(e) => updateParam("category", e.target.value || null)}
        className="rounded border px-2 py-2 text-sm"
      >
        <option value="">All categories</option>
        <option value="internship">Internships</option>
        <option value="job">Jobs</option>
      </select>

      <select
        defaultValue={searchParams.get("remote") ?? ""}
        onChange={(e) => updateParam("remote", e.target.value || null)}
        className="rounded border px-2 py-2 text-sm"
      >
        <option value="">Remote or on-site</option>
        <option value="true">Remote only</option>
        <option value="false">On-site only</option>
      </select>
    </div>
  );
}
