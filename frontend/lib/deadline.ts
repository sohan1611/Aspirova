export const COMPETITION_CATEGORIES = new Set(["hackathon", "competition"]);

export function isCompetitionCategory(category: string | null): boolean {
  return category !== null && COMPETITION_CATEGORIES.has(category);
}

export function hasExpiringDeadline(category: string | null): boolean {
  const isCompetition = isCompetitionCategory(category);
  const isInternship = category === "internship";

  return isCompetition || isInternship;
}

export function isDeadlinePast(value: string): boolean {
  const timestamp = new Date(value).getTime();
  return !Number.isNaN(timestamp) && timestamp < Date.now();
}

export function closedDeadlineLabel(category: string | null): string {
  return category === "internship"
    ? "Applications closed"
    : "Registrations closed";
}

export function estimatedClosedDeadlineLabel(category: string | null): string {
  return category === "internship"
    ? "Applications may have closed"
    : "Registrations may have closed";
}
