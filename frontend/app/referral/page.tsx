import type { Metadata } from "next";
import ReferralPage from "@/components/ReferralPage";

export const metadata: Metadata = {
  title: "Invite",
  description:
    "Share Aspirova with friends and earn Pro Lite referral rewards.",
};

export default function ReferralRoute() {
  return <ReferralPage />;
}
