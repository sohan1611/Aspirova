import type { Metadata } from "next";
import ResumeMatchPage from "@/components/ResumeMatchPage";

export const metadata: Metadata = {
  title: "Matches and resume check",
  description:
    "Opportunities ranked by your fields and skills, plus a private resume store, skill suggestions and an ATS readiness estimate.",
};

export default function ResumePage() {
  return <ResumeMatchPage />;
}
