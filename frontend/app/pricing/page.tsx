import type { Metadata } from "next";
import PricingPlans from "@/components/PricingPlans";
import { getPlans } from "@/lib/api";

export const metadata: Metadata = {
  title: "Pricing",
  description: "Aspirova pricing - Free, Pro Lite, and Pro plans. Pro launches soon.",
};

export default async function PricingPage() {
  const plans = await getPlans();

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
