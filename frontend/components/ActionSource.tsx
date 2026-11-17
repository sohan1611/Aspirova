import ApplyLink from "@/components/ApplyLink";
import { actionSource } from "@/lib/actionCenter";
import { safeExternalUrl } from "@/lib/safeUrl";
import type { SavedOpportunityItem } from "@/lib/types";

export default function ActionSource({ item }: { item: SavedOpportunityItem }) {
  const source = actionSource(item);
  const warningSource = source.kind === "withdrawn" ? safeExternalUrl(item.safety?.source_url) : null;
  const linkClass = "inline-flex min-h-11 max-w-full items-center rounded px-2 text-sm font-medium text-primary underline underline-offset-4 [overflow-wrap:anywhere] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring";
  return (
    <div className="min-w-0 space-y-1">
      {source.warning && <p className={source.kind === "withdrawn" ? "font-medium text-destructive" : "font-medium text-foreground"}>{source.warning}</p>}
      {source.kind === "withdrawn" && item.safety?.note && <p className="break-words text-sm">{item.safety.note}</p>}
      {source.href && (source.kind === "open" ? (
        <ApplyLink slug={item.slug} href={source.href} variant="outline" className="min-h-11 h-auto max-w-full whitespace-normal break-words text-left">{source.buttonLabel}</ApplyLink>
      ) : (
        <a href={source.href} target="_blank" rel="noopener noreferrer" className={linkClass}>{source.buttonLabel}</a>
      ))}
      {warningSource && <a href={warningSource} target="_blank" rel="noopener noreferrer" className={linkClass}>Read the source of this warning</a>}
      <p className="break-words text-xs leading-5 text-muted-foreground">{source.caption}</p>
    </div>
  );
}
