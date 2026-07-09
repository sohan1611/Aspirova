import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Account",
  description: "Manage your Aspirova profile, subscription, and account settings.",
};

export default function AccountLayout({ children }: { children: React.ReactNode }) {
  return children;
}
