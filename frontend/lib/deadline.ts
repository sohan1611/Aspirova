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

export function isListingClosed(
  closedAt: string | null,
  deadline: string | null,
  category: string | null,
): boolean {
  if (closedAt) return true;

  return !!deadline && hasExpiringDeadline(category) && isDeadlinePast(deadline);
}

export function closedDeadlineLabel(category: string | null): string {
  return isCompetitionCategory(category)
    ? "Registrations closed"
    : "Applications closed";
}

export function estimatedClosedDeadlineLabel(category: string | null): string {
  return isCompetitionCategory(category)
    ? "Registrations may have closed"
    : "Applications may have closed";
}
