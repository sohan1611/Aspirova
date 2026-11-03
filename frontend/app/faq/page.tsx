import type { Metadata } from "next";
import Link from "next/link";

export const metadata: Metadata = {
  title: "Frequently asked questions",
  description: "Answers about Aspirova's free features, public listing sources, applications and your data.",
};

export default function FaqPage() {
  return (
    <main className="mx-auto w-full max-w-4xl px-6 py-16 sm:px-8 sm:py-20">
      <header className="border-b border-border pb-10">
        <p className="eyebrow">Aspirova</p>
        <h1 className="mt-3 font-serif text-4xl font-semibold leading-tight tracking-tight text-foreground sm:text-5xl">
          Frequently asked questions
        </h1>
      </header>

      <article className="mt-12 max-w-none">
        <section className="scroll-mt-24">
          <h2 className="font-serif text-2xl font-semibold tracking-tight text-foreground">
            Is Aspirova free?
          </h2>
          <p className="mt-4 text-base leading-7 text-muted-foreground">
            Yes. Browsing, searching and the daily digest email are free. Pro is optional and adds instant alerts, a weekly report and more room to track companies. See{" "}
            <Link className="font-medium text-foreground underline decoration-primary/40 underline-offset-4 transition-colors hover:decoration-primary" href="/pricing">
              Pricing
            </Link>.
          </p>
        </section>

        <section className="mt-12 scroll-mt-24 border-t border-border pt-10">
          <h2 className="font-serif text-2xl font-semibold tracking-tight text-foreground">
            Why do I need to sign in to apply?
          </h2>
          <p className="mt-4 text-base leading-7 text-muted-foreground">
            You can read every listing without an account. Signing in is free, and it lets you save listings, track your applications and get alerts.
          </p>
        </section>

        <section className="mt-12 scroll-mt-24 border-t border-border pt-10">
          <h2 className="font-serif text-2xl font-semibold tracking-tight text-foreground">
            Do you apply for me?
          </h2>
          <p className="mt-4 text-base leading-7 text-muted-foreground">
            No. Apply takes you to the company&apos;s or organiser&apos;s own page, and you apply there.
          </p>
        </section>

        <section className="mt-12 scroll-mt-24 border-t border-border pt-10">
          <h2 className="font-serif text-2xl font-semibold tracking-tight text-foreground">
            Where do the listings come from?
          </h2>
          <p className="mt-4 text-base leading-7 text-muted-foreground">
            Public sources such as company career pages and competition platforms. Companies don&apos;t post here directly.
          </p>
        </section>

        <section className="mt-12 scroll-mt-24 border-t border-border pt-10">
          <h2 className="font-serif text-2xl font-semibold tracking-tight text-foreground">
            How often is it updated?
          </h2>
          <p className="mt-4 text-base leading-7 text-muted-foreground">
            Every day. Listings can still close before we notice, so always check the original page.
          </p>
        </section>

        <section className="mt-12 scroll-mt-24 border-t border-border pt-10">
          <h2 className="font-serif text-2xl font-semibold tracking-tight text-foreground">
            I found a wrong or closed listing. What should I do?
          </h2>
          <p className="mt-4 text-base leading-7 text-muted-foreground">
            Use &quot;Report an issue&quot; on the listing, or the{" "}
            <Link className="font-medium text-foreground underline decoration-primary/40 underline-offset-4 transition-colors hover:decoration-primary" href="/report">
              report page
            </Link>.
          </p>
        </section>

        <section className="mt-12 scroll-mt-24 border-t border-border pt-10">
          <h2 className="font-serif text-2xl font-semibold tracking-tight text-foreground">
            Do I have to pay anyone to apply?
          </h2>
          <p className="mt-4 text-base leading-7 text-muted-foreground">
            Aspirova never charges you to apply. Be careful with anyone who asks you to pay for a job or internship, and please report it to us.
          </p>
        </section>

        <section className="mt-12 scroll-mt-24 border-t border-border pt-10">
          <h2 className="font-serif text-2xl font-semibold tracking-tight text-foreground">
            What happens to my data?
          </h2>
          <p className="mt-4 text-base leading-7 text-muted-foreground">
            See our{" "}
            <Link className="font-medium text-foreground underline decoration-primary/40 underline-offset-4 transition-colors hover:decoration-primary" href="/privacy">
              Privacy Policy
            </Link>.
          </p>
        </section>
      </article>
    </main>
  );
}
