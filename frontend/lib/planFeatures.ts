// Show only features that run today; plan flags stay so features can return by adding their line back.
export const FEATURE_LABELS: Array<[string, (value: unknown) => string | null]> = [
  [
    "dream_companies_limit",
    (value) =>
      typeof value === "number"
        ? `Follow ${value} ${value === 1 ? "company" : "companies"}`
        : value === null
          ? "Follow unlimited companies"
          : null,
  ],
  ["daily_digest", (value) => (value === true ? "Daily digest email" : null)],
  [
    "instant_alerts",
    (value) => (value === true ? "Instant alerts for followed companies" : null),
  ],
  ["unlimited_bookmarks", (value) => (value === true ? "Unlimited bookmarks" : null)],
  ["weekly_report", (value) => (value === true ? "Weekly career report" : null)],
];
