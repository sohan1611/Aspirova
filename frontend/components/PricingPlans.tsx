"use client";

import { Check } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardFooter, CardHeader, CardTitle } from "@/components/ui/card";
import { getAccount } from "@/lib/api";
import { useCurrency } from "@/lib/country";
import type { PlanPublic, PlanState } from "@/lib/types";
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

function formatDate(date: string): string {
  return new Intl.DateTimeFormat("en-GB", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    timeZone: "UTC",
  }).format(new Date(date));
}

interface Tier {
  name: string;
  highlight?: boolean;
  free?: PlanPublic;
  monthly?: PlanPublic;
  annual?: PlanPublic;
}

// The badge straddles the card's top edge, and the heritage variant's fill is
// only 10% opaque - so the card's border painted straight through the text. The
// pseudo-element lays an opaque card-coloured layer under the tint (rather than
// replacing it) so the intended tint survives and the border stops showing.
const EDGE_BADGE_CLASS_NAME =
  "absolute -top-3 left-1/2 z-10 -translate-x-1/2 before:absolute before:inset-0 before:-z-10 before:bg-card";

export default function PricingPlans({
  plans,
  paymentsEnabled,
}: {
  plans: PlanPublic[];
  paymentsEnabled: boolean;
}) {
  const [billingOverride, setBillingOverride] = useState<
    "monthly" | "annual" | null
  >(null);
  const { currency, hydrated } = useCurrency();
  const session = useSession();
  const accessToken = session?.access_token;
  const [planResult, setPlanResult] = useState<{
    accessToken: string;
    currentPlan: PlanState | null;
  } | null>(null);
  const planRequestRef = useRef(0);

  const currentPlan =
    planResult && planResult.accessToken === accessToken ? planResult.currentPlan : null;
  // Default the toggle to the subscriber's own billing period (annual for
  // signed-out/free); once they click the toggle their override wins.
  const billing: "monthly" | "annual" =
    billingOverride ??
    (currentPlan?.billing === "monthly" || currentPlan?.billing === "annual"
      ? currentPlan.billing
      : "annual");
  const currentPlanKey = currentPlan?.key ?? null;
  const planLoading = Boolean(accessToken) && planResult?.accessToken !== accessToken;
  const hasActiveSubscription = currentPlan !== null;

  const refreshPlan = useCallback(async () => {
    const requestId = planRequestRef.current + 1;
    planRequestRef.current = requestId;

    if (!accessToken) return;

    try {
      const account = await getAccount(accessToken);
      if (planRequestRef.current !== requestId) return;
      setPlanResult({
        accessToken,
        currentPlan: account.plan.status !== "free" ? account.plan : null,
      });
    } catch {
      if (planRequestRef.current !== requestId) return;
      setPlanResult({ accessToken, currentPlan: null });
    }
  }, [accessToken]);

  useEffect(() => {
    // set-state-in-effect targets SYNCHRONOUS setState cascades. refreshPlan
    // only sets state after an awaited fetch resolves, and guards every write
    // behind planRequestRef so a stale response cannot land.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void refreshPlan();
    return () => {
      planRequestRef.current += 1;
    };
  }, [refreshPlan]);

  const byKey = Object.fromEntries(plans.map((p) => [p.key, p]));
  const tiers: Tier[] = [
    { name: "Free", free: byKey.free },
    // Pro Lite Annual RETIRED (founder decision 2026-07-22): under the
    // cancel-then-resubscribe policy, a mistaken Pro Lite Annual purchase would
    // lock the customer into the bottom tier for a FULL YEAR with no way up.
    // No `annual` mapping means the Pro Lite card simply doesn't render on the
    // Annual toggle (the `if (!plan) return null` below). Nobody was ever
    // subscribed to it - verified in prod before retiring.
    { name: "Pro Lite", monthly: byKey.pro_lite_monthly },
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
                  onClick={() => setBillingOverride(period)}
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
          const availableAfter =
            currentPlan?.cancel_at_period_end && currentPlan.current_period_end
              ? `Available after ${formatDate(currentPlan.current_period_end)}`
              : null;

          return (
            <Card
              key={tier.name}
              className={cn(
                "relative py-8 shadow-soft transition-[transform,box-shadow,border-color] duration-300 ease-premium",
                !isFree && "hover:-translate-y-0.5 hover:[box-shadow:var(--shadow-md)]",
                tier.highlight && "border-heritage/40 shadow-soft-md",
              )}
            >
              {isCurrentPlan ? (
                <Badge variant="heritage" className={EDGE_BADGE_CLASS_NAME}>
                  Current plan
                </Badge>
              ) : tier.highlight ? (
                <Badge variant="heritage" className={EDGE_BADGE_CLASS_NAME}>
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
                ) : hasActiveSubscription ? (
                  <Button
                    variant={tier.highlight ? "default" : "outline"}
                    className="w-full"
                    disabled
                  >
                    {availableAfter
                      ? availableAfter
                      : isCurrentTier && !isCurrentPlan
                        ? `Current plan · billed ${currentPlan.billing}`
                        : "Cancel your current plan to switch"}
                  </Button>
                ) : paymentsEnabled && currency === "INR" ? (
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

      {hasActiveSubscription && (
        <p className="mt-5 text-center text-xs text-muted-foreground">
          <strong>Changing plans?</strong> Razorpay can&apos;t modify an active subscription.
          Cancel your current plan &mdash; you&apos;ll keep full access until it ends &mdash; then
          subscribe to any plan you like.
        </p>
      )}

      <p
        className={cn(
          "text-center text-xs text-muted-foreground",
          hasActiveSubscription ? "mt-3" : "mt-5",
        )}
      >
        Cancel anytime · no refunds — see our{" "}
        <Link className="underline underline-offset-4 hover:text-foreground" href="/refunds">
          Refund Policy
        </Link>
      </p>
    </div>
  );
}
