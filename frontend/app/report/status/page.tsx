import type { Metadata } from "next";
import ReportStatusLookup from "@/components/ReportStatusLookup";

export const metadata: Metadata = {
  title: "Report status",
  robots: { index: false, follow: false },
};

export default async function ReportStatusPage({ searchParams }: {
  searchParams: Promise<{ ref?: string | string[] }>;
}) {
  const query = await searchParams;
  const reference = typeof query.ref === "string" ? query.ref : "";
  return (
    <main className="mx-auto w-full max-w-2xl px-4 py-10 sm:py-14">
      <h1 className="font-serif text-3xl font-bold text-foreground">Report status</h1>
      <p className="mt-3 text-sm leading-6 text-muted-foreground">
        Enter the receipt code from your report. We review reports within 2 days and aim to resolve them within 7 days.
        Reports are never shown with your name, and reporting never affects your account or plan.
      </p>
      <ReportStatusLookup initialReference={reference} />
    </main>
  );
}
