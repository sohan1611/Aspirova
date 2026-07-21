"use client";

import { Check, Loader2 } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { toast } from "sonner";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { cancelSubscription } from "@/lib/api";
import { formatDate } from "@/lib/date";
import type { AccountMe, PlanState } from "@/lib/types";

const FEATURE_LABELS: Array<[string, (value: unknown) => string | null]> = [
  [
    "dream_companies_limit",
    (value) =>
      typeof value === "number"
        ? `Track ${value} dream ${value === 1 ? "company" : "companies"}`
        : value === null
          ? "Unlimited dream companies"
          : null,
  ],
  ["daily_digest", (value) => (value === true ? "Daily digest email" : null)],
  [
    "instant_alerts",
    (value) => (value === true ? "Instant alerts for dream companies" : null),
  ],
  ["unlimited_bookmarks", (value) => (value === true ? "Unlimited bookmarks" : null)],
  ["weekly_report", (value) => (value === true ? "Weekly career report" : null)],
  [
    "hidden_opps",
    (value) =>
      value === true
        ? "Hidden opportunities"
        : value === "limited"
          ? "Limited hidden opportunities"
          : null,
  ],
  ["resume_match", (value) => (value === true ? "AI Resume Match" : null)],
  ["copilot", (value) => (value === true ? "AI Career Copilot" : null)],
  ["prediction", (value) => (value === true ? "Reopen prediction" : null)],
];

function featureLines(features: PlanState["features"]): string[] {
  return FEATURE_LABELS.map(([key, label]) => label(features[key])).filter(
    (line): line is string => line !== null,
  );
}

function planName(key: string): string {
  if (key === "free") return "Free";
  if (key.startsWith("pro_lite_")) return "Pro Lite";
  if (key.startsWith("pro_")) return "Pro";
  return key
    .split("_")
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
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

  return (
    <Card>
      <CardHeader>
        <CardTitle className="font-serif text-2xl">Subscription</CardTitle>
        <CardDescription>Your plan and billing.</CardDescription>
      </CardHeader>
      <CardContent>
        <div className="rounded-xl border border-border bg-background/60 p-5 sm:p-6">
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div>
              <div className="flex items-center gap-2">
                <h3 className="font-serif text-2xl font-semibold">{planName(plan.key)}</h3>
                <Badge variant={plan.status === "active" ? "default" : "secondary"}>
                  {plan.status === "active"
                    ? "Active"
                    : plan.status === "free"
                      ? "Free"
                      : plan.status}
                </Badge>
              </div>
              {!isFree && (
                <p className="mt-2 text-lg font-semibold text-foreground">
                  ₹{plan.price_paise / 100}
                  {plan.billing === "annual" ? "/yr" : "/mo"}
                </p>
              )}
              {cancellationScheduled ? (
                <p className="mt-1 text-sm text-muted-foreground">
                  Your access ends{" "}
                  {plan.current_period_end
                    ? `on ${formatDate(plan.current_period_end)}`
                    : "at the end of your current billing period"}
                  . Your plan stays fully usable until then.
                </p>
              ) : (
                plan.current_period_end && (
                  <p className="mt-1 text-sm text-muted-foreground">
                    Renews on {formatDate(plan.current_period_end)}
                  </p>
                )
              )}
            </div>
          </div>

          {features.length > 0 && (
            <ul className="mt-6 grid gap-2 text-sm text-muted-foreground sm:grid-cols-2">
              {features.map((feature) => (
                <li key={feature} className="flex items-start gap-2">
                  <Check className="mt-0.5 size-4 shrink-0 text-primary" aria-hidden="true" />
                  {feature}
                </li>
              ))}
            </ul>
          )}

          <div className="mt-6 flex flex-col gap-2 sm:flex-row">
            {isFree ? (
              <Button asChild>
                <Link href="/pricing">Upgrade</Link>
              </Button>
            ) : (
              <>
                <Button asChild variant="outline">
                  <Link href="/pricing">Change plan</Link>
                </Button>
                {!cancellationScheduled && (
                  <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
                    <DialogTrigger asChild>
                      <Button
                        variant="outline"
                        className="border-destructive/40 text-destructive hover:bg-destructive/10 hover:text-destructive"
                      >
                        Cancel subscription
                      </Button>
                    </DialogTrigger>
                    <DialogContent>
                      <DialogHeader>
                        <DialogTitle>Cancel your subscription?</DialogTitle>
                        <DialogDescription>
                          You&apos;ll keep access until{" "}
                          {plan.current_period_end
                            ? formatDate(plan.current_period_end)
                            : "the end of your current billing period"}
                          .
                        </DialogDescription>
                      </DialogHeader>
                      <DialogFooter>
                        <DialogClose asChild>
                          <Button variant="outline" disabled={cancelling}>
                            Keep subscription
                          </Button>
                        </DialogClose>
                        <Button
                          variant="destructive"
                          disabled={cancelling}
                          onClick={() => void handleCancel()}
                        >
                          {cancelling && (
                            <Loader2 className="animate-spin" aria-hidden="true" />
                          )}
                          {cancelling ? "Scheduling…" : "Confirm cancellation"}
                        </Button>
                      </DialogFooter>
                    </DialogContent>
                  </Dialog>
                )}
              </>
            )}
          </div>
        </div>
      </CardContent>
      <CardFooter>
        <p className="text-xs text-muted-foreground">
          Billing is handled securely by Razorpay.
        </p>
      </CardFooter>
    </Card>
  );
}
