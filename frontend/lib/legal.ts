/**
 * These values MUST be filled with real values before Razorpay activation.
 * Razorpay verifies them.
 */
export const LEGAL = {
  // Sole proprietorship - the proprietor's own name is the registered entity.
  // These MUST match what was filed with Razorpay during activation; a
  // mismatch between this page and the KYC record can stall their review.
  entityName: "Sohan Mandal",
  address: "124/4B, Manicktala Street, Kolkata - 700 006, India",
  // Domain address, not a personal inbox: this renders publicly on /contact,
  // /privacy, /terms and /refunds, so it gets scraped. Inbound mail for the
  // apex is handled by a forwarder (Resend sends from the `send.` subdomain,
  // which is untouched by the apex MX records).
  contactEmail: "support@aspirova.org",
  jurisdiction: "Kolkata, India", // courts for disputes
  lastUpdated: "2026-07-21",
} as const;

export const HAS_PLACEHOLDER = (v: string) => v.startsWith("TODO_");
