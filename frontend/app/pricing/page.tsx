import type { Metadata } from "next";
import Script from "next/script";
import PricingPlans from "@/components/PricingPlans";
import { getPlans } from "@/lib/api";
import type { PlanPublic } from "@/lib/types";

const FREE_FEATURES: PlanPublic["features"] = {
  dream_companies_limit: 1,
  instant_alerts: false,
  weekly_report: false,
  hidden_opps: "limited",
  unlimited_bookmarks: false,
  daily_digest: true,
  copilot: false,
  resume_match: false,
  prediction: false,
};

const PRO_LITE_FEATURES: PlanPublic["features"] = {
  dream_companies_limit: 5,
  instant_alerts: true,
  weekly_report: true,
  hidden_opps: true,
  unlimited_bookmarks: true,
  daily_digest: true,
  copilot: false,
  resume_match: false,
  prediction: false,
};

const PRO_FEATURES: PlanPublic["features"] = {
  dream_companies_limit: null,
  instant_alerts: true,
  weekly_report: true,
  hidden_opps: true,
  unlimited_bookmarks: true,
  daily_digest: true,
  copilot: true,
  resume_match: true,
  prediction: true,
};

const FALLBACK_PLANS: PlanPublic[] = [
  { key: "free", price_paise: 0, billing: null, features: FREE_FEATURES },
  {
    key: "pro_lite_monthly",
    price_paise: 3900,
    billing: "monthly",
    features: PRO_LITE_FEATURES,
  },
  {
    key: "pro_lite_annual",
    price_paise: 39900,
    billing: "annual",
    features: PRO_LITE_FEATURES,
  },
  {
    key: "pro_monthly",
    price_paise: 4900,
    billing: "monthly",
    features: PRO_FEATURES,
  },
  {
    key: "pro_annual",
    price_paise: 49900,
    billing: "annual",
    features: PRO_FEATURES,
  },
];

export const metadata: Metadata = {
  title: "Pricing",
  description: "Aspirova pricing - Free, Pro Lite, and Pro plans. Pro launches soon.",
};

export default async function PricingPage() {
  const paymentsEnabled = process.env.NEXT_PUBLIC_PAYMENTS_ENABLED === "true";
  let plans: PlanPublic[];
  try {
    plans = await getPlans();
  } catch {
    plans = FALLBACK_PLANS;
  }

  return (
    <main className="mx-auto max-w-4xl px-4 py-12">
      {paymentsEnabled && (
        <Script src="https://checkout.razorpay.com/v1/checkout.js" strategy="afterInteractive" />
      )}
      <header className="mx-auto max-w-3xl text-center">
        <p className="eyebrow">Membership</p>
        <h1 className="mt-3 font-serif text-4xl font-semibold leading-tight tracking-tight text-foreground sm:text-5xl">
          Simple, honest pricing
        </h1>
        <p className="mx-auto mt-4 max-w-2xl text-sm leading-6 text-muted-foreground sm:text-base sm:leading-7">
          The free feed is genuinely useful today. Pro is launching soon -
          join the waitlist to be first in line.
        </p>
      </header>

      <div className="mt-10">
        <PricingPlans plans={plans} paymentsEnabled={paymentsEnabled} />
      </div>
    </main>
  );
}
