"use client";

import { Check } from "lucide-react";
import { useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardFooter, CardHeader, CardTitle } from "@/components/ui/card";
import type { PlanPublic } from "@/lib/types";
import { cn } from "@/lib/utils";
import SubscribeButton from "./SubscribeButton";
import WaitlistForm from "./WaitlistForm";

const FEATURE_LABELS: [string, (v: unknown) => string | null][] = [
  [
    "dream_companies_limit",
    (v) => (v === null ? "Unlimited dream companies" : `Track ${v} dream ${v === 1 ? "company" : "companies"}`),
  ],
  ["daily_digest", (v) => (v ? "Daily digest email" : null)],
  ["instant_alerts", (v) => (v ? "Instant alerts for dream companies" : null)],
  ["unlimited_bookmarks", (v) => (v ? "Unlimited bookmarks" : null)],
  ["weekly_report", (v) => (v ? "Weekly career report" : null)],
  [
    "hidden_opps",
    (v) => (v === true ? "Hidden opportunities" : v === "limited" ? "Limited hidden opportunities" : null),
  ],
  ["resume_match", (v) => (v ? "AI Resume Match" : null)],
  ["copilot", (v) => (v ? "AI Career Copilot" : null)],
  ["prediction", (v) => (v ? "Reopen prediction" : null)],
];

function featureLines(features: PlanPublic["features"]): string[] {
  return FEATURE_LABELS.map(([key, label]) => label(features[key])).filter(
    (line): line is string => line !== null,
  );
}

function rupees(paise: number): string {
  return `₹${Math.round(paise / 100)}`;
}

interface Tier {
  name: string;
  highlight?: boolean;
  free?: PlanPublic;
  monthly?: PlanPublic;
  annual?: PlanPublic;
}

export default function PricingPlans({
  plans,
  paymentsEnabled,
}: {
  plans: PlanPublic[];
  paymentsEnabled: boolean;
}) {
  const [billing, setBilling] = useState<"monthly" | "annual">("annual");

  const byKey = Object.fromEntries(plans.map((p) => [p.key, p]));
  const tiers: Tier[] = [
    { name: "Free", free: byKey.free },
    { name: "Pro Lite", monthly: byKey.pro_lite_monthly, annual: byKey.pro_lite_annual },
    { name: "Pro", highlight: true, monthly: byKey.pro_monthly, annual: byKey.pro_annual },
  ];

  return (
    <div>
      <div className="flex justify-center">
        <div
          role="group"
          aria-label="Billing period"
          className="inline-flex rounded-md border border-border bg-muted p-1"
        >
          {(["monthly", "annual"] as const).map((period) => (
            <button
              key={period}
              type="button"
              aria-pressed={billing === period}
              onClick={() => setBilling(period)}
              className={cn(
                "rounded-sm px-4 py-1.5 text-sm font-medium capitalize transition-colors duration-150",
                billing === period
                  ? "bg-background text-foreground shadow-xs"
                  : "text-muted-foreground hover:text-foreground",
              )}
            >
              {period}
              {period === "annual" && (
                <span className="ml-1.5 text-xs text-primary">Save ~15%</span>
              )}
            </button>
          ))}
        </div>
      </div>

      <div className="mt-8 grid gap-6 md:grid-cols-3">
        {tiers.map((tier) => {
          const plan = tier.free ?? (billing === "annual" ? tier.annual : tier.monthly);
          if (!plan) return null;

          const isFree = tier.name === "Free";
          const priceLabel = isFree
            ? "Free"
            : `${rupees(plan.price_paise)}${billing === "annual" ? "/yr" : "/mo"}`;

          return (
            <Card
              key={tier.name}
              className={cn("relative", tier.highlight && "border-primary shadow-md")}
            >
              {tier.highlight && (
                <Badge className="absolute -top-3 left-1/2 -translate-x-1/2">Most popular</Badge>
              )}
              <CardHeader>
                <CardTitle className="text-lg">{tier.name}</CardTitle>
                <p className="text-3xl font-bold tracking-tight text-foreground">{priceLabel}</p>
              </CardHeader>
              <CardContent className="flex-1">
                <ul className="space-y-2 text-sm text-muted-foreground">
                  {featureLines(plan.features).map((line) => (
                    <li key={line} className="flex items-start gap-2">
                      <Check className="mt-0.5 h-4 w-4 shrink-0 text-primary" />
                      {line}
                    </li>
                  ))}
                </ul>
              </CardContent>
              <CardFooter>
                {isFree ? (
                  <Button variant="outline" className="w-full" disabled>
                    Included today
                  </Button>
                ) : paymentsEnabled ? (
                  <SubscribeButton
                    planKey={plan.key}
                    planLabel={tier.name}
                    highlight={tier.highlight}
                  />
                ) : (
                  <WaitlistForm planLabel={tier.name} highlight={tier.highlight} />
                )}
              </CardFooter>
            </Card>
          );
        })}
      </div>
    </div>
  );
}
