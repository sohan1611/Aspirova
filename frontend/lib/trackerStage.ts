export function trackerStageMessage(stage: string | undefined): string | null {
  switch (stage) {
    case "planned":
      return "You marked this as planned.";
    case "applied":
      return "You marked this as applied.";
    case "interviewing":
      return "You're interviewing for this role.";
    case "assessment":
      return "You marked this as assessment.";
    case "offer":
      return "You have an offer for this role.";
    case "rejected":
      return "You marked this as rejected.";
    default:
      return null;
  }
}
