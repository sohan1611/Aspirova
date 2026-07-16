import type { Metadata } from "next";
import Link from "next/link";
import { HAS_PLACEHOLDER, LEGAL } from "@/lib/legal";

const TITLE = "Refund & Cancellation Policy";
const DESCRIPTION =
  "How to cancel an Aspirova subscription and how payments already made are handled.";

export const metadata: Metadata = {
  title: TITLE,
  description: DESCRIPTION,
  alternates: { canonical: "/refunds" },
  openGraph: {
    title: TITLE,
    description: DESCRIPTION,
    type: "website",
    url: "/refunds",
  },
};

function LaunchPlaceholder() {
  return (
    <span className="mx-1 inline-flex rounded-md border border-amber-500/40 bg-amber-500/10 px-1.5 py-0.5 text-xs font-medium leading-5 text-amber-900 dark:text-amber-200">
      [To be completed before launch]
    </span>
  );
}

function ContactEmail() {
  if (HAS_PLACEHOLDER(LEGAL.contactEmail)) {
    return <LaunchPlaceholder />;
  }

  return (
    <a className="font-medium text-primary underline-offset-4 hover:underline" href={`mailto:${LEGAL.contactEmail}`}>
      {LEGAL.contactEmail}
    </a>
  );
}

export default function RefundsPage() {
  return (
    <main className="mx-auto w-full max-w-3xl px-4 py-10 sm:px-6 sm:py-14">
      <header className="max-w-3xl">
        <p className="eyebrow">Billing, plainly</p>
        <h1 className="mt-3 font-serif text-4xl font-semibold leading-tight tracking-tight text-foreground sm:text-5xl">
          Refund &amp; Cancellation Policy
        </h1>
        <p className="mt-4 max-w-2xl text-sm leading-6 text-muted-foreground sm:text-base sm:leading-7">
          Please read this before you subscribe to an Aspirova paid plan.
        </p>
        <p className="mt-5 text-sm text-muted-foreground">
          Last updated: <time dateTime={LEGAL.lastUpdated}>{LEGAL.lastUpdated}</time>
        </p>
      </header>

      <section className="mt-10 max-w-3xl rounded-xl border border-amber-500/40 bg-amber-500/10 p-5 shadow-soft sm:p-6">
        <h2 className="font-serif text-2xl font-semibold tracking-tight text-foreground">
          Payments already made are not refunded
        </h2>
        <p className="mt-3 text-sm font-medium leading-6 text-foreground sm:text-base sm:leading-7">
          Payments already made are not refunded, including partial periods.
        </p>
      </section>

      <div className="mt-10 max-w-3xl space-y-10 text-sm leading-6 text-muted-foreground sm:text-base sm:leading-7">
        <section>
          <h2 className="font-serif text-2xl font-semibold tracking-tight text-foreground">
            Cancel any time
          </h2>
          <p className="mt-3">
            You can cancel your subscription at any time. Cancelling stops all future charges;
            your plan stays active until the end of the period you have already paid for.
          </p>
        </section>

        <section>
          <h2 className="font-serif text-2xl font-semibold tracking-tight text-foreground">
            How to cancel
          </h2>
          <p className="mt-3">
            Cancel your subscription from your{" "}
            <Link className="font-medium text-primary underline-offset-4 hover:underline" href="/account">
              Account page
            </Link>
            .
          </p>
        </section>

        <section>
          <h2 className="font-serif text-2xl font-semibold tracking-tight text-foreground">
            If something went wrong
          </h2>
          <p className="mt-3">
            If you were charged in error or something went wrong, contact <ContactEmail /> and we
            will look into it.
          </p>
        </section>

        <section>
          <h2 className="font-serif text-2xl font-semibold tracking-tight text-foreground">
            Prices and payments
          </h2>
          <p className="mt-3">Prices are in INR and are billed through Razorpay.</p>
        </section>
      </div>
    </main>
  );
}
