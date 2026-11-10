export function trackerStageMessage(stage: string | undefined): string | null {
  switch (stage) {
    case "applied":
      return "You marked this as applied.";
    case "interviewing":
      return "You're interviewing for this role.";
    case "offer":
      return "You have an offer for this role.";
    default:
      return null;
  }
}
