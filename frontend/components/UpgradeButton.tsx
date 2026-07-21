"use client";

import { Loader2 } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import HeaderAuth from "@/components/HeaderAuth";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  isCheckoutConflictError,
  startUpgrade,
  verifyUpgrade,
} from "@/lib/api";
import type { UpgradePaymentRequired } from "@/lib/types";
import { useSession } from "@/lib/useSession";
import {
  isPaymentsUnavailableError,
  waitForRazorpay,
} from "./SubscribeButton";

interface UpgradeButtonProps {
  planKey: string;
  planLabel: string;
  highlight?: boolean;
  currentPlanLabel: string;
  onUpgraded?: () => Promise<void>;
}

interface RazorpayPaymentResponse {
  razorpay_order_id: string;
  razorpay_payment_id: string;
  razorpay_signature: string;
}

function formatUpgradeAmount(amountPaise: number): string {
  return `Rs.${(amountPaise / 100).toFixed(2)}`;
}

export default function UpgradeButton({
  planKey,
  planLabel,
  highlight,
  currentPlanLabel,
  onUpgraded,
}: UpgradeButtonProps) {
  const session = useSession();
  const accessToken = session?.access_token;
  const [loading, setLoading] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [paymentRequired, setPaymentRequired] = useState<UpgradePaymentRequired | null>(null);

  if (!session) {
    return (
      <HeaderAuth
        triggerLabel="Sign in to upgrade"
        triggerVariant={highlight ? "default" : "outline"}
        triggerClassName="w-full"
      />
    );
  }

  async function refreshAccount() {
    try {
      await onUpgraded?.();
    } catch (error) {
      console.error("Could not refresh account after upgrade", error);
    }
  }

  async function finishUpgrade() {
    toast.success(`You're on ${planLabel} now`);
    await refreshAccount();
  }

  async function handleUpgrade() {
    if (!accessToken) {
      toast.error("Please sign in again to upgrade.");
      return;
    }

    setLoading(true);
    try {
      const result = await startUpgrade(planKey, accessToken);
      if (result.status === "upgraded") {
        await finishUpgrade();
        return;
      }

      setPaymentRequired(result);
    } catch (error: unknown) {
      if (isPaymentsUnavailableError(error)) {
        toast.error("Payments aren't available yet.");
      } else if (isCheckoutConflictError(error)) {
        toast.error(error.message);
      } else {
        toast.error("Couldn't start upgrade. Please try again.");
      }
    } finally {
      setLoading(false);
    }
  }

  async function handleConfirmUpgrade() {
    if (!accessToken || !paymentRequired) return;

    const payment = paymentRequired;
    setConfirming(true);
    try {
      const Razorpay = await waitForRazorpay();
      if (!Razorpay) {
        toast.error("Payments aren't available yet.");
        return;
      }

      new Razorpay({
        key: payment.razorpay_key_id,
        order_id: payment.razorpay_order_id,
        name: "Aspirova",
        description: `Upgrade to ${planLabel}`,
        theme: { color: "#2563eb" },
        handler: async (response: RazorpayPaymentResponse) => {
          try {
            await verifyUpgrade(
              {
                razorpay_order_id: response.razorpay_order_id,
                razorpay_payment_id: response.razorpay_payment_id,
                razorpay_signature: response.razorpay_signature,
              },
              accessToken,
            );
            await finishUpgrade();
          } catch (error) {
            console.error("Upgrade payment verification failed", error);
            toast.error(
              "Payment received. If your plan doesn't update in a few minutes, contact support@aspirova.org",
            );
          }
        },
      }).open();
      setPaymentRequired(null);
    } catch (error) {
      console.error("Could not open upgrade checkout", error);
      toast.error("Payments aren't available yet.");
    } finally {
      setConfirming(false);
    }
  }

  return (
    <>
      <Button
        type="button"
        variant={highlight ? "default" : "outline"}
        disabled={loading || paymentRequired !== null}
        className="w-full"
        onClick={handleUpgrade}
      >
        {loading && <Loader2 className="animate-spin" aria-hidden="true" />}
        {loading ? "Starting upgrade..." : `Upgrade to ${planLabel}`}
      </Button>

      <Dialog
        open={paymentRequired !== null}
        onOpenChange={(open) => {
          if (!open && !confirming) setPaymentRequired(null);
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              Upgrade from {currentPlanLabel} to {planLabel}?
            </DialogTitle>
            <DialogDescription className="space-y-3">
              <span className="block">
                You&apos;ll pay {paymentRequired && formatUpgradeAmount(paymentRequired.amount_paise)}
                today. This covers only the remainder of your current billing period.
              </span>
              <span className="block">
                Your renewal date does not change. From that renewal onward, you&apos;ll be billed
                the {planLabel} plan price.
              </span>
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <DialogClose asChild>
              <Button variant="outline" disabled={confirming}>
                Keep current plan
              </Button>
            </DialogClose>
            <Button disabled={confirming} onClick={() => void handleConfirmUpgrade()}>
              {confirming && <Loader2 className="animate-spin" aria-hidden="true" />}
              {confirming ? "Opening payment..." : "Continue to payment"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
