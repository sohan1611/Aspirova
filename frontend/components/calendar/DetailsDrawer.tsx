"use client";

import { useState } from "react";
import { Copy, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Sheet, SheetClose, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { buildIcs, googleCalendarUrl } from "@/lib/calendar";
import { calendarParams, dateLabel, officialDeadline, registrationEvents } from "@/lib/hiringCalendar";
import type { CalendarItem, CalendarQuery } from "@/lib/hiringCalendar";
import { safeExternalUrl } from "@/lib/safeUrl";
import { CALENDAR_INPUT, CategoryBadge, HowToApply, OfficialLink, StatusBadge } from "./CalendarItem";

function CalendarActions({ item }: { item: CalendarItem }) {
  const deadline = officialDeadline(item);
  if (!deadline) return null;
  const event = {
    slug: item.id.replace(/:/g, "-"), title: item.programme.name, deadline,
    url: safeExternalUrl(item.programme.url) ?? "", estimated: false
  };
  const google = safeExternalUrl(googleCalendarUrl(event));
  function download() {
    const blob = new Blob([buildIcs(event)], { type: "text/calendar;charset=utf-8" });
    const objectUrl = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = objectUrl;
    link.download = `${event.slug}-deadline.ics`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    window.setTimeout(() => URL.revokeObjectURL(objectUrl), 1000);
  }
  return <section className="space-y-2" aria-label="Add official deadline to calendar">
    <h3 className="text-sm font-semibold">Add deadline to calendar</h3>
    <div className="flex flex-wrap gap-2">
      {google && <Button variant="outline" className="min-h-11" asChild><a href={google} target="_blank" rel="noopener noreferrer">Google Calendar</a></Button>}
      <Button variant="outline" className="min-h-11" onClick={download}>Download .ics</Button>
    </div>
  </section>;
}

function KeyDates({ item }: { item: CalendarItem }) {
  const events = registrationEvents(item);
  const rows = [
    { label: "Registration opens", kind: "opens", value: "" },
    { label: "Registration closes", kind: "closes", value: item.metadata.deadline_rolling ? "Rolling · apply early" : "" },
    { label: "Event or programme dates", kind: "event", value: item.metadata.event_window?.trim() || item.metadata.duration_start?.trim() || "" },
  ];
  return <section aria-labelledby="calendar-key-dates-heading">
    <h3 id="calendar-key-dates-heading" className="mb-3 text-sm font-semibold">Key dates</h3>
    <table className="w-full table-fixed text-left text-sm">
      <caption className="sr-only">Registration and programme dates, with their source and precision</caption>
      <tbody>{rows.map(({ label, kind, value }) => {
        const event = events.find((entry) => entry.kind === kind);
        const text = value || (event ? `${event.label} ${event.from.slice(0, 4)}${event.to.slice(0, 4) !== event.from.slice(0, 4) ? `–${event.to.slice(0, 4)}` : ""}` : "Awaiting published dates");
        return <tr key={kind} className="border-b border-border align-top">
          <th scope="row" className="w-2/5 py-3 pr-3 font-medium">{label}</th>
          <td className="break-words py-3 leading-6"><span className="whitespace-pre-wrap">{text}</span>
            {(value || event) && <span className={`mt-1 block text-xs ${item.edition.basis === "tentative" ? "text-muted-foreground" : "text-primary"}`}>{item.edition.basis}{event ? ` · ${event.precision} precision` : ""}</span>}
          </td>
        </tr>;
      })}</tbody>
    </table>
    <p className="mt-3 text-xs text-muted-foreground">{item.verified_at ? `Checked ${dateLabel(item.verified_at)}` : "Awaiting a current-cycle check"}</p>
  </section>;
}

export default function DetailsDrawer({ item, query, recurringRule, loading, onClose, onRestoreFocus }: {
  item: CalendarItem | null; query: CalendarQuery; recurringRule?: string; loading: boolean; onClose: () => void; onRestoreFocus: () => void;
}) {
  const [copyStatus, setCopyStatus] = useState("");
  const [copyUrl, setCopyUrl] = useState("");
  async function copyLink() {
    const url = new URL("/calendar", window.location.origin);
    url.search = calendarParams(query).toString();
    try {
      await navigator.clipboard.writeText(url.toString());
      setCopyStatus("Link copied");
    } catch {
      setCopyUrl(url.toString());
      setCopyStatus("Select and copy the link below");
    }
  }
  return <Sheet open={!!query.item} onOpenChange={(open) => { if (!open) onClose(); }}>
    <SheetContent side="bottom" showCloseButton={false} onCloseAutoFocus={(event) => { event.preventDefault(); onRestoreFocus(); }}
      className="inset-x-0 bottom-0 max-h-[92dvh] w-full gap-0 rounded-t-xl sm:inset-x-auto sm:inset-y-0 sm:right-0 sm:h-dvh sm:max-h-none sm:w-[min(34rem,100vw)] sm:rounded-none sm:border-t-0 sm:border-l">
      <SheetHeader className="shrink-0 border-b border-border p-5 pr-16 text-left">
        <SheetTitle className="break-words font-serif text-xl leading-7">{item?.programme.name ?? (loading ? "Loading programme…" : "Programme unavailable")}</SheetTitle>
        <SheetDescription>{item ? `${item.programme.organiser} · ${item.edition.year} cycle` : "Registration dates and application details"}</SheetDescription>
      </SheetHeader>
      <SheetClose asChild><Button variant="ghost" className="absolute top-3 right-3 size-11 min-h-11 min-w-11 p-0" aria-label="Close programme details"><X aria-hidden="true" /></Button></SheetClose>
      <div className="min-h-0 overflow-y-auto overscroll-contain p-5 pb-[max(1.25rem,env(safe-area-inset-bottom))]">
        {item ? <div className="space-y-6">
          <div className="flex flex-wrap items-center gap-2"><CategoryBadge item={item} /><StatusBadge item={item} /></div>
          <KeyDates item={item} />
          {recurringRule && <section className="space-y-2"><h3 className="text-sm font-semibold">Recurring registration</h3><p className="text-sm leading-6 text-muted-foreground">{recurringRule}</p></section>}
          <div className="flex flex-wrap items-center gap-2"><OfficialLink item={item} /><Button variant="outline" className="min-h-11" onClick={copyLink}><Copy aria-hidden="true" />Copy link</Button></div>
          {copyStatus && <p role="status" className="text-xs text-muted-foreground">{copyStatus}</p>}
          {copyUrl && <input aria-label="Programme share link" readOnly value={copyUrl} onFocus={(event) => event.target.select()} className={`${CALENDAR_INPUT} w-full`} />}
          <section className="space-y-2"><h3 className="text-sm font-semibold">How to apply</h3><HowToApply item={item} /></section>
          {[
            ["Eligibility", item.programme.eligibility || "Review the eligibility in the current official notice."],
            ["Selection process", item.metadata.hiring_mode || "Refer to the current official notice for the selection process."],
            ["Preparation tip", item.metadata.prep_tip],
            ["Career linkage", item.metadata.career_linkage],
            ["Verification notes", item.metadata.verification_note],
          ].map(([heading, text]) => text && <section key={heading} className="space-y-2"><h3 className="text-sm font-semibold">{heading}</h3><p className="whitespace-pre-wrap break-words text-sm leading-6 text-muted-foreground">{text}</p></section>)}
          {item.programme.geography && <p className="text-xs text-muted-foreground">{item.programme.geography}</p>}
          {item.metadata.source_cycle_year != null && item.metadata.source_cycle_year !== item.edition.year && <p className="text-xs text-muted-foreground">Historical guidance from the {item.metadata.source_cycle_year} source cycle.</p>}
          <CalendarActions item={item} />
        </div> : <p className="text-sm leading-6 text-muted-foreground" role="status">{loading ? "Loading this registration window…" : "This item is unavailable in the selected period. Close the drawer to browse the calendar."}</p>}
      </div>
    </SheetContent>
  </Sheet>;
}
