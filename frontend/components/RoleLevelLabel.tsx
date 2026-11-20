import type { RoleLevel } from "@/lib/types";

export default function RoleLevelLabel({ roleLevel }: { roleLevel?: RoleLevel }) {
  if (roleLevel?.level !== "experienced") return null;

  const evidence = roleLevel.evidence;
  const title = roleLevel.source === "title"
    ? `Title says "${evidence}"`
    : roleLevel.source === "override"
      ? `Reviewed: ${evidence}`
      : evidence === true
        ? "Employer eligibility is experienced-only"
        : `Eligibility says "${evidence}"`;

  return (
    <span
      className="inline-flex w-fit rounded-md border border-border px-2 py-0.5 text-xs text-muted-foreground"
      title={title}
    >
      Experienced role
      <span className="sr-only">. {title}</span>
    </span>
  );
}
