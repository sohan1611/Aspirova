/**
 * These values MUST be filled with real values before Razorpay activation.
 * Razorpay verifies them.
 */
export const LEGAL = {
  entityName: "TODO_LEGAL_ENTITY_NAME", // registered name, e.g. "Aspirova Technologies Pvt Ltd" or the proprietor's name
  address: "TODO_BUSINESS_ADDRESS", // Razorpay requires a real operating address
  contactEmail: "TODO_CONTACT_EMAIL",
  jurisdiction: "TODO_CITY, India", // courts for disputes
  lastUpdated: "2026-07-16",
} as const;

export const HAS_PLACEHOLDER = (v: string) => v.startsWith("TODO_");
