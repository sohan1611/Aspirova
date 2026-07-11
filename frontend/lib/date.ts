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
