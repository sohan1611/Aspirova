import type { Metadata } from "next";
import type { ReactNode } from "react";

export const metadata: Metadata = {
  title: "Reset your password",
  // A single-use recovery surface: never worth a search result, and indexing it
  // would put a dead-end page in front of people looking for the real site.
  robots: { index: false, follow: false },
};

export default function ResetPasswordLayout({ children }: { children: ReactNode }) {
  return children;
}
