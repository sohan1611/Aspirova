import { destinationFacts, destinationLines } from "@/lib/applyDestination";
import type { ApplyDestination } from "@/lib/types";

export default function DestinationLabel({ facts: value, destination }: { facts?: unknown; destination?: ApplyDestination }) {
  const facts = destinationFacts(value);
  const lines = destinationLines(facts);
  if (!facts && destination?.host) {
    lines.push(destination.kind === "event_platform"
      ? `Hosted on ${destination.label || destination.host} (${destination.host})`
      : `Applies on ${destination.host}`);
    if (destination.kind === "job_board") lines.push(`Listed via ${destination.label || destination.host} — not the employer's own page`);
  }
  if (!lines.length) return null;
  return <div className="min-w-0 max-w-full space-y-1 text-xs leading-5 text-muted-foreground [overflow-wrap:anywhere]">
    {lines.map(line => <span key={line} className="block min-w-0 max-w-full">{line}</span>)}
  </div>;
}
