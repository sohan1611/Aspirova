import { formatDate } from "@/lib/date";

type Meta = Record<string, unknown> | null | undefined;

const CURRENCIES: Record<string, string> = {
  "fa-rupee": "INR",
  "fa-inr": "INR",
  "fa-rupee-sign": "INR",
  INR: "INR",
  inr: "INR",
  "fa-dollar": "USD",
  "fa-usd": "USD",
  USD: "USD",
  "fa-eur": "EUR",
  EUR: "EUR",
  "fa-gbp": "GBP",
  GBP: "GBP",
};
const SYMBOLS: Record<string, string> = { INR: "₹", USD: "$", EUR: "€", GBP: "£" };

function positiveCash(value: unknown): number | null {
  if (typeof value !== "number" && typeof value !== "string") return null;
  if (typeof value === "string" && !/^\s*[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?\s*$/.test(value)) return null;
  const number = Number(value);
  return Number.isFinite(number) && number > 0 ? number : null;
}

function cashPrizes(meta: Meta): { rank: unknown; cash: number; currency: string }[] {
  if (!Array.isArray(meta?.prizes)) return [];
  return meta.prizes.flatMap((prize: unknown) => {
    if (!prize || typeof prize !== "object" || Array.isArray(prize)) return [];
    const entry = prize as Record<string, unknown>;
    const currency = typeof entry.currency === "string" && Object.prototype.hasOwnProperty.call(CURRENCIES, entry.currency)
      ? CURRENCIES[entry.currency]
      : null;
    const cash = positiveCash(entry.cash);
    return currency && cash !== null ? [{ rank: entry.rank, cash, currency }] : [];
  });
}

function formatAmount(cash: number, currency: string): string {
  return `${SYMBOLS[currency]}${cash.toLocaleString(currency === "INR" ? "en-IN" : "en-US")}`;
}

export function formatPrizePool(meta: Meta): string | null {
  return typeof meta?.prize_text === "string" && meta.prize_text.trim()
    ? meta.prize_text
    : null;
}

export function prizeBreakdown(meta: Meta): { rank: string; amount: string }[] {
  return cashPrizes(meta).slice(0, 5).map(({ rank, cash, currency }) => {
    let label = typeof rank === "string" || typeof rank === "number" ? String(rank).trim() : "";
    if (/^\d+$/.test(label)) {
      const number = Number(label);
      const suffix = number % 100 >= 11 && number % 100 <= 13 ? "th"
        : (({ 1: "st", 2: "nd", 3: "rd" } as Record<number, string>)[number % 10] ?? "th");
      label = `${number}${suffix}`;
    }
    return { rank: label, amount: formatAmount(cash, currency) };
  });
}

export function competitionMode(item: {
  meta?: Meta;
  is_remote: boolean | null;
  source: string | null;
}): "Online" | "In person" | "Hybrid" | null {
  const mode = typeof item.meta?.mode === "string" ? item.meta.mode.trim().toLowerCase() : "";
  if (mode === "online") return "Online";
  if (mode === "offline") return "In person";
  if (mode === "hybrid") return "Hybrid";
  if (item.meta?.is_online === true) return "Online";
  if (item.meta?.is_online === false) return "In person";
  if (item.source === "devpost" && mode) return "In person";
  return item.is_remote === true ? "Online" : null;
}

export function participantCount(meta: Meta): number | null {
  for (const key of ["register_count", "registrations_count", "participants_count"]) {
    const value = positiveCash(meta?.[key]);
    if (value !== null) return value;
  }
  return null;
}

export function teamSizeText(meta: Meta): string | null {
  const min = meta?.team_min;
  const max = meta?.team_size;
  const valid = (value: unknown): value is number =>
    typeof value === "number" && Number.isInteger(value) && value >= 1;
  if ((min != null && !valid(min)) || (max != null && !valid(max))) return null;
  if (!valid(max)) return null;
  if (!valid(min)) return `Up to ${max} people`;
  if (min > max) return null;
  if (min === 1 && max === 1) return "Individual";
  if (min === max) return `Team of ${max}`;
  return `${min}–${max} people`;
}

export function eligibilityText(meta: Meta): string | null {
  if (!Array.isArray(meta?.eligibility)) return null;
  const values = meta.eligibility
    .filter((value): value is string => typeof value === "string" && !!value.trim())
    .map((value) => value.trim());
  return values.includes("All") ? "Open to all" : values.join(", ") || null;
}

export function eventDatesText(meta: Meta): string | null {
  if (typeof meta?.dates === "string" && meta.dates.trim()) return meta.dates.trim();
  const start = meta?.starts_at;
  const end = meta?.ends_at;
  if (typeof start !== "string" || typeof end !== "string") return null;
  if (Number.isNaN(Date.parse(start)) || Number.isNaN(Date.parse(end))) return null;
  return `${formatDate(start)}–${formatDate(end)}`;
}
