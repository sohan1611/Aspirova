"use client";

import { Check } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardFooter, CardHeader, CardTitle } from "@/components/ui/card";
import { getAccount } from "@/lib/api";
import { useCurrency } from "@/lib/country";
import type { PlanPublic } from "@/lib/types";
import { useSession } from "@/lib/useSession";
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
  const { currency, hydrated } = useCurrency();
  const session = useSession();
  const accessToken = session?.access_token;
  const [planResult, setPlanResult] = useState<{
    accessToken: string;
    currentPlanKey: string | null;
  } | null>(null);
  const planRequestRef = useRef(0);

  const currentPlanKey =
    planResult && planResult.accessToken === accessToken ? planResult.currentPlanKey : null;
  const planLoading = Boolean(accessToken) && planResult?.accessToken !== accessToken;

  useEffect(() => {
    const requestId = planRequestRef.current + 1;
    planRequestRef.current = requestId;

    if (!accessToken) return;

    let cancelled = false;
    void getAccount(accessToken)
      .then((account) => {
        if (cancelled || planRequestRef.current !== requestId) return;
        setPlanResult({
          accessToken,
          currentPlanKey: account.plan.status !== "free" ? account.plan.key : null,
        });
      })
      .catch(() => {
        if (cancelled || planRequestRef.current !== requestId) return;
        setPlanResult({ accessToken, currentPlanKey: null });
      });

    return () => {
      cancelled = true;
    };
  }, [accessToken]);

  const byKey = Object.fromEntries(plans.map((p) => [p.key, p]));
  const tiers: Tier[] = [
    { name: "Free", free: byKey.free },
    { name: "Pro Lite", monthly: byKey.pro_lite_monthly, annual: byKey.pro_lite_annual },
    { name: "Pro", highlight: true, monthly: byKey.pro_monthly, annual: byKey.pro_annual },
  ];

  return (
    <div>
      <div className="flex justify-center">
        <div className="flex flex-col items-center gap-2">
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
                  "rounded-sm px-4 py-1.5 text-sm font-medium capitalize outline-none transition-colors duration-150 focus-visible:ring-2 focus-visible:ring-ring",
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
          {hydrated && (
            <p className="text-xs font-medium text-muted-foreground">
              {currency === "INR"
                ? "Prices shown in ₹ (INR) · India"
                : "You're outside India — USD pricing is being finalized."}
            </p>
          )}
        </div>
      </div>

      <div className="mt-8 grid gap-6 md:grid-cols-3">
        {tiers.map((tier) => {
          const plan = tier.free ?? (billing === "annual" ? tier.annual : tier.monthly);
          if (!plan) return null;

          const isFree = tier.name === "Free";
          const price = isFree ? "Free" : rupees(plan.price_paise);
          const billingSuffix = isFree ? null : billing === "annual" ? "/yr" : "/mo";
          const usdPricingPending = !isFree && currency === "USD";
          const isCurrentPlan = currentPlanKey != null && plan.key === currentPlanKey;
          const isCurrentTier =
            currentPlanKey != null &&
            (tier.monthly?.key === currentPlanKey || tier.annual?.key === currentPlanKey);

          return (
            <Card
              key={tier.name}
              className={cn(
                "relative py-8 shadow-soft transition-[transform,box-shadow,border-color] duration-300 ease-premium",
                !isFree && "hover:-translate-y-0.5 hover:[box-shadow:var(--shadow-md)]",
                tier.highlight && "border-heritage/40 shadow-soft-md",
              )}
            >
              {isCurrentTier ? (
                <Badge
                  variant="heritage"
                  className="absolute -top-3 left-1/2 -translate-x-1/2"
                >
                  Current plan
                </Badge>
              ) : tier.highlight ? (
                <Badge
                  variant="heritage"
                  className="absolute -top-3 left-1/2 -translate-x-1/2"
                >
                  Most popular
                </Badge>
              ) : null}
              <CardHeader>
                <CardTitle className="eyebrow">{tier.name}</CardTitle>
                <div className="flex items-baseline gap-1.5">
                  {usdPricingPending ? (
                    <p className="text-sm font-medium text-muted-foreground">
                      USD pricing coming soon
                    </p>
                  ) : (
                    <>
                      <p className="tnum font-serif text-4xl font-semibold tracking-tight text-foreground">
                        {price}
                      </p>
                      {billingSuffix && (
                        <span className="text-sm font-normal text-muted-foreground">
                          {billingSuffix}
                        </span>
                      )}
                    </>
                  )}
                </div>
              </CardHeader>
              <CardContent className="flex-1">
                <ul className="space-y-3 text-sm leading-6 text-muted-foreground">
                  {featureLines(plan.features).map((line) => (
                    <li key={line} className="flex items-start gap-2.5">
                      <Check
                        className="mt-1 size-4 shrink-0 text-primary"
                        aria-hidden="true"
                      />
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
                ) : planLoading ? (
                  <Button
                    variant={tier.highlight ? "default" : "outline"}
                    className="w-full"
                    disabled
                  >
                    Loading…
                  </Button>
                ) : isCurrentPlan ? (
                  <Button
                    variant={tier.highlight ? "default" : "outline"}
                    className="w-full"
                    disabled
                  >
                    Current plan
                  </Button>
                ) : paymentsEnabled && currency === "INR" ? (
                  <SubscribeButton
                    planKey={plan.key}
                    planLabel={tier.name}
                    highlight={tier.highlight}
                    label={isCurrentTier ? `Switch to ${billing}` : undefined}
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
