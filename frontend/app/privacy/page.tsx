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

      <article className="prose prose-zinc mt-12 max-w-none dark:prose-invert prose-headings:scroll-mt-24 prose-headings:font-semibold prose-a:text-foreground prose-a:decoration-primary/40 prose-a:underline-offset-4 hover:prose-a:decoration-primary">
        <h2>What we collect</h2>

        <h3>Account information</h3>
        <p>
          When you create an account, Supabase authentication handles your
          email address and display name, whether you sign in with email or a
          social sign-in method. You can also choose to add your college and
          graduation year in <Link href="/account">your account</Link>.
        </p>

        <h3>Activity in Aspirova</h3>
        <p>We store the information needed to make the service work:</p>
        <ul>
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

        <h3>Your resume</h3>
        <p>
          We store only a mathematical embedding of your resume: a
          1,536-number vector, along with its embedding model and version. We
          never store the resume text itself.
        </p>
        <p>
          If and when AI features are enabled, your resume text is sent to the
          embedding provider solely to create that vector. Aspirova does not
          retain the resume text after that process.
        </p>

        <h3>Information stored only on your device</h3>
        <p>
          Your chosen country, interest fields, recently viewed list, and
          onboarding state are stored in your browser&apos;s local storage. They
          are not sent to our servers.
        </p>

        <h3>Payments</h3>
        <p>
          Payments are handled entirely by Razorpay. Aspirova never sees or
          stores your card details. We do store your subscription status and
          subscription period.
        </p>

        <h2>Why we use this information</h2>
        <p>We use the information above to:</p>
        <ul>
          <li>Run and secure the service.</li>
          <li>Send the alerts and reports you have chosen to receive.</li>
          <li>Match opportunities to your resume embedding when applicable.</li>
          <li>Prevent abuse and keep the service reliable.</li>
          <li>Investigate and fix bugs that you report.</li>
        </ul>

        <h2>Who processes information</h2>
        <p>We use the following service providers to operate Aspirova:</p>
        <ul>
          <li>
            <strong>Supabase</strong> for our database and authentication,
            hosted in Mumbai, India.
          </li>
          <li>
            <strong>Render</strong> for our API, hosted in Singapore.
          </li>
          <li>
            <strong>Vercel</strong> for the website.
          </li>
          <li>
            <strong>Razorpay</strong> for payments.
          </li>
          <li>
            <strong>Resend</strong> for transactional email, including
            deadline alerts, daily digests, instant alerts, and weekly reports
            that are controlled by your notification preferences.
          </li>
          <li>
            <strong>Upstash</strong> for rate limiting and caching.
          </li>
          <li>
            <strong>Cloudflare R2 or Backblaze B2</strong> for encrypted
            backups.
          </li>
          <li>
            <strong>OpenAI or Anthropic</strong> only if and when AI features
            are enabled.
          </li>
        </ul>

        <h2>What we do not do</h2>
        <ul>
          <li>We do not sell personal data.</li>
          <li>We do not run advertising.</li>
          <li>We never see or store card details.</li>
          <li>We never store your resume text.</li>
        </ul>

        <h2>How long we keep information</h2>
        <p>
          We keep account information while your account exists. Raw crawl
          data is kept on a rolling retention basis. Encrypted backup copies
          are retained in our backup systems.
        </p>

        <h2>Your choices and rights</h2>
        <p>
          You can edit your profile in <Link href="/account">your account</Link>{" "}
          and turn off emails in your notification preferences. To request
          access to or deletion of your information, email <ContactEmail />.
        </p>

        <h2>Cookies and local storage</h2>
        <p>
          We use an authentication session and the device-only local storage
          preferences described above. We do not use advertising cookies or
          third-party tracking for advertising.
        </p>

        <h2>Children</h2>
        <p>
          Aspirova is intended for students and is not directed at children
          under 13.
        </p>

        <h2>Changes to this policy</h2>
        <p>
          We may update this policy when the service or our practices change.
          The latest version will always be posted here with its updated date.
        </p>

        <h2>Contact</h2>
        <p>
          For privacy questions or requests, email <ContactEmail /> or visit
          our <Link href="/contact">contact page</Link>.
        </p>
      </article>

      <p className="mt-12 text-sm text-muted-foreground">
        Last updated: {LEGAL.lastUpdated}
      </p>
    </main>
  );
}
