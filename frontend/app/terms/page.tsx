import type { Metadata } from "next";
import Link from "next/link";
import { HAS_PLACEHOLDER, LEGAL } from "@/lib/legal";

const TITLE = "Terms of Service";
const DESCRIPTION =
  "The terms that apply when you use Aspirova to discover opportunities and manage your membership.";

export const metadata: Metadata = {
  title: TITLE,
  description: DESCRIPTION,
  alternates: { canonical: "/terms" },
  openGraph: {
    title: TITLE,
    description: DESCRIPTION,
    type: "website",
    url: "/terms",
  },
};

function LaunchPlaceholder() {
  return (
    <span className="mx-1 inline-flex rounded-md border border-amber-500/40 bg-amber-500/10 px-1.5 py-0.5 text-xs font-medium leading-5 text-amber-900 dark:text-amber-200">
      [To be completed before launch]
    </span>
  );
}

function Jurisdiction() {
  if (HAS_PLACEHOLDER(LEGAL.jurisdiction)) {
    return <LaunchPlaceholder />;
  }

  return <>{LEGAL.jurisdiction}</>;
}

export default function TermsPage() {
  return (
    <main className="mx-auto w-full max-w-3xl px-4 py-10 sm:px-6 sm:py-14">
      <header className="max-w-3xl">
        <p className="eyebrow">The fine print, plainly</p>
        <h1 className="mt-3 font-serif text-4xl font-semibold leading-tight tracking-tight text-foreground sm:text-5xl">
          Terms of Service
        </h1>
        <p className="mt-4 max-w-2xl text-sm leading-6 text-muted-foreground sm:text-base sm:leading-7">
          These terms explain how Aspirova works and what each of us is responsible for when
          you use it.
        </p>
        <p className="mt-5 text-sm text-muted-foreground">
          Last updated: <time dateTime={LEGAL.lastUpdated}>{LEGAL.lastUpdated}</time>
        </p>
      </header>

      <div className="mt-10 max-w-3xl space-y-10 text-sm leading-6 text-muted-foreground sm:text-base sm:leading-7">
        <section>
          <h2 className="font-serif text-2xl font-semibold tracking-tight text-foreground">
            What Aspirova is
          </h2>
          <p className="mt-3">
            Aspirova automatically discovers opportunities published on public career pages and
            links you to the official source. Aspirova is not the employer, is not an agent, and
            does not accept applications. Companies do not post here.
          </p>
        </section>

        <section>
          <h2 className="font-serif text-2xl font-semibold tracking-tight text-foreground">
            Accuracy and availability
          </h2>
          <p className="mt-3">
            Listings are third-party content that can change or close at any time. We refresh
            daily and retire listings once a crawl shows they are gone, but a listing may still
            be out of date or already closed. Always confirm on the official page before relying
            on it. There is no guarantee of any internship, job, placement, or outcome.
          </p>
        </section>

        <section>
          <h2 className="font-serif text-2xl font-semibold tracking-tight text-foreground">
            Accounts
          </h2>
          <p className="mt-3">
            Keep your account credentials safe and give us accurate information. You may have
            one account per person, and you are responsible for activity under your account.
          </p>
        </section>

        <section>
          <h2 className="font-serif text-2xl font-semibold tracking-tight text-foreground">
            Acceptable use
          </h2>
          <p className="mt-3">Please do not:</p>
          <ul className="mt-3 list-disc space-y-2 pl-5 marker:text-primary">
            <li>Scrape Aspirova or use automated tools for bulk access.</li>
            <li>Try to break, bypass, or overload the service.</li>
            <li>Resell Aspirova&apos;s content.</li>
          </ul>
        </section>

        <section>
          <h2 className="font-serif text-2xl font-semibold tracking-tight text-foreground">
            Subscriptions and billing
          </h2>
          <p className="mt-3">
            Paid plans are billed through Razorpay in Indian rupees (INR). The plan and price
            shown at checkout apply. Cancellation and refunds are governed by our{" "}
            <Link className="font-medium text-primary underline-offset-4 hover:underline" href="/refunds">
              Refund &amp; Cancellation Policy
            </Link>
            .
          </p>
        </section>

        <section>
          <h2 className="font-serif text-2xl font-semibold tracking-tight text-foreground">
            Changes and termination
          </h2>
          <p className="mt-3">
            We may change, suspend, or stop parts of Aspirova, and we may update these Terms.
            We may also suspend or terminate an account that breaches these Terms.
          </p>
        </section>

        <section>
          <h2 className="font-serif text-2xl font-semibold tracking-tight text-foreground">
            Disclaimer and limitation of liability
          </h2>
          <p className="mt-3">
            To the extent permitted by law, Aspirova is provided &ldquo;as is&rdquo; and
            &ldquo;as available.&rdquo; We do not guarantee that the service or any listing will be
            complete, accurate, available, or suitable for your needs. To the extent permitted by
            law, Aspirova is not liable for indirect, incidental, special, consequential, or
            punitive losses arising from your use of the service.
          </p>
        </section>

        <section>
          <h2 className="font-serif text-2xl font-semibold tracking-tight text-foreground">
            Governing law
          </h2>
          <p className="mt-3">
            These Terms are governed by the laws of India. Courts at <Jurisdiction /> have
            jurisdiction over disputes, to the extent permitted by law.
          </p>
        </section>

        <section>
          <h2 className="font-serif text-2xl font-semibold tracking-tight text-foreground">
            Contact
          </h2>
          <p className="mt-3">
            Questions about these Terms? Please visit our{" "}
            <Link className="font-medium text-primary underline-offset-4 hover:underline" href="/contact">
              Contact page
            </Link>
            .
          </p>
        </section>
      </div>
    </main>
  );
}
