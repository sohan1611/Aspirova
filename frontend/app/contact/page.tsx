import type { Metadata } from "next";
import Link from "next/link";

import { HAS_PLACEHOLDER, LEGAL } from "@/lib/legal";

export const metadata: Metadata = {
  title: "Contact | Aspirova",
  description: "How to contact Aspirova for support, billing, and privacy questions.",
};

function PlaceholderNotice() {
  return (
    <span className="inline-flex rounded bg-amber-100 px-1.5 py-0.5 text-sm font-medium text-amber-900 dark:bg-amber-950/60 dark:text-amber-200">
      [To be completed before launch]
    </span>
  );
}

function LegalValue({ value }: { value: string }) {
  return HAS_PLACEHOLDER(value) ? <PlaceholderNotice /> : <>{value}</>;
}

function ContactEmail() {
  if (HAS_PLACEHOLDER(LEGAL.contactEmail)) {
    return <PlaceholderNotice />;
  }

  return (
    <a
      className="font-medium text-foreground underline decoration-primary/40 underline-offset-4 transition-colors hover:decoration-primary"
      href={`mailto:${LEGAL.contactEmail}`}
    >
      {LEGAL.contactEmail}
    </a>
  );
}

export default function ContactPage() {
  return (
    <main className="mx-auto w-full max-w-4xl px-6 py-16 sm:px-8 sm:py-20">
      <header className="border-b border-border pb-10">
        <p className="eyebrow">Aspirova legal</p>
        <h1 className="mt-3 font-serif text-4xl font-semibold leading-tight tracking-tight text-foreground sm:text-5xl">
          Contact Aspirova
        </h1>
        <p className="mt-5 max-w-2xl text-lg leading-8 text-muted-foreground">
          Reach us for support, billing, or privacy questions.
        </p>
      </header>

      <article className="mt-12 max-w-none">
        <section className="scroll-mt-24">
          <h2 className="font-serif text-2xl font-semibold tracking-tight text-foreground">
            Get in touch
          </h2>
          <p className="mt-4 text-base leading-7 text-muted-foreground">
            For support, billing, or privacy questions, email <ContactEmail />. We
            respond within 36 hours.
          </p>
        </section>

        <section className="mt-12 scroll-mt-24 border-t border-border pt-10">
          <h2 className="font-serif text-2xl font-semibold tracking-tight text-foreground">
            Business details
          </h2>
          <p className="mt-4 text-base leading-7 text-muted-foreground">
            <strong>Entity:</strong> <LegalValue value={LEGAL.entityName} />
            <br />
            <strong>Address:</strong> <LegalValue value={LEGAL.address} />
          </p>
        </section>

        <section className="mt-12 scroll-mt-24 border-t border-border pt-10">
          <h2 className="font-serif text-2xl font-semibold tracking-tight text-foreground">
            Report a bug or broken link
          </h2>
          <p className="mt-4 text-base leading-7 text-muted-foreground">
            The fastest way to report a bug or a broken opportunity link is our{" "}
            <Link
              className="font-medium text-foreground underline decoration-primary/40 underline-offset-4 transition-colors hover:decoration-primary"
              href="/report"
            >
              report form
            </Link>. We respond within 36 hours, or fix the issue within that
            time when possible.
          </p>
        </section>
      </article>

      <p className="mt-12 text-sm text-muted-foreground">
        Last updated: {LEGAL.lastUpdated}
      </p>
    </main>
  );
}
