import type { Metadata } from "next";
import CopilotChat from "@/components/CopilotChat";

export const metadata: Metadata = {
  title: "Career Copilot",
  description:
    "Ask career questions grounded in Aspirova opportunities and your profile.",
};

export default function CopilotPage() {
  return <CopilotChat />;
}
