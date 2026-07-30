import type { Metadata } from "next";
import Link from "next/link";

import { HAS_PLACEHOLDER, LEGAL } from "@/lib/legal";

export const metadata: Metadata = {
  title: "Privacy Policy | Aspirova",
  description:
    "How Aspirova collects, uses, and protects the information needed to provide opportunity discovery and alerts.",
};

function PlaceholderNotice() {
  return (
    <span className="inline-flex rounded bg-amber-100 px-1.5 py-0.5 text-sm font-medium text-amber-900 dark:bg-amber-950/60 dark:text-amber-200">
      [To be completed before launch]
    </span>
  );
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

export default function PrivacyPage() {
  return (
    <main className="mx-auto w-full max-w-4xl px-6 py-16 sm:px-8 sm:py-20">
      <header className="border-b border-border pb-10">
        <p className="eyebrow">Aspirova legal</p>
        <h1 className="mt-3 font-serif text-4xl font-semibold leading-tight tracking-tight text-foreground sm:text-5xl">
          Privacy Policy
        </h1>
        <p className="mt-5 max-w-2xl text-lg leading-8 text-muted-foreground">
          A clear explanation of the information Aspirova needs to run the
          service, and what we do not collect.
        </p>
      </header>

      <article className="mt-12 max-w-none">
        <h2 className="scroll-mt-24 font-serif text-2xl font-semibold tracking-tight text-foreground">
          What we collect
        </h2>

        <h3 className="mt-6 scroll-mt-24 font-serif text-xl font-semibold tracking-tight text-foreground">
          Account information
        </h3>
        <p className="mt-3 text-base leading-7 text-muted-foreground">
          When you create an account, Supabase authentication handles your
          email address and display name, whether you sign in with email or a
          social sign-in method. You can also choose to add your college and graduation year in{" "}
          <Link
            className="font-medium text-foreground underline decoration-primary/40 underline-offset-4 transition-colors hover:decoration-primary"
            href="/account"
          >
            your account
          </Link>
          .
        </p>

        <h3 className="mt-8 scroll-mt-24 font-serif text-xl font-semibold tracking-tight text-foreground">
          Activity in Aspirova
        </h3>
        <p className="mt-3 text-base leading-7 text-muted-foreground">
          We store the information needed to make the service work:
        </p>
        <ul className="mt-3 list-disc space-y-2 pl-5 text-base leading-7 text-muted-foreground marker:text-primary">
          <li>Your bookmarks and their application stage.</li>
          <li>Your notification preferences.</li>
          <li>
            Per-opportunity view counts. These are aggregate counters, not a
            record of your individual browsing history.
          </li>
          <li>
            Bug reports you send us, including the message, an optional
            contact email, and the page or opportunity the report came from.
          </li>
        </ul>

        <h3 className="mt-8 scroll-mt-24 font-serif text-xl font-semibold tracking-tight text-foreground">
          Your resume
        </h3>
        <p className="mt-3 text-base leading-7 text-muted-foreground">
          We store only a mathematical embedding of your resume: a
          1,536-number vector, along with its embedding model and version. We
          never store the resume text itself.
        </p>
        <p className="mt-3 text-base leading-7 text-muted-foreground">
          If and when AI features are enabled, your resume text is sent to the
          embedding provider solely to create that vector. Aspirova does not
          retain the resume text after that process.
        </p>

        <h3 className="mt-8 scroll-mt-24 font-serif text-xl font-semibold tracking-tight text-foreground">
          Information stored only on your device
        </h3>
        <p className="mt-3 text-base leading-7 text-muted-foreground">
          Your chosen country, interest fields, recently viewed list, and
          onboarding state are stored in your browser&apos;s local storage. They
          are not sent to our servers.
        </p>

        <h3 className="mt-8 scroll-mt-24 font-serif text-xl font-semibold tracking-tight text-foreground">
          Payments
        </h3>
        <p className="mt-3 text-base leading-7 text-muted-foreground">
          Payments are handled entirely by Razorpay. Aspirova never sees or
          stores your card details. We do store your subscription status and
          subscription period.
        </p>

        <h2 className="mt-12 scroll-mt-24 font-serif text-2xl font-semibold tracking-tight text-foreground">
          Why we use this information
        </h2>
        <p className="mt-4 text-base leading-7 text-muted-foreground">
          We use the information above to:
        </p>
        <ul className="mt-3 list-disc space-y-2 pl-5 text-base leading-7 text-muted-foreground marker:text-primary">
          <li>Run and secure the service.</li>
          <li>Send the alerts and reports you have chosen to receive.</li>
          <li>Match opportunities to your resume embedding when applicable.</li>
          <li>Prevent abuse and keep the service reliable.</li>
          <li>Investigate and fix bugs that you report.</li>
        </ul>

        <h2 className="mt-12 scroll-mt-24 font-serif text-2xl font-semibold tracking-tight text-foreground">
          Who processes information
        </h2>
        <p className="mt-4 text-base leading-7 text-muted-foreground">
          We use the following service providers to operate Aspirova:
        </p>
        <ul className="mt-3 list-disc space-y-2 pl-5 text-base leading-7 text-muted-foreground marker:text-primary">
          <li>
            <strong className="font-semibold text-foreground">Supabase</strong> for our database and authentication,
            hosted in Mumbai, India.
          </li>
          <li>
            <strong className="font-semibold text-foreground">Render</strong> for our API, hosted in Singapore.
          </li>
          <li>
            <strong className="font-semibold text-foreground">Vercel</strong> for the website.
          </li>
          <li>
            <strong className="font-semibold text-foreground">Razorpay</strong> for payments.
          </li>
          <li>
            <strong className="font-semibold text-foreground">Resend</strong> for transactional email, including
            deadline alerts, daily digests, instant alerts, and weekly reports
            that are controlled by your notification preferences.
          </li>
          <li>
            <strong className="font-semibold text-foreground">Upstash</strong> for rate limiting and caching.
          </li>
          <li>
            <strong className="font-semibold text-foreground">Cloudflare R2 or Backblaze B2</strong> for encrypted
            backups.
          </li>
          <li>
            <strong className="font-semibold text-foreground">OpenAI or Anthropic</strong> only if and when AI features
            are enabled.
          </li>
        </ul>

        <h2 className="mt-12 scroll-mt-24 font-serif text-2xl font-semibold tracking-tight text-foreground">
          What we do not do
        </h2>
        <ul className="mt-4 list-disc space-y-2 pl-5 text-base leading-7 text-muted-foreground marker:text-primary">
          <li>We do not sell personal data.</li>
          <li>We do not run advertising.</li>
          <li>We never see or store card details.</li>
          <li>We never store your resume text.</li>
        </ul>

        <h2 className="mt-12 scroll-mt-24 font-serif text-2xl font-semibold tracking-tight text-foreground">
          How long we keep information
        </h2>
        <p className="mt-4 text-base leading-7 text-muted-foreground">
          We keep account information while your account exists. Raw crawl
          data is kept on a rolling retention basis. Encrypted backup copies
          are retained in our backup systems.
        </p>

        <h2 className="mt-12 scroll-mt-24 font-serif text-2xl font-semibold tracking-tight text-foreground">
          Your choices and rights
        </h2>
        <p className="mt-4 text-base leading-7 text-muted-foreground">
          You can edit your profile in{" "}
          <Link
            className="font-medium text-foreground underline decoration-primary/40 underline-offset-4 transition-colors hover:decoration-primary"
            href="/account"
          >
            your account
          </Link>{" "}
          and turn off emails in your notification preferences. To request
          access to or deletion of your information, email <ContactEmail />.
        </p>

        <h2 className="mt-12 scroll-mt-24 font-serif text-2xl font-semibold tracking-tight text-foreground">
          Cookies and local storage
        </h2>
        <p className="mt-4 text-base leading-7 text-muted-foreground">
          We use an authentication session and the device-only local storage
          preferences described above. We do not use advertising cookies or
          third-party tracking for advertising.
        </p>

        <h2 className="mt-12 scroll-mt-24 font-serif text-2xl font-semibold tracking-tight text-foreground">
          Children
        </h2>
        <p className="mt-4 text-base leading-7 text-muted-foreground">
          Aspirova is intended for students and is not directed at children
          under 13.
        </p>

        <h2 className="mt-12 scroll-mt-24 font-serif text-2xl font-semibold tracking-tight text-foreground">
          Changes to this policy
        </h2>
        <p className="mt-4 text-base leading-7 text-muted-foreground">
          We may update this policy when the service or our practices change.
          The latest version will always be posted here with its updated date.
        </p>

        <h2 className="mt-12 scroll-mt-24 font-serif text-2xl font-semibold tracking-tight text-foreground">
          Contact
        </h2>
        <p className="mt-4 text-base leading-7 text-muted-foreground">
          For privacy questions or requests, email <ContactEmail /> or visit
          our{" "}
          <Link
            className="font-medium text-foreground underline decoration-primary/40 underline-offset-4 transition-colors hover:decoration-primary"
            href="/contact"
          >
            contact page
          </Link>
          .
        </p>
      </article>

      <p className="mt-12 text-sm text-muted-foreground">
        Last updated: {LEGAL.lastUpdated}
      </p>
    </main>
  );
}
