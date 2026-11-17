const LONG_DATE_FORMATTER = new Intl.DateTimeFormat("en-GB", {
  day: "numeric",
  month: "short",
  year: "numeric",
});

const SHORT_LONG_DATE_FORMATTER = new Intl.DateTimeFormat("en-GB", {
  day: "numeric",
  month: "short",
});

const NUMERIC_DATE_FORMATTER = new Intl.DateTimeFormat("en-GB", {
  day: "2-digit",
  month: "2-digit",
  year: "numeric",
});

const SHORT_UTC_DATE_FORMATTER = new Intl.DateTimeFormat("en-GB", {
  day: "numeric",
  month: "short",
  timeZone: "UTC",
});

const LONG_UTC_DATE_FORMATTER = new Intl.DateTimeFormat("en-GB", {
  day: "numeric",
  month: "short",
  year: "numeric",
  timeZone: "UTC",
});

/**
 * Deadlines and posted dates are calendar days stored in UTC (often 23:59:59Z). Format them in
 * UTC, as OpportunityCard and the action center do, so the Vercel server (UTC) and a browser in
 * IST print the same day on one page.
 */
export function formatDateUtc(value: string | Date, now: Date = new Date()): string {
  const date = typeof value === "string" ? new Date(value) : value;
  if (Number.isNaN(date.getTime())) {
    return typeof value === "string" ? value : "";
  }
  const formatter =
    date.getUTCFullYear() === now.getUTCFullYear()
      ? SHORT_UTC_DATE_FORMATTER
      : LONG_UTC_DATE_FORMATTER;
  return formatter.format(date);
}

export function formatDate(
  value: string | Date,
  variant: "long" | "numeric" = "long",
): string {
  const date = typeof value === "string" ? new Date(value) : value;

  if (Number.isNaN(date.getTime())) {
    return typeof value === "string" ? value : "";
  }

  if (variant === "numeric") {
    return NUMERIC_DATE_FORMATTER.format(date);
  }

  const formatter =
    date.getFullYear() === new Date().getFullYear()
      ? SHORT_LONG_DATE_FORMATTER
      : LONG_DATE_FORMATTER;
  return formatter.format(date);
}
