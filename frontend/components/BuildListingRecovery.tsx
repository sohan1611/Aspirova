"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import CompanyFavicon from "@/components/CompanyFavicon";
import CompanyOpportunities from "@/components/CompanyOpportunities";
import ProgrammeCard from "@/components/ProgrammeCard";
import ProgrammeAlmanac from "@/components/ProgrammeAlmanac";
import { ListingEmpty, ListingFailure } from "@/components/ListingFeedback";
import { getCompanies, getCompanyPage, getProgrammes, type ProgrammeParams } from "@/lib/api";
import { failedList, loadedList, type ListState } from "@/lib/listState";

// Only the explicit CI/local-build failure shell uses this recovery path. Fetch
// on mount, not just on Retry, so an offline prerender heals when viewed online.
function useBuildListing<T>(load: () => Promise<T>, count: (data: T) => number) {
  const [state, setState] = useState<ListState<T>>(() => failedList<T>(null));
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    let cancelled = false;
    void load().then(data => {
      if (!cancelled) setState(loadedList(data, count(data)));
    }).catch(() => {
      if (!cancelled) setState(previous => failedList(previous));
    });
    return () => { cancelled = true; };
  }, [load, count, attempt]);
  return { state, retry: () => setAttempt(value => value + 1) };
}

const itemCount = (data: { items: unknown[] }) => data.items.length;
const arrayCount = (data: unknown[]) => data.length;
const companyCount = (data: Awaited<ReturnType<typeof getCompanyPage>>) => data?.items.length ?? 0;

export function ProgrammeBuildRecovery({ params, pathname = "/programmes", query = "", almanac = false }: {
  params: ProgrammeParams; pathname?: string; query?: string; almanac?: boolean;
}) {
  const key = JSON.stringify(params);
  const load = useCallback(() => getProgrammes(JSON.parse(key) as ProgrammeParams), [key]);
  const { state, retry } = useBuildListing(load, itemCount);
  const data = state.data;
  if (!data || (state.status === "failed" && !data.items.length)) return <ListingFailure retry={retry} />;
  if (state.status === "empty") return <ListingEmpty pathname={pathname} query={query} title="No programmes match this view." />;
  return <>
    {state.status === "failed" && <ListingFailure retry={retry} loadedAt={state.loadedAt} />}
    <p className="my-4 text-sm text-muted-foreground">{data.total} programmes</p>
    {almanac && <ProgrammeAlmanac programmes={data.items} />}
    <div className="grid grid-cols-1 gap-6 sm:grid-cols-2 lg:grid-cols-3">
      {data.items.map(programme => <ProgrammeCard key={programme.slug} programme={programme} />)}
    </div>
  </>;
}

export function CompaniesBuildRecovery() {
  const { state, retry } = useBuildListing(getCompanies, arrayCount);
  const companies = state.data;
  if (!companies || (state.status === "failed" && !companies.length)) return <ListingFailure retry={retry} />;
  if (state.status === "empty") return <ListingEmpty pathname="/companies" title="No companies are hiring here yet." />;
  return <>
    {state.status === "failed" && <ListingFailure retry={retry} loadedAt={state.loadedAt} />}
    <p className="my-4 text-sm text-muted-foreground">{companies.length} companies</p>
    <div className="grid grid-cols-1 gap-6 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
      {companies.map(company => <Link key={company.slug} href={`/companies/${encodeURIComponent(company.slug)}`} className="rounded-lg border border-border bg-card p-5 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
        <CompanyFavicon company={company} size={70} />
        <h2 className="mt-4 font-serif text-lg font-bold">{company.name}</h2>
        <p className="mt-2 text-sm text-muted-foreground">{company.active_count} open roles</p>
      </Link>)}
    </div>
  </>;
}

export function CompanyBuildRecovery({ slug, page, limit }: { slug: string; page: number; limit: number }) {
  const load = useCallback(() => getCompanyPage(slug, page, limit), [slug, page, limit]);
  const { state, retry } = useBuildListing(load, companyCount);
  if (!state.data) return <ListingFailure retry={retry} />;
  return <>
    {state.status === "failed" && <ListingFailure retry={retry} loadedAt={state.loadedAt} />}
    <CompanyOpportunities data={state.data} page={page} slug={slug} />
  </>;
}
