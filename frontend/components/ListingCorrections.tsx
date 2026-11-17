import Link from "next/link";
import type { ListingCorrection } from "@/lib/types";

export default function ListingCorrections({ corrections, duplicateOf }: {
  corrections?: ListingCorrection[];
  duplicateOf?: unknown;
}) {
  const original = typeof duplicateOf === "string" && duplicateOf ? duplicateOf : null;
  if (!corrections?.length && !original) return null;
  return (
    <aside aria-labelledby="listing-corrections-heading" className="mt-6 rounded-lg border border-border bg-secondary/50 p-4 text-sm leading-6 text-muted-foreground">
      <h2 id="listing-corrections-heading" className="font-medium text-foreground">Corrections</h2>
      {corrections?.map((correction, index) => (
        <p key={index} className="mt-2">
          Corrected <time dateTime={correction.at}>{new Date(correction.at).toLocaleDateString("en-GB", {
            day: "numeric", month: "short", year: "numeric", timeZone: "Asia/Kolkata",
          })}</time>: {correction.summary}
        </p>
      ))}
      {original && <p className="mt-2">This listing duplicates <Link href={`/opportunity/${encodeURIComponent(original)}`}
        className="text-primary underline underline-offset-4">the original listing</Link>.</p>}
    </aside>
  );
}
