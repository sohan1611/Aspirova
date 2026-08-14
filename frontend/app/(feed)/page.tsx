import { SearchX } from "lucide-react";
import Link from "next/link";
import FeedViewControls from "@/components/FeedViewControls";
import ForYouControl from "@/components/ForYouControl";
import MostViewed from "@/components/MostViewed";
import OpportunityCard from "@/components/OpportunityCard";
import RecentlyViewed from "@/components/RecentlyViewed";
import SearchFilters from "@/components/SearchFilters";
import SignedInWelcome from "@/components/SignedInWelcome";
import SignedOutHero from "@/components/SignedOutHero";
import SourceCompanyCard from "@/components/SourceCompanyCard";
import StatsBar from "@/components/StatsBar";
import { Button } from "@/components/ui/button";
import TopCompanies from "@/components/TopCompanies";
import { getFeed, getForYou, getStats, getTrending, searchOpportunities } from "@/lib/api";
import { findExternalCompany } from "@/lib/externalCompanies";
import { buildPageHref } from "@/lib/pagination";
import { matchesResearchIntent } from "@/lib/programmes";
import type { StatsResponse } from "@/lib/types";

interface PageProps {
  searchParams: Promise<{
    q?: string;
    category?: string;
    kind?: string;
    source?: string;
    experience?: string;
    remote?: string;
    location?: string | string[];
    company?: string | string[];
    top?: string;
    scope?: string;
    country?: string;
    remote_abroad?: string;
    sort?: string;
    view?: string;
    fields?: string;
    terms?: string;
    skills?: string;
    page?: string;
    cols?: string;
    rows?: string;
  }>;
}

const COLS_LG: Record<number, string> = {
  1: "lg:grid-cols-1",
  2: "lg:grid-cols-2",
  3: "lg:grid-cols-3",
  4: "lg:grid-cols-4",
};

async function loadStats(): Promise<StatsResponse | null> {
  try {
    return await getStats();
  } catch {
    return null;
  }
}

