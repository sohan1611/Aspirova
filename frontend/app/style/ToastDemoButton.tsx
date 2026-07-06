"use client";

import { toast } from "sonner";
import { Button } from "@/components/ui/button";

export function ToastDemoButton() {
  return (
    <Button variant="outline" onClick={() => toast("Bookmark saved")}>
      Trigger toast
    </Button>
  );
}
