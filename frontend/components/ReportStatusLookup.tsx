"use client";

import Link from "next/link";
import { type FormEvent, useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { getReportStatus } from "@/lib/api";
import type { ReportStatus } from "@/lib/types";

export default function ReportStatusLookup({ initialReference }: { initialReference: string }) {
  const [reference, setReference] = useState(initialReference);
  const [report, setReport] = useState<ReportStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!initialReference) return;
    let active = true;
    getReportStatus(initialReference).then((value) => {
      if (active) setReport(value);
    }).catch((cause: unknown) => {
      if (active) setError(cause instanceof Error ? cause.message : "Could not check report.");
    });
    return () => { active = false; };
  }, [initialReference]);

  async function lookup(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setReport(null);
    setLoading(true);
    try {
      setReport(await getReportStatus(reference));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not check report.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="mt-6 grid gap-6">
      <form onSubmit={lookup} className="grid gap-3 rounded-lg border border-border bg-card p-5">
        <Label htmlFor="report-reference">Report receipt</Label>
        <Input id="report-reference" value={reference} onChange={(event) => setReference(event.target.value)}
          placeholder="R-XXXXXX" maxLength={8} required autoCapitalize="characters" autoComplete="off" />
        <Button type="submit" disabled={loading}>{loading ? "Checking…" : "Check status"}</Button>
      </form>
      {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
      {report && (
        <section aria-label="Report outcome" aria-live="polite" className="rounded-lg border border-border bg-card p-5 text-sm leading-6">
          <h2 className="font-serif text-xl font-bold">{report.reference}</h2>
          <dl className="mt-3 grid gap-2">
            <div><dt className="font-medium">Status</dt><dd>{report.status}</dd></div>
            <div><dt className="font-medium">Category</dt><dd>{report.category.replaceAll("_", " ")}</dd></div>
            {([
              ["Received", report.created_at], ["Reviewed", report.triaged_at], ["Resolved", report.resolved_at],
            ] as const).map(([label, at]) => at && <div key={label}><dt className="font-medium">{label}</dt>
              <dd><time dateTime={at}>{new Date(at).toLocaleString("en-IN", { timeZone: "Asia/Kolkata" })} IST</time></dd></div>)}
            {report.resolution && <div><dt className="font-medium">Resolution</dt><dd>{report.resolution.replaceAll("_", " ")}</dd></div>}
          </dl>
          {report.resolution_note && <p className="mt-4 whitespace-pre-wrap break-words">{report.resolution_note}</p>}
          {report.listing_slug && <Link href={`/opportunity/${encodeURIComponent(report.listing_slug)}`}
            className="mt-4 inline-flex min-h-11 items-center text-primary underline underline-offset-4">{report.listing_title ?? "View listing"}</Link>}
        </section>
      )}
    </div>
  );
}
