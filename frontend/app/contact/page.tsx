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

      <article className="prose prose-zinc mt-12 max-w-none dark:prose-invert prose-headings:scroll-mt-24 prose-headings:font-semibold prose-a:text-foreground prose-a:decoration-primary/40 prose-a:underline-offset-4 hover:prose-a:decoration-primary">
        <h2>Get in touch</h2>
        <p>
          For support, billing, or privacy questions, email <ContactEmail />.
          We usually reply within a few working days.
        </p>

        <h2>Business details</h2>
        <p>
          <strong>Entity:</strong> <LegalValue value={LEGAL.entityName} />
          <br />
          <strong>Address:</strong> <LegalValue value={LEGAL.address} />
        </p>

        <h2>Report a bug or broken link</h2>
        <p>
          The fastest way to report a bug or a broken opportunity link is our{" "}
          <Link href="/report">report form</Link>.
        </p>
      </article>

      <p className="mt-12 text-sm text-muted-foreground">
        Last updated: {LEGAL.lastUpdated}
      </p>
    </main>
  );
}
