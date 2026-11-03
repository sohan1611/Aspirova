import type { Metadata } from "next";
import ResumeMatchPage from "@/components/ResumeMatchPage";

export const metadata: Metadata = {
  title: "Resume check",
  description:
    "Store your private resume, review suggested skills and check an ATS readiness estimate.",
};

export default function ResumePage() {
  return <ResumeMatchPage />;
}
