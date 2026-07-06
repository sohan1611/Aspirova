import type { Metadata } from "next";
import ResumeMatchPage from "@/components/ResumeMatchPage";

export const metadata: Metadata = {
  title: "Resume Match",
  description:
    "Paste your resume and discover Aspirova opportunities ranked by fit.",
};

export default function ResumePage() {
  return <ResumeMatchPage />;
}