export default async function HomePage({ searchParams }: PageProps) {
  const params = await searchParams;
  const sourceCompany = params.q ? findExternalCompany(params.q) : undefined;
  const showResearch = params.q ? matchesResearchIntent(params.q) : false;
  const page = Math.max(1, Number(params.page ?? "1") || 1);
  const cols = Math.min(4, Math.max(1, Number(params.cols ?? "3") || 3));
  const rows = Math.min(20, Math.max(5, Number(params.rows ?? "10") || 10));
  const LIMIT = cols * rows;
  const top = params.top ? Number(params.top) : undefined;
  const sort: "student" | "recent" | "deadline" =
    params.sort === "deadline"
      ? "deadline"
      : params.sort === "recent"
        ? "recent"
        : "student";
  const kind = params.kind
    ? (params.kind as "roles" | "competitions")
    : params.category
      ? undefined
      : "roles";

  const filters = {
    category: params.category as "internship" | "job" | undefined,
    kind: params.kind as "roles" | "competitions" | undefined,
    source: params.source as
      | "direct"
      | "unstop"
      | "remoteok"
      | "devpost"
      | undefined,
    experience: params.experience as "early" | undefined,
    remote: params.remote === "true" ? true : params.remote === "false" ? false : undefined,
    location: params.location,
    company: params.company,
    top: top && Number.isFinite(top) && top > 0 ? top : undefined,
    scope: params.scope as "abroad" | "domestic" | "both" | undefined,
    country: params.country,
    remote_abroad: params.remote_abroad === "true" ? true : undefined,
  };
  const forYouFields = params.fields
    ?.split(",")
    .map((field) => field.trim())
    .filter(Boolean);
  const forYouTerms = params.terms
    ?.split(",")
    .map((term) => term.trim())
    .filter(Boolean);
  const forYouSkills = params.skills
    ?.split(",")
    .map((skill) => skill.trim())
    .filter(Boolean);
  const isForYou = (params.view === "foryou" || Boolean(forYouSkills?.length)) && !params.q;
  const hasActiveFilters = Boolean(
    params.category ||
      params.kind ||
      params.source ||
      params.experience ||
      params.remote !== undefined ||
      params.location ||
      params.company ||
      params.top ||
      params.scope ||
      params.country ||
      params.remote_abroad === "true" ||
      params.sort === "recent" ||
      params.sort === "deadline",
  );
  const isCleanDefaultFeed =
    !params.q &&
    params.view !== "foryou" &&
    !params.fields &&
    !params.terms &&
    !params.skills &&
    !hasActiveFilters &&
    page === 1;

  const statsPromise = loadStats();
  const trendingPromise = isCleanDefaultFeed ? getTrending() : null;
  const data = params.q
    ? await searchOpportunities(params.q, filters, page, LIMIT)
    : isForYou
      ? await getForYou({
          terms: forYouTerms,
          skills: forYouSkills,
          fields: forYouFields,
          categories: params.category ? [params.category] : undefined,
          country: params.country,
          scope: filters.scope,
          page,
          limit: LIMIT,
        })
    : await getFeed({
        ...filters,
        kind,
        sort,
        page,
        limit: LIMIT,
      });
  const [stats, trending] = await Promise.all([
    statsPromise,
    trendingPromise ?? Promise.resolve({ items: [] }),
  ]);

  const totalPages = Math.max(1, Math.ceil(data.total / LIMIT));

  return (
    <main className="mx-auto max-w-[1680px] px-4 pb-10 sm:px-6 lg:px-10 xl:px-12">
      <SignedOutHero />
      <SignedInWelcome />
      {stats && <StatsBar stats={stats} />}
      <RecentlyViewed />
      {isCleanDefaultFeed && <MostViewed items={trending.items} />}

      <div id="feed-search" className="mb-6 scroll-mt-20 pt-10">
        <ForYouControl />
        <div className="mt-3">
          <SearchFilters />
        </div>
      </div>

      <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
        <p className="text-sm text-muted-foreground">{data.total} opportunities</p>
        <FeedViewControls cols={cols} rows={rows} />
      </div>

      {sourceCompany && (
        <section className="mb-6 max-w-md">
          <p className="eyebrow mb-3">Straight to source</p>
          <SourceCompanyCard company={sourceCompany} />
        </section>
      )}

      {showResearch && (
        <section className="mb-6 max-w-md">
          <div className="rounded-xl border border-border bg-card p-5 shadow-soft">
            <p className="eyebrow">Research track</p>
            <p className="mt-3 text-sm leading-6 text-muted-foreground">
              India&apos;s flagship IISc, IIT, NIT &amp; TIFR research fellowships and
              internships, with the windows they usually open in.
            </p>
            <Button asChild variant="outline" size="sm" className="mt-4">
              <Link href="/research">Explore the research track →</Link>
            </Button>
          </div>
        </section>
      )}

      <TopCompanies />

      {data.items.length > 0 ? (
        <div className={`grid grid-cols-1 sm:grid-cols-2 gap-6 ${COLS_LG[cols]}`}>
          {data.items.map((item) => (
            <OpportunityCard key={item.slug} item={item} />
          ))}
        </div>
      ) : (
        <div className="flex flex-col items-center px-4 py-20 text-center sm:py-24">
          <div className="rounded-lg border border-border bg-secondary/40 p-3">
            <SearchX className="h-6 w-6 text-muted-foreground" aria-hidden="true" />
          </div>
          <h2 className="mt-5 text-xl font-semibold text-foreground">Nothing matches — yet.</h2>
          <p className="mt-2 max-w-md text-sm leading-relaxed text-muted-foreground">
            Try a broader search or clear your filters — the almanac updates daily.
          </p>
          <Button className="mt-5" variant="outline" size="sm" asChild>
            <Link href="/">Clear filters</Link>
          </Button>
        </div>
      )}

      {totalPages > 1 && (
        <div className="mt-8 flex items-center justify-center gap-4">
          <Button variant="outline" size="sm" disabled={page <= 1} asChild={page > 1}>
            {page > 1 ? <Link href={buildPageHref(params, page - 1)}>Previous</Link> : "Previous"}
          </Button>
          <span className="text-sm text-muted-foreground">
            Page {page} of {totalPages}
          </span>
          <Button variant="outline" size="sm" disabled={page >= totalPages} asChild={page < totalPages}>
            {page < totalPages ? (
              <Link href={buildPageHref(params, page + 1)}>Next</Link>
            ) : (
              "Next"
            )}
          </Button>
        </div>
      )}
    </main>
  );
}
