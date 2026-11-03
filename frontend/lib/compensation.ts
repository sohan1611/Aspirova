const SYMBOLS: Record<string, string> = {
  INR: "₹", USD: "$", CAD: "C$", AUD: "A$", SGD: "S$", GBP: "£", EUR: "€",
};

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
  const period = pay.period;
  if (
    typeof low !== "number" || !Number.isFinite(low) || low <= 0 ||
    typeof high !== "number" || !Number.isFinite(high) || high < low ||
    !SYMBOLS[currency] || !["month", "year", "hour"].includes(String(period))
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
