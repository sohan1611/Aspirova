import type { Metadata } from "next";
import Link from "next/link";

export const metadata: Metadata = {
  title: "About",
  description: "How Aspirova gathers student opportunities from public sources and links you to the original listing.",
};

export default function AboutPage() {
  return (
    <main className="mx-auto w-full max-w-4xl px-6 py-16 sm:px-8 sm:py-20">
      <header className="border-b border-border pb-10">
        <p className="eyebrow">Aspirova</p>
        <h1 className="mt-3 font-serif text-4xl font-semibold leading-tight tracking-tight text-foreground sm:text-5xl">
          About Aspirova
        </h1>
        <p className="mt-5 max-w-2xl text-lg leading-8 text-muted-foreground">
          Aspirova helps students find internships, jobs, hackathons, scholarships and research programmes in one place.
        </p>
        <p className="mt-5 max-w-2xl text-base leading-7 text-muted-foreground">
          Most opportunities are scattered across thousands of company career pages and event sites. Aspirova checks them every day and brings the open ones together, so you can spend your time applying instead of searching.
        </p>
      </header>

      <article className="mt-12 max-w-none">
        <section className="scroll-mt-24">
          <h2 className="font-serif text-2xl font-semibold tracking-tight text-foreground">
            How it works
          </h2>
          <p className="mt-4 text-base leading-7 text-muted-foreground">
            We gather listings from public sources such as company career pages, job boards and competition platforms. When you apply, you always go to the original listing. Aspirova never handles your application.
          </p>
        </section>

        <section className="mt-12 scroll-mt-24 border-t border-border pt-10">
          <h2 className="font-serif text-2xl font-semibold tracking-tight text-foreground">
            Not a job board
          </h2>
          <p className="mt-4 text-base leading-7 text-muted-foreground">
            Companies don&apos;t post on Aspirova and can&apos;t pay to appear here. Listings come from the sources we check.
          </p>
        </section>

        <section className="mt-12 scroll-mt-24 border-t border-border pt-10">
          <h2 className="font-serif text-2xl font-semibold tracking-tight text-foreground">
            Who builds it
          </h2>
          <p className="mt-4 text-base leading-7 text-muted-foreground">
            Aspirova is built by a student who wanted a better way to find opportunities. If something is wrong or missing, please tell us.
          </p>
          <p className="mt-4 text-base leading-7 text-muted-foreground">
            <Link className="font-medium text-foreground underline decoration-primary/40 underline-offset-4 transition-colors hover:decoration-primary" href="/report">
              Report an issue
            </Link>{" "}
            or{" "}
            <Link className="font-medium text-foreground underline decoration-primary/40 underline-offset-4 transition-colors hover:decoration-primary" href="/contact">
              contact us
            </Link>.
          </p>
        </section>
      </article>
    </main>
  );
}
