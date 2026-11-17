import { withBuildFallback } from "@/lib/buildFallback";
import type { Metadata } from "next";
import HiringCalendar from "@/components/HiringCalendar";
import CalendarHeader from "@/components/calendar/Header";
import { fetchCalendar, parseCalendarParams, todayIST } from "@/lib/hiringCalendar";

export const revalidate = 3600;
export const dynamic = "force-static";
export function generateStaticParams() { return []; }

export const metadata: Metadata = {
  title: "Hiring Calendar",
  description: "Plan application windows for research, government, early-career roles and competitions. Official dates and historical trends are clearly labelled.",
  alternates: { canonical: "/calendar" },
};

export default async function CalendarPage() {
  const query = parseCalendarParams(new URLSearchParams(), todayIST());
  const { data } = await withBuildFallback(
    () => fetchCalendar(query, { next: { revalidate: 3600 } } as RequestInit),
    result => result.items.length + result.rolling.length,
  );
  return (
    <main className="mx-auto w-full min-w-0 max-w-6xl px-4 py-6 sm:px-6 sm:py-10">
      <CalendarHeader />
      <HiringCalendar initialQuery={query} initialData={data} />
    </main>
  );
}
