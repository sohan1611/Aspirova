"use client";

import {
  Bell,
  CreditCard,
  Shield,
  UserRound,
  type LucideIcon,
} from "lucide-react";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { cn } from "@/lib/utils";

export const ACCOUNT_SECTIONS = [
  { key: "profile", label: "Profile", Icon: UserRound },
  { key: "subscription", label: "Subscription", Icon: CreditCard },
  { key: "notifications", label: "Notifications", Icon: Bell },
  { key: "security", label: "Security", Icon: Shield },
] as const satisfies ReadonlyArray<{
  key: string;
  label: string;
  Icon: LucideIcon;
}>;

export type AccountSectionKey = (typeof ACCOUNT_SECTIONS)[number]["key"];

export function isAccountSection(value: string | null): value is AccountSectionKey {
  return ACCOUNT_SECTIONS.some((section) => section.key === value);
}

export default function AccountSidebar({
  activeSection,
  onSectionChange,
}: {
  activeSection: AccountSectionKey;
  onSectionChange: (section: AccountSectionKey) => void;
}) {
  return (
    <>
      <div className="md:hidden">
        <Select
          value={activeSection}
          onValueChange={(value) => {
            if (isAccountSection(value)) onSectionChange(value);
          }}
        >
          <SelectTrigger className="w-full" aria-label="Account section">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {ACCOUNT_SECTIONS.map(({ key, label, Icon }) => (
              <SelectItem key={key} value={key}>
                <Icon aria-hidden="true" />
                {label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      <aside className="hidden md:block">
        <div className="sticky top-24">
          <p className="eyebrow mb-2 px-3">Settings</p>
          <nav
            aria-label="Account settings"
            className="grid gap-1 rounded-xl border border-border bg-card p-2 shadow-soft"
          >
            {ACCOUNT_SECTIONS.map(({ key, label, Icon }) => (
              <button
                key={key}
                type="button"
                aria-current={activeSection === key ? "page" : undefined}
                onClick={() => onSectionChange(key)}
                className={cn(
                  "flex w-full items-center gap-3 rounded-lg border-l-2 px-3 py-2.5 text-left text-sm font-medium outline-none transition-colors duration-200 ease-premium focus-visible:ring-2 focus-visible:ring-ring",
                  activeSection === key
                    ? "border-primary bg-primary/10 text-primary"
                    : "border-transparent text-muted-foreground hover:bg-accent hover:text-foreground",
                )}
              >
                <Icon className="size-4" aria-hidden="true" />
                {label}
              </button>
            ))}
          </nav>
        </div>
      </aside>
    </>
  );
}
