import Link from "next/link";
import OpportunityCard from "@/components/OpportunityCard";
import SearchFilters from "@/components/SearchFilters";
import { getFeed, searchOpportunities } from "@/lib/api";
import { buildPageHref } from "@/lib/pagination";

interface PageProps {
  searchParams: Promise<{
    q?: string;
    category?: string;
    remote?: string;
    page?: string;
  }>;
}

const LIMIT = 20;

export default async function HomePage({ searchParams }: PageProps) {
  const params = await searchParams;
  const page = Math.max(1, Number(params.page ?? "1") || 1);

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
    <main className="mx-auto max-w-3xl px-4 py-8">
      <div className="mb-6">
        <SearchFilters />
      </div>

      <p className="mb-3 text-sm text-gray-500">{data.total} opportunities</p>

      <div className="space-y-3">
        {data.items.map((item) => (
          <OpportunityCard key={item.slug} item={item} />
        ))}
      </div>

      {data.items.length === 0 && (
        <p className="py-12 text-center text-gray-500">No opportunities found.</p>
      )}

      {totalPages > 1 && (
        <div className="mt-8 flex justify-center gap-4 text-sm">
          {page > 1 && (
            <Link href={buildPageHref(params, page - 1)} className="underline">
              Previous
            </Link>
          )}
          <span className="text-gray-500">
            Page {page} of {totalPages}
          </span>
          {page < totalPages && (
            <Link href={buildPageHref(params, page + 1)} className="underline">
              Next
            </Link>
          )}
        </div>
      )}
    </main>
  );
}
