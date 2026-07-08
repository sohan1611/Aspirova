import { SearchX } from "lucide-react";
import Link from "next/link";
import FeedViewControls from "@/components/FeedViewControls";
import OpportunityCard from "@/components/OpportunityCard";
import SearchFilters from "@/components/SearchFilters";
import { Button } from "@/components/ui/button";
import { getFeed, searchOpportunities } from "@/lib/api";
import { buildPageHref } from "@/lib/pagination";

interface PageProps {
  searchParams: Promise<{
    q?: string;
    category?: string;
    remote?: string;
    page?: string;
    cols?: string;
    rows?: string;
  }>;
}

const COLS_MD: Record<number, string> = {
  1: "md:grid-cols-1",
  2: "md:grid-cols-2",
  3: "md:grid-cols-3",
};

export default async function HomePage({ searchParams }: PageProps) {
  const params = await searchParams;
  const page = Math.max(1, Number(params.page ?? "1") || 1);
  const cols = Math.min(3, Math.max(1, Number(params.cols ?? "2") || 2));
  const rows = Math.min(20, Math.max(5, Number(params.rows ?? "10") || 10));
  const LIMIT = cols * rows;

  const data = params.q
    ? await searchOpportunities(params.q, page, LIMIT)
    : await getFeed({
        category: params.category as "internship" | "job" | undefined,
        remote: params.remote === "true" ? true : params.remote === "false" ? false : undefined,
        page,
        limit: LIMIT,
      });

  const totalPages = Math.max(1, Math.ceil(data.total / LIMIT));

  return (
    <main className="mx-auto max-w-7xl px-4 py-10 sm:px-6 lg:px-8">
      <div className="mb-6">
        <SearchFilters />
      </div>

      <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
        <p className="text-sm text-muted-foreground">{data.total} opportunities</p>
        <FeedViewControls cols={cols} rows={rows} />
      </div>

      {data.items.length > 0 ? (
        <div className={`grid grid-cols-1 gap-4 ${COLS_MD[cols]}`}>
          {data.items.map((item) => (
            <OpportunityCard key={item.slug} item={item} />
          ))}
        </div>
      ) : (
        <div className="flex flex-col items-center gap-3 rounded-lg border border-dashed border-border py-16 text-center">
          <SearchX className="h-8 w-8 text-muted-foreground" aria-hidden="true" />
          <p className="font-medium text-foreground">No opportunities found</p>
          <p className="max-w-xs text-sm text-muted-foreground">
            Try a different search term or clear a filter.
          </p>
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
