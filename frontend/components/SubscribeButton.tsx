"use client";

import { Loader2 } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import HeaderAuth from "@/components/HeaderAuth";
import { Button } from "@/components/ui/button";
import { createCheckout, getAccount, isCheckoutConflictError } from "@/lib/api";
import { useSession } from "@/lib/useSession";

interface SubscribeButtonProps {
  planKey: string;
  planLabel: string;
  highlight?: boolean;
  label?: string;
  onSubscribed?: () => Promise<void>;
}

export function isPaymentsUnavailableError(error: unknown): boolean {
  return error instanceof Error && error.message.endsWith(": 503");
}

export async function waitForRazorpay(): Promise<Window["Razorpay"]> {
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
  label,
  onSubscribed,
}: SubscribeButtonProps) {
  const router = useRouter();
  const session = useSession();
  const accessToken = session?.access_token;
  const [status, setStatus] = useState<"idle" | "starting" | "checkout" | "confirming">("idle");
  const operationRef = useRef(0);
  const stopConfirmationRef = useRef<(() => void) | null>(null);
  const loading = status !== "idle";

  useEffect(() => {
    return () => {
      operationRef.current += 1;
      stopConfirmationRef.current?.();
    };
  }, []);

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

    const checkoutAccessToken = accessToken;
    const operation = ++operationRef.current;
    const isCurrent = () => operationRef.current === operation;
    setStatus("starting");
    try {
      const Razorpay = await waitForRazorpay();
      if (!isCurrent()) return;
      if (!Razorpay) {
        toast.error("Payments aren't available yet.");
        setStatus("idle");
        return;
      }

      const { razorpay_key_id, razorpay_subscription_id } = await createCheckout(
        planKey,
        checkoutAccessToken,
      );
      if (!isCurrent()) return;

      let submitted = false;

      setStatus("checkout");
      new Razorpay({
        key: razorpay_key_id,
        subscription_id: razorpay_subscription_id,
        name: "Aspirova",
        description: `${planLabel} subscription`,
        theme: { color: "#2563eb" },
        handler: () => {
          if (!isCurrent() || submitted) return;
          submitted = true;
          setStatus("confirming");
          toast.info("Checkout submitted — confirming your subscription…");

          const controller = new AbortController();
          let pollTimer: ReturnType<typeof setTimeout> | undefined;
          const stop = () => {
            controller.abort();
            clearTimeout(pollTimer);
            clearTimeout(timeoutTimer);
            stopConfirmationRef.current = null;
          };
          const timeoutTimer = setTimeout(() => {
            stop();
            if (!isCurrent()) return;
            setStatus("idle");
            toast.info("Still confirming with Razorpay. Your plan will update shortly — refresh in a minute.");
          }, 60_000);
          stopConfirmationRef.current = stop;

          async function poll() {
            try {
              const account = await getAccount(checkoutAccessToken, controller.signal);
              if (!isCurrent() || controller.signal.aborted) return;
              if (account.plan.key === planKey && account.plan.status === "active") {
                stop();
                toast.success(`${planLabel} is active`);
                router.refresh();
                // Refresh client-owned pricing state as well as server components.
                try {
                  await onSubscribed?.();
                } finally {
                  if (isCurrent()) setStatus("idle");
                }
                return;
              }
            } catch {
              // A transient account read failure is still pending confirmation.
            }
            if (isCurrent() && !controller.signal.aborted) {
              pollTimer = setTimeout(() => void poll(), 3_000);
            }
          }

          void poll();
        },
        modal: {
          ondismiss: () => {
            if (isCurrent() && !submitted) {
              operationRef.current += 1;
              setStatus("idle");
            }
          },
        },
      }).open();
    } catch (error: unknown) {
      if (!isCurrent()) return;
      setStatus("idle");
      if (isPaymentsUnavailableError(error)) {
        toast.error("Payments aren't available yet.");
      } else if (isCheckoutConflictError(error)) {
        toast.error(error.message);
      } else {
        toast.error("Couldn't start checkout. Please try again.");
      }
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
      {status === "confirming" ? "Confirming…" : loading ? "Starting checkout..." : (label ?? `Upgrade to ${planLabel}`)}
    </Button>
  );
}
