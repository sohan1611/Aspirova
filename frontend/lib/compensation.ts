const SYMBOLS: Record<string, string> = {
  INR: "₹", USD: "$", CAD: "C$", AUD: "A$", SGD: "S$", GBP: "£", EUR: "€",
};

// Mirror core/pay_format.py. Shared fixture tests cover both display guards.
const INR_PER_UNIT: Record<string, number> = {
  INR: 1, USD: 88, EUR: 102, GBP: 117, CAD: 63, AUD: 58, SGD: 68,
};
const PERIOD_TO_MONTH: Record<string, number> = {
  month: 1, year: 1 / 12, hour: 173, week: 52 / 12,
};
const MAX_PLAUSIBLE_HOURLY_INR = 10000;
const MAX_PLAUSIBLE_MONTHLY_INR = 10000000;
const MAX_PLAUSIBLE_RANGE_RATIO = 5;

function compact(value: number): string {
  return Number(value.toFixed(2)).toLocaleString("en-US", { maximumFractionDigits: 2 });
}

export function formatCompensation(
  meta: Record<string, unknown> | null | undefined,
): string | null {
  const value = meta?.compensation;
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const pay = value as Record<string, unknown>;
  if (pay.unpaid === true) return "Unpaid";
  const low = pay.min;
  const high = pay.max;
  const currency = typeof pay.currency === "string" ? pay.currency : "";
  const period = typeof pay.period === "string" ? pay.period : "";
  if (
    typeof low !== "number" || !Number.isFinite(low) || low <= 0 ||
    typeof high !== "number" || !Number.isFinite(high) || high < low ||
    !Object.hasOwn(SYMBOLS, currency) || !Object.hasOwn(PERIOD_TO_MONTH, period) ||
    (pay.source === "text" && high > low * MAX_PLAUSIBLE_RANGE_RATIO) ||
    (period === "hour" && high * INR_PER_UNIT[currency] > MAX_PLAUSIBLE_HOURLY_INR) ||
    high * PERIOD_TO_MONTH[period] * INR_PER_UNIT[currency] > MAX_PLAUSIBLE_MONTHLY_INR
  ) return pay.paid === true ? "Paid" : null;

  let divisor = 1;
  let suffix = `/${period}`;
  if (currency === "INR" && period === "year") {
    divisor = high >= 10000000 ? 10000000 : 100000;
    suffix = divisor === 10000000 ? " Cr/year" : " LPA";
  } else if (period === "year" && low >= 1000) {
    divisor = 1000;
    suffix = "/year";
  }
  const format = (amount: number) => currency === "INR" && divisor === 1
    ? amount.toLocaleString("en-IN", { maximumFractionDigits: 2 })
    : `${compact(amount / divisor)}${currency !== "INR" && divisor === 1000 ? "K" : ""}`;
  const amounts = low === high ? format(low) : `${format(low)}–${format(high)}`;
  return `${SYMBOLS[currency]}${amounts}${suffix}${pay.ote === true ? " OTE" : ""}`;
}
