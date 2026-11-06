import Link from "next/link";
import EmailMatchesButton from "@/components/EmailMatchesButton";
import { savedSearchParamsFromQuery } from "@/lib/savedSearchParams";
import FeedGrid from "@/components/FeedGrid";
import { FeedNavigationProvider } from "@/components/FeedNavigation";
import {
  BROWSE_LIMIT,
  browsePages,
  loadBrowsePage,
  type BrowseCategory,
  type BrowseConfig,
} from "@/lib/browse";

export function BrowseLinks({ category }: { category: BrowseCategory }) {
  return (
    <nav className="mt-12 space-y-6 border-t border-border pt-6" aria-label="Browse by city and role">
      {(["place", "role"] as const).map((kind) => (
        <div key={kind}>
          <h2 className="eyebrow">{kind === "place" ? "Browse by city" : "Browse by role"}</h2>
          <ul className="mt-3 flex flex-wrap gap-x-5 gap-y-3 text-sm">
            {browsePages(category, kind).map((page) => (
              <li key={page.path}>
                <Link className="underline underline-offset-4" href={page.path}>
                  {page.label}
                </Link>
              </li>
            ))}
          </ul>
        </div>
      ))}
    </nav>
  );
}

export default async function BrowsePage({ config }: { config: BrowseConfig }) {
  const data = await loadBrowsePage(config);
  return (
    <main className="mx-auto w-full max-w-[1680px] px-4 py-10 sm:px-6 sm:py-14 lg:px-10 xl:px-12">
      <header className="max-w-3xl">
        <p className="eyebrow">Open opportunities</p>
        <h1 className="mt-3 font-serif text-4xl font-bold leading-tight tracking-tight text-foreground sm:text-5xl">
          {config.title}
        </h1>
        <p className="mt-4 max-w-2xl text-sm leading-6 text-muted-foreground sm:text-base sm:leading-7">
          {config.description}
        </p>
      </header>
      <FeedNavigationProvider>
        <div className="mb-5 mt-10 flex flex-wrap items-center justify-between gap-3 border-b border-border pb-4">
          <p className="tnum text-sm text-muted-foreground">{data.total.toLocaleString("en-IN")} open</p>
          <EmailMatchesButton params={savedSearchParamsFromQuery(config.query)} />
        </div>
        <FeedGrid
          items={data.items}
          cols={3}
          skeletonCount={data.items.length}
          emptyHref={config.seeAll}
          emptyActionLabel="See all"
          emptyTitle="No open listings here yet."
          emptyDescription="Check the original sources or browse other listings."
        />
      </FeedNavigationProvider>
      {data.total > BROWSE_LIMIT && (
        <Link className="mt-8 inline-block text-sm underline underline-offset-4" href={config.seeAll}>
          See all
        </Link>
      )}
      <BrowseLinks category={config.category} />
    </main>
  );
}
