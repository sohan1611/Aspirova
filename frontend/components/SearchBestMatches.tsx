"use client";

import Link from "next/link";
import { useId } from "react";
import CompanyFavicon from "@/components/CompanyFavicon";
import { windowText } from "@/lib/hiringCalendar";
import { useSearchRelatedResults } from "@/lib/listingResults";
import { safeExternalUrl } from "@/lib/safeUrl";
import type { SearchRelatedResponse } from "@/lib/types";

interface Props {
  scope: string;
  queryKey: string;
  q: string;
  loading: boolean;
  // Present only on surfaces supporting source filters.
  searchQuery?: string;
  // Companies the page already shows (the "Straight to source" card), so one employer never appears twice.
  excludeCompanyNames?: string[];
}

/** Pure view exported for node rendering tests; fetching belongs to the result lifecycle. */
export function SearchBestMatchesView({ data, q, searchQuery, excludeCompanyNames }: {
  data: SearchRelatedResponse | null;
  q: string;
  searchQuery?: string;
  excludeCompanyNames?: string[];
}) {
  const id = useId();
  const excluded = new Set((excludeCompanyNames ?? []).map(name => name.trim().toLowerCase()));
  const companies = data ? data.companies.items.filter(company => !excluded.has(company.name.trim().toLowerCase())) : [];
  if (!data || (!data.programmes.items.length && !companies.length)) return null;
  const linkClass = "inline-flex min-h-11 items-center py-2 text-primary underline-offset-4 hover:underline";
  return (
    <section aria-labelledby={id} className="mb-6 min-w-0 max-w-full">
      <h2 id={id} className="mb-3 text-sm font-semibold">Best matches</h2>
      <div className="flex max-w-full gap-3 overflow-x-auto pb-2 sm:grid sm:grid-cols-2 sm:overflow-visible lg:grid-cols-3">
        {data.programmes.items.map(programme => {
          const officialUrl = safeExternalUrl(programme.official_url);
          const edition = programme.edition;
          return (
            <article key={`programme:${programme.slug}`} className="w-72 min-w-0 shrink-0 rounded-lg border border-border bg-card p-4 sm:w-auto">
              <p className="text-xs text-muted-foreground">Programme · <Link href={programme.calendar_path} className={linkClass}>Hiring Calendar</Link></p>
              <h3 className="break-words font-semibold"><Link href={programme.path} className={linkClass}>{programme.name}</Link></h3>
              <p className="break-words text-sm text-muted-foreground">{programme.organiser}</p>
              <p className="mt-2 text-sm">{edition ? <>
                <span className="font-medium">{edition.basis === "official" ? "Official" : "Tentative · historical trend"}</span>
                {" · "}{windowText({ edition, metadata: { deadline_rolling: programme.deadline_rolling } })}
              </> : "Dates not announced yet"}</p>
              {officialUrl && <a href={officialUrl} target="_blank" rel="noopener noreferrer" className={`${linkClass} mt-1 break-all text-sm`}>Official site ↗ · {new URL(officialUrl).hostname}</a>}
            </article>
          );
        })}
        {companies.map(company => (
          <article key={`company:${company.slug}`} className="w-72 min-w-0 shrink-0 rounded-lg border border-border bg-card p-4 sm:w-auto">
            <p className="mb-3 text-xs text-muted-foreground">Company</p>
            <CompanyFavicon company={company} />
            <h3 className="break-words font-semibold"><Link href={company.path} className={linkClass}>{company.name}</Link></h3>
            <p className="text-sm text-muted-foreground">{company.active_count ? `${company.active_count} open ${company.active_count === 1 ? "role" : "roles"}` : "No open roles right now"}</p>
          </article>
        ))}
      </div>
      {data.programmes.total > data.programmes.items.length && <Link href={`/programmes?${new URLSearchParams({ q })}`} className={`${linkClass} text-sm`}>See all {data.programmes.total} programmes</Link>}
      <div className="mt-2 text-sm">
        <p className="font-medium">Listings ({data.listings.total.toLocaleString("en-IN")})</p>
        <div className="flex flex-wrap gap-x-3 gap-y-1 text-muted-foreground">
          {data.listings.by_source.map(source => {
            const text = `${source.label} ${source.count.toLocaleString("en-IN")}`;
            // "other" has no public source-filter value.
            if (searchQuery !== undefined && source.value !== "other") {
              const params = new URLSearchParams(searchQuery);
              params.set("q", q);
              params.set("source", source.value);
              params.delete("page");
              return <Link key={source.value} href={`/?${params}#feed-search`} className={linkClass}>{text}</Link>;
            }
            return <span key={source.value} className="inline-flex min-h-11 items-center">{text}</span>;
          })}
        </div>
      </div>
    </section>
  );
}

export default function SearchBestMatches({ scope, queryKey, q, loading, searchQuery, excludeCompanyNames }: Props) {
  const data = useSearchRelatedResults(scope, queryKey);
  return loading ? null : <SearchBestMatchesView data={data} q={q} searchQuery={searchQuery} excludeCompanyNames={excludeCompanyNames} />;
}
