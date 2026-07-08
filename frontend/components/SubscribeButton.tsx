"use client";

import { Loader2 } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import HeaderAuth from "@/components/HeaderAuth";
import { Button } from "@/components/ui/button";
import { createCheckout } from "@/lib/api";
import { useSession } from "@/lib/useSession";

interface SubscribeButtonProps {
  planKey: string;
  planLabel: string;
  highlight?: boolean;
}

function isPaymentsUnavailableError(error: unknown): boolean {
  return error instanceof Error && error.message.endsWith(": 503");
}

async function waitForRazorpay(): Promise<Window["Razorpay"]> {
  if (typeof window === "undefined") return undefined;
  if (window.Razorpay) return window.Razorpay;

  for (let attempt = 0; attempt < 10; attempt += 1) {
    await new Promise((resolve) => window.setTimeout(resolve, 300));
    if (window.Razorpay) return window.Razorpay;
  }

  return window.Razorpay;
}

export default function SubscribeButton({
  planKey,
  planLabel,
  highlight,
}: SubscribeButtonProps) {
  const session = useSession();
  const accessToken = session?.access_token;
  const [loading, setLoading] = useState(false);

  if (!session) {
    return (
      <HeaderAuth
        triggerLabel="Sign in to subscribe"
        triggerVariant={highlight ? "default" : "outline"}
        triggerClassName="w-full"
      />
    );
  }

  async function handleSubscribe() {
    if (!accessToken) {
      toast.error("Please sign in again to subscribe.");
      return;
    }

    setLoading(true);
    try {
      const Razorpay = await waitForRazorpay();
      if (!Razorpay) {
        toast.error("Payments aren't available yet.");
        return;
      }

      const { razorpay_key_id, razorpay_subscription_id } = await createCheckout(
        planKey,
        accessToken,
      );

      new Razorpay({
        key: razorpay_key_id,
        subscription_id: razorpay_subscription_id,
        name: "Aspirova",
        description: `${planLabel} subscription`,
        theme: { color: "#2563eb" },
        handler: () => {
          toast.success("Payment received — your plan activates in a moment", {
            description: "Refresh in a few seconds once it's confirmed.",
          });
        },
      }).open();
    } catch (error: unknown) {
      if (isPaymentsUnavailableError(error)) {
        toast.error("Payments aren't available yet.");
      } else {
        toast.error("Couldn't start checkout. Please try again.");
      }
    } finally {
      setLoading(false);
    }
  }

  return (
    <Button
      type="button"
      variant={highlight ? "default" : "outline"}
      disabled={loading}
      className="w-full"
      onClick={handleSubscribe}
    >
      {loading && <Loader2 className="animate-spin" aria-hidden="true" />}
      {loading ? "Starting checkout..." : `Upgrade to ${planLabel}`}
    </Button>
  );
}
