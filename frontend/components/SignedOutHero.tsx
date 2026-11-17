import Link from "next/link";
import SignedOutHeroVisibility from "@/components/SignedOutHeroVisibility";
import HomePreviews from "@/components/HomePreviews";
import { HOME_CATEGORIES } from "@/lib/home";
import type { CalendarItem } from "@/lib/hiringCalendar";
import type { OpportunityListItem } from "@/lib/types";

export default function SignedOutHero({ closing = null, calendar = null, asOf }: {
  closing?: OpportunityListItem[] | null;
  calendar?: CalendarItem[] | null;
  asOf: number;
}) {
  return (
    <SignedOutHeroVisibility>
      <section aria-labelledby="signed-out-hero-title" className="auth-collapse-while-pending border-b border-border py-5 sm:py-8">
        <div className="grid gap-6 lg:grid-cols-[1fr_1.2fr] lg:gap-10">
          <div className="min-w-0">
            <p className="eyebrow text-primary">The Opportunity Almanac</p>
            <h1 id="signed-out-hero-title" tabIndex={-1} className="mt-2 font-serif text-3xl font-bold leading-tight sm:text-4xl">
              Every opportunity. One place.
            </h1>
            <p className="mt-3 max-w-xl text-sm leading-5 text-muted-foreground">
              Openings from company career pages and public listing sites. Apply always takes you to the original listing.
            </p>
            <form role="search" action="/#feed-search" method="get" className="mt-4">
              <label htmlFor="hero-search" className="text-sm font-medium">Find your next opportunity</label>
              <div className="mt-2 flex gap-2">
                <input id="hero-search" name="q" type="search" aria-label="Search opportunities" placeholder="Role, company or skill" maxLength={200}
                  className="min-h-11 min-w-0 flex-1 rounded-md border border-input bg-background px-3 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring" />
                <button type="submit" className="min-h-11 rounded-md bg-primary px-4 text-sm font-medium text-primary-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2">Search</button>
              </div>
            </form>
            <nav aria-label="Browse opportunity categories" className="mt-3 grid grid-cols-3 gap-2">
              {HOME_CATEGORIES.map(([href, label]) => (
                <Link key={href} href={href} className="inline-flex min-h-11 items-center justify-center rounded-md border border-border px-2 text-xs font-medium hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">{label}</Link>
              ))}
            </nav>
            <p className="mt-3 text-xs leading-5 text-muted-foreground">
              No “verified employer” claim: we show where a link goes and how fresh it is. Check requirements at the source. Browse without signing up.
            </p>
            <a href="#feed-search" className="mt-1 inline-flex min-h-11 items-center text-sm font-medium text-primary underline underline-offset-4 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">Browse below ↓</a>
          </div>
          <HomePreviews closing={closing} calendar={calendar} asOf={asOf} />
        </div>
      </section>
    </SignedOutHeroVisibility>
  );
}
