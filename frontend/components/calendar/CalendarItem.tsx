import { ArrowUpRight } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { categoryColour, categoryLabel, howToApply, keyDatesText } from "@/lib/hiringCalendar";
import type { CalendarItem } from "@/lib/hiringCalendar";
import { safeExternalUrl } from "@/lib/safeUrl";

export const CALENDAR_FOCUS = "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2";
export const CALENDAR_INPUT = `min-h-11 min-w-0 rounded-md border border-input bg-card px-3 text-sm ${CALENDAR_FOCUS}`;

export function CategoryBadge({ item }: { item: CalendarItem }) {
  return <Badge variant="outline" className="max-w-full gap-1.5 whitespace-normal text-left font-normal">
    <span className="size-2 shrink-0 rounded-full" style={{ backgroundColor: categoryColour(item.programme.category) }} aria-hidden="true" />
    {categoryLabel(item.programme.category, item.programme.category_label)}
  </Badge>;
}

export function statusClass(item: CalendarItem): string {
  return item.is_open_now ? "border-success/30 bg-success/10 text-success"
    : item.edition.status === "closed" ? "border-border bg-muted text-muted-foreground"
      : item.edition.basis === "tentative" ? "border-dashed border-border bg-muted/40 text-muted-foreground"
        : "border-primary/25 bg-accent text-primary";
}

export function StatusBadge({ item }: { item: CalendarItem }) {
  return <Badge className={statusClass(item)}>{item.is_open_now ? "● Open now" : item.edition.status === "closed" ? "Closed" : item.edition.basis === "tentative" ? "Tentative" : "Official"}</Badge>;
}

export function OfficialLink({ item }: { item: CalendarItem }) {
  const url = safeExternalUrl(item.programme.url);
  if (!url) return <p className="text-xs text-muted-foreground">Application link awaiting confirmation. See how to apply.</p>;
  return <Button asChild variant={item.is_open_now ? "default" : "outline"} className="min-h-11">
    <a href={url} target="_blank" rel="noopener noreferrer">{item.is_open_now ? "Apply now →" : "Official site"}<ArrowUpRight aria-hidden="true" /></a>
  </Button>;
}

export function HowToApply({ item }: { item: CalendarItem }) {
  return <ol className="list-decimal space-y-2 pl-5 text-sm leading-6 text-muted-foreground">
    {howToApply(item, !!safeExternalUrl(item.programme.url)).map((step, index) => <li key={index} className="whitespace-pre-wrap break-words">{step}</li>)}
  </ol>;
}

export function ItemRow({ item, dateChip, text, onSelect }: {
  item: CalendarItem; dateChip?: string; text?: string; onSelect: (item: CalendarItem) => void;
}) {
  return <button type="button" onClick={() => onSelect(item)} className={`flex min-h-11 w-full min-w-0 items-start gap-3 rounded-lg border border-border bg-card p-3 text-left hover:border-primary/30 hover:bg-accent/30 sm:gap-4 sm:p-4 ${CALENDAR_FOCUS}`}>
    {dateChip && <span className="mt-0.5 flex min-h-11 w-16 shrink-0 items-center justify-center rounded-md bg-secondary px-1 py-2 text-center text-sm font-semibold">{dateChip}</span>}
    <span className="block min-w-0 flex-1">
      <span className="flex flex-wrap items-start justify-between gap-2">
        <span className="min-w-0 break-words font-semibold leading-6">{item.programme.name}</span>
        <StatusBadge item={item} />
      </span>
      <span className="mt-0.5 block break-words text-xs leading-5 text-muted-foreground">{item.programme.organiser}</span>
      <span className="mt-1.5 block break-words text-sm leading-6">{text ?? keyDatesText(item)}</span>
      <span className="mt-2 block"><CategoryBadge item={item} /></span>
    </span>
  </button>;
}
