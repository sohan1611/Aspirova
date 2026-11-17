import Link from "next/link";
import ActionSource from "@/components/ActionSource";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { actionDateLabel, nextUpItems, stageLabel } from "@/lib/actionCenter";
import type { SavedOpportunityItem } from "@/lib/types";

export default function NextUp({ items, onPlanNext }: { items: SavedOpportunityItem[]; onPlanNext: () => void }) {
  const next = nextUpItems(items);
  return (
    <section className="mt-10" aria-labelledby="next-up-heading">
      <h2 id="next-up-heading" className="font-serif text-2xl font-bold">Next up</h2>
      <p className="mt-2 text-sm text-muted-foreground">Your unfinished applications, with the soonest dates first. Stages change only when you set them.</p>
      {next.length === 0 ? (
        <div className="mt-5 rounded-lg border border-border bg-card p-5">
          <p>Nothing unfinished. Choose a saved opportunity below and mark it as planned.</p>
          <Button type="button" variant="outline" onClick={onPlanNext} className="mt-3 min-h-11">Plan from saved items</Button>
        </div>
      ) : (
        <ul className="mt-5 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {next.map(item => {
            const date = actionDateLabel(item);
            return (
              <li key={item.slug} className="min-w-0 space-y-3 rounded-lg border border-border bg-card p-5 shadow-soft">
                <Badge variant="secondary">{stageLabel(item.bookmark_status)}</Badge>
                <h3 className="break-words font-serif text-lg font-bold"><Link href={`/opportunity/${item.slug}`} className="inline-flex min-h-11 items-center rounded underline-offset-4 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">{item.title}</Link></h3>
                {date && <p className="text-sm font-medium">{date}</p>}
                {item.note && <p className="line-clamp-2 break-words text-sm text-muted-foreground">{item.note}</p>}
                <ActionSource item={item} />
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
