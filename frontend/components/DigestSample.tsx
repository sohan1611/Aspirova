"use client";

import { useEffect, useState } from "react";
import { categoryCounts, getDigestSample, type DigestSample as Sample } from "@/lib/digest";

// The API sends the IST calendar date as YYYY-MM-DD; format it as that same day,
// never shifted by the viewer's timezone.
const SAMPLE_DATE = new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short", timeZone: "UTC" });

function sampleDate(value: string): string {
  const parsed = new Date(`${value}T00:00:00Z`);
  return Number.isNaN(parsed.getTime()) ? value : SAMPLE_DATE.format(parsed);
}

// Shown inside the sign-in dialog, so items are plain text: a click must not take
// the visitor away from the listing they came to apply for.
export function DigestSampleContent({ sample }: { sample: Sample | null }) {
  if (!sample || sample.empty || !sample.items.length) return null;
  return (
    <aside aria-label="Example from today's digest" className="mt-4 rounded-lg border border-border p-3 text-sm">
      <p className="font-medium">Example from today&apos;s digest</p>
      <p className="mt-1 text-xs text-muted-foreground"><time dateTime={sample.date}>{sampleDate(sample.date)}</time> · {categoryCounts(sample.counts_by_category)}</p>
      <ul className="mt-2 list-disc space-y-1 pl-5">
        {sample.items.slice(0, 6).map((item) => (
          <li key={item.slug}>{item.title}{item.company_name ? <span className="text-muted-foreground"> · {item.company_name}</span> : null}</li>
        ))}
      </ul>
      <p className="mt-2 text-xs text-muted-foreground">Sign in above to get picks like these by email each day.</p>
    </aside>
  );
}

export default function DigestSample() {
  const [sample, setSample] = useState<Sample | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    void getDigestSample(controller.signal).then((value) => { if (!controller.signal.aborted) setSample(value); });
    return () => controller.abort();
  }, []);
  return <DigestSampleContent sample={sample} />;
}
