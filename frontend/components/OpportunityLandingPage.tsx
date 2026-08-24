import { SearchX } from "lucide-react";
import Link from "next/link";
import OpportunityCard from "@/components/OpportunityCard";
import { Button } from "@/components/ui/button";
import { buildPagePath } from "@/lib/pagination";
import type { OpportunityListItem } from "@/lib/types";

const EMPTY_STATE_CLASS_NAME = [
  "flex flex-col items-center gap-3 rounded-lg border border-dashed",
  "border-border py-16 text-center",
].join(" ");

interface OpportunityLandingPageProps {
  title: string;
  intro: string;
  items: OpportunityListItem[];
  total: number;
  page: number;
  limit: number;
  basePath: string;
}

export default function OpportunityLandingPage({
  title,
  intro,
  items,
  total,
  page,
  limit,
  basePath,
}: OpportunityLandingPageProps) {
  const totalPages = Math.max(1, Math.ceil(total / limit));

  return (
    <main className="mx-auto max-w-3xl px-4 py-8">
      <div className="mb-6">
        <h1 className="text-3xl font-bold tracking-tight text-foreground">{title}</h1>
        <p className="mt-2 max-w-2xl text-sm leading-6 text-muted-foreground">{intro}</p>
      </div>

      <p className="mb-3 text-sm text-muted-foreground">{total} opportunities</p>

      {items.length > 0 ? (
        <div className="space-y-3">
          {items.map((item) => (
            <OpportunityCard key={item.slug} item={item} />
          ))}
        </div>
      ) : (
        <div className={EMPTY_STATE_CLASS_NAME}>
          <SearchX className="h-8 w-8 text-muted-foreground" aria-hidden="true" />
          <p className="font-medium text-foreground">Nothing open here — yet.</p>
          <p className="max-w-xs text-sm text-muted-foreground">
            Aspirova is always discovering more from public career pages. Meanwhile, browse
            everything on offer.
          </p>
          <Button variant="outline" size="sm" asChild>
            <Link href="/">Browse all opportunities</Link>
          </Button>
        </div>
      )}

      {totalPages > 1 && (
        <div className="mt-8 flex items-center justify-center gap-4">
          <Button variant="outline" size="sm" disabled={page <= 1} asChild={page > 1}>
            {page > 1 ? (
              <Link href={buildPagePath(basePath, page - 1)} rel="prev">
                Previous
              </Link>
            ) : (
              "Previous"
            )}
          </Button>
          <span className="text-sm text-muted-foreground">
            Page {page} of {totalPages}
          </span>
          <Button
            variant="outline"
            size="sm"
            disabled={page >= totalPages}
            asChild={page < totalPages}
          >
            {page < totalPages ? (
              <Link href={buildPagePath(basePath, page + 1)} rel="next">
                Next
              </Link>
            ) : (
              "Next"
            )}
          </Button>
        </div>
      )}
    </main>
  );
}
