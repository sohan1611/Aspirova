import type { Metadata } from "next";
import { ReportIssueForm } from "@/components/ReportIssueDialog";

export const metadata: Metadata = {
  title: "Report a problem",
  description: "Report a dead link, incorrect information, or a problem with Aspirova.",
  alternates: { canonical: "/report" },
};

export default function ReportPage() {
  return (
    <main className="mx-auto w-full max-w-3xl px-4 py-10 sm:py-14">
      <header className="max-w-2xl">
        <p className="eyebrow">Feedback</p>
        <h1 className="mt-3 font-serif text-4xl font-semibold leading-tight tracking-tight text-foreground sm:text-5xl">
          Report a problem
        </h1>
        <p className="mt-4 text-sm leading-6 text-muted-foreground sm:text-base sm:leading-7">
          Found a dead link, incorrect information, or something that isn&apos;t working? Reports
          go straight to the founder so we can fix them quickly.
        </p>
      </header>

      <section
        className="mt-10 max-w-2xl rounded-xl border border-border bg-card p-6 shadow-soft sm:p-7"
        aria-label="Report a problem"
      >
        <ReportIssueForm />
      </section>
    </main>
  );
}
