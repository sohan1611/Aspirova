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
        <h1 className="mt-3 font-serif text-4xl font-bold leading-tight tracking-tight text-foreground sm:text-5xl">
          Privacy Policy
        </h1>
        <p className="mt-5 max-w-2xl text-lg leading-8 text-muted-foreground">
          A clear explanation of the information Aspirova needs to run the
          service, and what we do not collect.
        </p>
      </header>

      <article className="mt-12 max-w-none">
        <h2 className="scroll-mt-24 font-serif text-2xl font-bold tracking-tight text-foreground">
          What we collect
        </h2>

        <h3 className="mt-6 scroll-mt-24 font-serif text-xl font-semibold tracking-tight text-foreground">
          Account information
        </h3>
        <p className="mt-3 text-base leading-7 text-muted-foreground">
          When you create an account, Supabase authentication handles your
          email address and display name, whether you sign in with email or a
          social sign-in method. If you sign in with Google or GitHub and the provider
          shares your name, we use it as your starting display name, and you can
          change it in your account. You can also choose to add your college and graduation year in{" "}
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
            Per-opportunity counts of views and Apply button taps. These are
            aggregate counters, not a record of your individual browsing history.
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
          If you upload a resume, we store the PDF privately so you can open or
          replace it later. It isn&apos;t public and other users can&apos;t open it.
          We only access it if you ask us to, or if the law requires it. You can
          remove it at any time from the Resume check page.
        </p>
        <p className="mt-3 text-base leading-7 text-muted-foreground">
          We also save the file name, the upload date, your resume check score
          and the skills you keep on your account. Your browser reads the PDF to
          suggest skills and work out the score.
        </p>
        <p className="mt-3 text-base leading-7 text-muted-foreground">
          If you used an earlier version of resume matching, we may also hold a
          mathematical embedding of your resume, which is a list of numbers
          rather than its text. Email us to have it removed. If AI matching is
          turned on in future, your resume text would be sent to our embedding
          provider to create that embedding, and we&apos;d update this policy first.
        </p>

        <h3 className="mt-8 scroll-mt-24 font-serif text-xl font-semibold tracking-tight text-foreground">
          Information stored on your device
        </h3>
        <p className="mt-3 text-base leading-7 text-muted-foreground">
          Your chosen country, interest fields, recently viewed list, onboarding
          state and a short-lived note of the listing you opened to apply are
          stored in your browser&apos;s local storage. If
          you&apos;re signed in, your field, interests and skills are also saved to
          your account so they follow you across devices. Your browser sends your
          interests or country to our servers only when needed to show results,
          such as the For You feed or putting listings from your country first.
          To decide the order of listings, your browser&apos;s time zone is checked
          on your device and isn&apos;t sent to us.
        </p>

        <h3 className="mt-8 scroll-mt-24 font-serif text-xl font-semibold tracking-tight text-foreground">
          Payments
        </h3>
        <p className="mt-3 text-base leading-7 text-muted-foreground">
          Payments are handled entirely by Razorpay. Aspirova never sees or
          stores your card details. We do store your subscription status and
          subscription period.
        </p>

        <h2 className="mt-12 scroll-mt-24 font-serif text-2xl font-bold tracking-tight text-foreground">
          Why we use this information
        </h2>
        <p className="mt-4 text-base leading-7 text-muted-foreground">
          We use the information above to:
        </p>
        <ul className="mt-3 list-disc space-y-2 pl-5 text-base leading-7 text-muted-foreground marker:text-primary">
          <li>Run and secure the service.</li>
          <li>Send the alerts and reports you have chosen to receive.</li>
          <li>Check your resume and suggest skills when you ask us to.</li>
          <li>Prevent abuse and keep the service reliable.</li>
          <li>Investigate and fix bugs that you report.</li>
        </ul>

        <h2 className="mt-12 scroll-mt-24 font-serif text-2xl font-bold tracking-tight text-foreground">
          Who processes information
        </h2>
        <p className="mt-4 text-base leading-7 text-muted-foreground">
          We use the following service providers to operate Aspirova:
        </p>
        <ul className="mt-3 list-disc space-y-2 pl-5 text-base leading-7 text-muted-foreground marker:text-primary">
          <li>
            <strong className="font-semibold text-foreground">DigitalOcean</strong> for our main database, hosted in Singapore.
          </li>
          <li>
            <strong className="font-semibold text-foreground">Supabase</strong> for sign-in and private resume file storage, hosted in Mumbai, India.
          </li>
          <li>
            <strong className="font-semibold text-foreground">Render</strong> for our API, hosted in Singapore.
          </li>
          <li>
            <strong className="font-semibold text-foreground">Vercel</strong> for the website, including cookieless visit statistics.
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

        <h2 className="mt-12 scroll-mt-24 font-serif text-2xl font-bold tracking-tight text-foreground">
          What we do not do
        </h2>
        <ul className="mt-4 list-disc space-y-2 pl-5 text-base leading-7 text-muted-foreground marker:text-primary">
          <li>We do not sell personal data.</li>
          <li>We do not run advertising.</li>
          <li>We never see or store card details.</li>
          <li>We never show your resume to companies or other users.</li>
        </ul>

        <h2 className="mt-12 scroll-mt-24 font-serif text-2xl font-bold tracking-tight text-foreground">
          How long we keep information
        </h2>
        <p className="mt-4 text-base leading-7 text-muted-foreground">
          We keep account information while your account exists. Raw crawl
          data is kept on a rolling retention basis. Encrypted backup copies
          are retained in our backup systems. When you remove your resume, we
          delete the stored PDF straight away. Related account records can remain
          in encrypted backups until those backups expire.
        </p>

        <h2 className="mt-12 scroll-mt-24 font-serif text-2xl font-bold tracking-tight text-foreground">
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
          access to or deletion of your information, email <ContactEmail />. You can download a copy of your account data any time from Account, under Security.
        </p>

        <h2 className="mt-12 scroll-mt-24 font-serif text-2xl font-bold tracking-tight text-foreground">
          Cookies and local storage
        </h2>
        <p className="mt-4 text-base leading-7 text-muted-foreground">
          We use an authentication session and the local storage
          preferences described above. We do not use advertising cookies or
          third-party tracking for advertising.
        </p>

        <h2 className="mt-12 scroll-mt-24 font-serif text-2xl font-bold tracking-tight text-foreground">
          Children
        </h2>
        <p className="mt-4 text-base leading-7 text-muted-foreground">
          Aspirova is intended for students and is not directed at children
          under 13.
        </p>

        <h2 className="mt-12 scroll-mt-24 font-serif text-2xl font-bold tracking-tight text-foreground">
          Changes to this policy
        </h2>
        <p className="mt-4 text-base leading-7 text-muted-foreground">
          We may update this policy when the service or our practices change.
          The latest version will always be posted here with its updated date.
        </p>

        <h2 className="mt-12 scroll-mt-24 font-serif text-2xl font-bold tracking-tight text-foreground">
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
        Last updated: {LEGAL.privacyLastUpdated}
      </p>
    </main>
  );
}
