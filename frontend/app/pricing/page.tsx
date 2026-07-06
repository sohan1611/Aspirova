import type { Metadata } from "next";
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
  let plans: PlanPublic[];
  try {
    plans = await getPlans();
  } catch {
    plans = FALLBACK_PLANS;
  }

  return (
    <main className="mx-auto max-w-4xl px-4 py-12">
      <div className="text-center">
        <h1 className="text-3xl font-bold tracking-tight text-foreground">
          Simple, honest pricing
        </h1>
        <p className="mt-2 text-muted-foreground">
          The free feed is genuinely useful today. Pro is launching soon -
          join the waitlist to be first in line.
        </p>
      </div>

      <div className="mt-10">
        <PricingPlans plans={plans} />
      </div>
    </main>
  );
}
