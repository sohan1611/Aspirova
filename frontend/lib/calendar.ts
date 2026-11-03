export interface DeadlineEvent {
  slug: string;
  title: string;
  deadline: string;
  url: string;
  estimated: boolean;
}

function timestamp(date: Date): string {
  return date.toISOString().replace(/[-:]/g, "").replace(/\.\d{3}/, "");
}

function eventFields(event: DeadlineEvent) {
  const end = new Date(event.deadline);
  return {
    start: timestamp(new Date(end.getTime() - 30 * 60 * 1000)),
    end: timestamp(end),
    summary: `${event.estimated ? "Estimated deadline" : "Deadline"}: ${event.title}`,
  };
}

export function googleCalendarUrl(event: DeadlineEvent): string {
  const fields = eventFields(event);
  const params = new URLSearchParams({
    action: "TEMPLATE", text: fields.summary,
    dates: `${fields.start}/${fields.end}`, details: event.url,
  });
  return `https://calendar.google.com/calendar/render?${params.toString()}`;
}

function escapeText(value: string): string {
  return value.replace(/\\/g, "\\\\").replace(/;/g, "\\;").replace(/,/g, "\\,").replace(/\r\n|\r|\n/g, "\\n");
}

function foldLine(line: string): string {
  const encoder = new TextEncoder();
  let result = "";
  let octets = 0;
  for (const character of line) {
    const length = encoder.encode(character).length;
    if (octets + length > 75) {
      result += "\r\n ";
      octets = 1;
    }
    result += character;
    octets += length;
  }
  return result;
}

export function buildIcs(event: DeadlineEvent): string {
  const fields = eventFields(event);
  return [
    "BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Aspirova//Deadlines//EN",
    "CALSCALE:GREGORIAN", "BEGIN:VEVENT",
    `UID:${escapeText(event.slug)}@aspirova.org`, `DTSTAMP:${timestamp(new Date())}`,
    `DTSTART:${fields.start}`, `DTEND:${fields.end}`,
    `SUMMARY:${escapeText(fields.summary)}`, `DESCRIPTION:${escapeText(event.url)}`,
    `URL:${event.url}`, "BEGIN:VALARM", "TRIGGER:-P1D", "ACTION:DISPLAY",
    `DESCRIPTION:${escapeText(fields.summary)}`, "END:VALARM", "END:VEVENT", "END:VCALENDAR",
  ].map(foldLine).join("\r\n") + "\r\n";
}
