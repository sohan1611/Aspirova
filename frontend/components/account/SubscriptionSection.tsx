"use client";

import { CalendarDays, CircleCheck, CreditCard, ShieldCheck, Sparkles, TriangleAlert } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { toast } from "sonner";
import { ConfirmDialog, SectionHeader, SettingsCard, StatusPill } from "@/components/account/primitives";
import { Button } from "@/components/ui/button";
import { cancelSubscription } from "@/lib/api";
import { formatDate } from "@/lib/date";
import { FEATURE_LABELS } from "@/lib/planFeatures";
import { planName } from "@/lib/planName";
import type { AccountMe, PlanState } from "@/lib/types";

function featureLines(features: PlanState["features"]): string[] {
  return FEATURE_LABELS.map(([key, label]) => label(features[key])).filter(
    (line): line is string => line !== null,
  );
}

function billingSummary(plan: PlanState, isFree: boolean): string {
  if (isFree) return "You’re on the free plan.";

  const periodEnd = plan.current_period_end
    ? formatDate(plan.current_period_end)
    : "the end of your current billing period";

  if (plan.cancel_at_period_end) {
    return `Access until ${periodEnd} · resubscribe anytime from Pricing.`;
  }

  const billingPeriod = plan.billing === "annual" ? "year" : "month";
  return `₹${plan.price_paise / 100}/${billingPeriod} · renews ${periodEnd}`;
}

export default function SubscriptionSection({
  account,
  accessToken,
  refresh,
}: {
  account: AccountMe;
  accessToken: string;
  refresh: () => Promise<void>;
}) {
  const [dialogOpen, setDialogOpen] = useState(false);
  const [cancelling, setCancelling] = useState(false);
  const { plan } = account;
  const isFree = plan.key === "free" || plan.status === "free";
  const cancellationScheduled = plan.cancel_at_period_end;
  const features = featureLines(plan.features);

  async function handleCancel() {
    setCancelling(true);
    try {
      await cancelSubscription(accessToken);
      toast.success("Cancellation scheduled");
      setDialogOpen(false);
      await refresh();
    } catch {
      toast.error("We couldn't schedule cancellation. Please try again.");
    } finally {
      setCancelling(false);
    }
  }

  const periodEnd = plan.current_period_end
    ? formatDate(plan.current_period_end)
    : "the end of your current billing period";

  return (
    <section aria-labelledby="account-subscription-heading" className="grid gap-6">
      <SectionHeader id="account-subscription-heading" eyebrow="Account" title="Subscription" description="Your plan, billing and what's included." />
      <SettingsCard
        icon={CreditCard}
        title={planName(plan.key)}
        className="[&_h3]:font-serif [&_h3]:text-3xl [&_h3]:font-bold"
        action={
          <StatusPill tone={isFree ? "muted" : cancellationScheduled ? "warning" : plan.status === "active" ? "success" : "muted"}>
            {isFree ? "Free plan" : cancellationScheduled
              ? plan.current_period_end ? `Cancels ${formatDate(plan.current_period_end)}` : "Cancels at period end"
              : plan.status === "active" ? "Active" : plan.status}
          </StatusPill>
        }
        footer={isFree ? (
          <>
            <Button asChild><Link href="/pricing"><Sparkles aria-hidden="true" />Upgrade</Link></Button>
            <Button asChild variant="ghost"><Link href="/pricing">Compare plans</Link></Button>
          </>
        ) : (
          <>
            <Button asChild variant="outline"><Link href="/pricing">Change plan</Link></Button>
            {!cancellationScheduled && (
              <Button variant="destructive-ghost" onClick={() => setDialogOpen(true)}>Cancel subscription</Button>
            )}
          </>
        )}
      >
        {isFree ? (
          <p className="text-sm text-muted-foreground">{billingSummary(plan, isFree)}</p>
        ) : (
          <div className="grid gap-3">
            <p className="flex flex-wrap items-baseline gap-1">
              <span className="font-serif text-3xl tnum">₹{plan.price_paise / 100}</span>
              <span className="text-sm text-muted-foreground">/{plan.billing === "annual" ? "year" : "month"}</span>
            </p>
            <p className="flex items-center gap-2 text-sm text-muted-foreground">
              <CalendarDays className="size-4 shrink-0" aria-hidden="true" />
              {cancellationScheduled ? "Access until" : "Renews"} {periodEnd}
            </p>
          </div>
        )}

        {features.length > 0 && (
          <ul className="mt-6 grid gap-3 text-sm text-muted-foreground sm:grid-cols-2">
            {features.map((feature) => (
              <li key={feature} className="flex items-start gap-2">
                <CircleCheck className="mt-0.5 size-4 shrink-0 text-primary" aria-hidden="true" />
                {feature}
              </li>
            ))}
          </ul>
        )}

        {cancellationScheduled && (
          <div className="mt-6 flex items-start gap-3 rounded-xl border border-warning/40 bg-warning/10 p-4 text-sm">
            <TriangleAlert className="mt-0.5 size-5 shrink-0 text-warning-foreground dark:text-warning" aria-hidden="true" />
            <div className="min-w-0">
              <p>{billingSummary(plan, isFree)}</p>
              <Link href="/pricing" className="mt-1 inline-flex min-h-11 items-center font-medium text-primary underline underline-offset-4 sm:min-h-0">Resubscribe</Link>
            </div>
          </div>
        )}
      </SettingsCard>
      <p className="flex items-center gap-2 text-xs text-muted-foreground">
        <ShieldCheck className="size-4 shrink-0" aria-hidden="true" />
        Billing is handled securely by Razorpay.
      </p>
      {!isFree && !cancellationScheduled && (
        <ConfirmDialog
          open={dialogOpen}
          onOpenChange={setDialogOpen}
          title="Cancel your subscription?"
          description={<>You&apos;ll keep access until {periodEnd}.</>}
          confirmLabel="Confirm cancellation"
          pendingLabel="Scheduling…"
          cancelLabel="Keep subscription"
          pending={cancelling}
          onConfirm={handleCancel}
        />
      )}
    </section>
  );
}
