"use client";

import { useEffect, useId, useRef, useState, type FormEvent } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { actionDateLabel, BOOKMARK_STAGES } from "@/lib/actionCenter";
import type { BookmarkStage, BookmarkUpdate, SavedOpportunityItem } from "@/lib/types";

export default function BookmarkControls({ item, pending, onChange }: {
  item: SavedOpportunityItem;
  pending: boolean;
  onChange: (update: BookmarkUpdate) => Promise<boolean>;
}) {
  const id = useId();
  const toggleRef = useRef<HTMLButtonElement>(null);
  const dateRef = useRef<HTMLInputElement>(null);
  const focusTarget = useRef<"date" | "toggle" | null>(null);
  const [expanded, setExpanded] = useState(false);
  const [note, setNote] = useState(item.note ?? "");
  const [date, setDate] = useState(item.status_date ?? "");
  const [announcement, setAnnouncement] = useState("");
  const hasDetails = Boolean(item.status_date || item.note);
  const summary = [item.status_date ? actionDateLabel(item) : null, item.note?.trim()]
    .filter(Boolean).join(" · ");

  useEffect(() => {
    // Wait for the pending write to release disabled controls before focusing.
    if (pending) return;
    if (focusTarget.current === "date" && expanded) {
      dateRef.current?.focus();
      focusTarget.current = null;
    } else if (focusTarget.current === "toggle" && !expanded) {
      toggleRef.current?.focus();
      focusTarget.current = null;
    }
  }, [expanded, pending]);

  function toggleEditor() {
    if (expanded) {
      focusTarget.current = "toggle";
    } else {
      setNote(item.note ?? "");
      setDate(item.status_date ?? "");
      focusTarget.current = "date";
    }
    setExpanded(!expanded);
  }

  async function changeStage(status: BookmarkStage) {
    setAnnouncement("");
    const saved = await onChange({ status });
    setAnnouncement(saved ? "Stage saved." : "Couldn't save changes. Previous values restored.");
  }

  async function saveDetails(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setAnnouncement("");
    if (await onChange({ note: note || null, status_date: date || null })) {
      setAnnouncement("Date and note saved.");
      focusTarget.current = "toggle";
      setExpanded(false);
    } else {
      setNote(item.note ?? "");
      setDate(item.status_date ?? "");
      setAnnouncement("Couldn't save changes. Previous values restored.");
    }
  }
  return (
    <div role="group" aria-label={`Tracking for ${item.title}`} className="min-w-0 border-t border-border bg-secondary/20 px-4 py-2">
      <div className="flex min-w-0 items-center gap-3">
        <label htmlFor={`${id}-stage`} className="shrink-0 text-sm font-medium">Stage <span className="sr-only">for {item.title}</span></label>
        <select id={`${id}-stage`} value={item.bookmark_status} disabled={pending} aria-busy={pending}
          onChange={event => void changeStage(event.target.value as BookmarkStage)}
          className="min-h-11 w-full min-w-0 flex-1 rounded-md border border-input bg-background px-3 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50">
          {BOOKMARK_STAGES.map(stage => <option key={stage.value} value={stage.value}>{stage.label}</option>)}
        </select>
      </div>
      <div className="flex min-w-0 items-center justify-between gap-2">
        {summary && <p className="line-clamp-2 min-w-0 break-words text-sm text-muted-foreground">{summary}</p>}
        <Button ref={toggleRef} type="button" variant="ghost" disabled={pending}
          aria-expanded={expanded} aria-controls={`${id}-details`}
          aria-label={`${expanded ? "Close date and note editor" : hasDetails ? "Edit date or note" : "Add date or note"} for ${item.title}`}
          onClick={toggleEditor} className="min-h-11 min-w-11 shrink-0 px-2 text-sm sm:min-w-11">
          {expanded ? "Close editor" : hasDetails ? "Edit" : "Add date or note"}
        </Button>
      </div>
      <div id={`${id}-details`} hidden={!expanded}>
        {expanded && (
          <form onSubmit={saveDetails} aria-label={`Date and note for ${item.title}`} aria-busy={pending} className="space-y-3 border-t border-border py-3">
            <label htmlFor={`${id}-date`} className="block text-sm font-medium">Status date (optional)</label>
            <div className="flex min-w-0 gap-2">
              <Input ref={dateRef} id={`${id}-date`} type="date" value={date} disabled={pending} onChange={event => setDate(event.target.value)} className="min-h-11 min-w-0 flex-1" />
              <Button type="button" variant="outline" disabled={pending || !date} onClick={() => setDate("")} className="min-h-11" aria-label={`Clear date for ${item.title}`}>Clear</Button>
            </div>
            <label htmlFor={`${id}-note`} className="block text-sm font-medium">Note (optional)</label>
            <Textarea id={`${id}-note`} value={note} maxLength={1000} rows={3} disabled={pending} onChange={event => setNote(event.target.value)} aria-describedby={`${id}-limit`} className="min-h-24 resize-none break-words" />
            <p id={`${id}-limit`} className="text-xs text-muted-foreground">Up to 1,000 characters. Date and note refer to your current stage.</p>
            <div className="flex min-w-0 flex-wrap gap-2">
              <Button type="submit" disabled={pending} className="min-h-11">Save date and note</Button>
              <Button type="button" variant="outline" disabled={pending || !note} onClick={() => setNote("")} className="min-h-11" aria-label={`Clear note for ${item.title}`}>Clear note</Button>
            </div>
          </form>
        )}
      </div>
      <p role="status" aria-live="polite" className="sr-only">{pending ? "Saving changes…" : announcement}</p>
    </div>
  );
}
