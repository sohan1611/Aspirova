"use client";

import { Eye, EyeOff } from "lucide-react";
import { useState, type ComponentProps } from "react";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

type PasswordInputProps = Omit<ComponentProps<typeof Input>, "type">;

export function PasswordInput({
  className,
  disabled,
  ...props
}: PasswordInputProps) {
  const [revealed, setRevealed] = useState(false);

  return (
    <div className="relative">
      <Input
        {...props}
        disabled={disabled}
        type={revealed ? "text" : "password"}
        className={cn("pr-9", className)}
      />
      <button
        type="button"
        onClick={() => setRevealed((visible) => !visible)}
        aria-label={revealed ? "Hide password" : "Show password"}
        disabled={disabled}
        className="absolute top-1/2 right-2 -translate-y-1/2 text-muted-foreground hover:text-foreground disabled:pointer-events-none disabled:opacity-50"
      >
        {revealed ? (
          <EyeOff className="h-4 w-4" aria-hidden="true" />
        ) : (
          <Eye className="h-4 w-4" aria-hidden="true" />
        )}
      </button>
    </div>
  );
}
