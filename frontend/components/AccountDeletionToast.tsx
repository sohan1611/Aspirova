"use client";

import { useEffect } from "react";
import { toast } from "sonner";

export default function AccountDeletionToast() {
  useEffect(() => {
    const url = new URL(window.location.href);
    if (url.pathname !== "/" || url.searchParams.get("account") !== "deleted") return;
    url.searchParams.delete("account");
    window.history.replaceState(window.history.state, "", `${url.pathname}${url.search}${url.hash}`);
    toast.success("Your account has been deleted.");
  }, []);
  return null;
}
