"use client";

import * as React from "react";
import { Loader2, TriangleAlert, type LucideIcon } from "lucide-react";
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent,
  AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { cn } from "@/lib/utils";

export function SectionHeader({ eyebrow, title, description, action, id, headingRef }: {
  eyebrow: string; title: string; description: string; action?: React.ReactNode;
  id?: string; headingRef?: React.Ref<HTMLHeadingElement>;
}) {
  return (
    <header className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
      <div className="min-w-0">
        <p className="eyebrow mb-1.5">{eyebrow}</p>
        <h2 ref={headingRef} id={id} tabIndex={-1} className="font-serif text-2xl font-bold tracking-tight outline-none focus-visible:ring-2 focus-visible:ring-ring sm:text-3xl">{title}</h2>
        <p className="mt-1 max-w-prose text-sm text-muted-foreground">{description}</p>
      </div>
      {action && <div className="shrink-0 sm:pt-6">{action}</div>}
    </header>
  );
}

export function SettingsCard({ icon: Icon, title, description, action, footer, tone = "default", children, className, bodyClassName }: {
  icon?: LucideIcon; title: string; description?: React.ReactNode; action?: React.ReactNode;
  footer?: React.ReactNode; tone?: "default" | "danger"; children?: React.ReactNode;
  className?: string; bodyClassName?: string;
}) {
  return (
    <div className={cn("overflow-hidden rounded-xl border border-border bg-card shadow-soft", tone === "danger" && "border-destructive/30 bg-destructive/[0.03]", className)}>
      <div className="flex flex-wrap items-start gap-3 px-5 pt-5 pb-4 sm:px-6 sm:pt-6">
        {Icon && <span className={cn("flex size-9 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary", tone === "danger" && "bg-destructive/10 text-destructive-text")}><Icon className="size-4" aria-hidden="true" /></span>}
        <div className="min-w-0 flex-1">
          <h3 className={cn("font-semibold text-foreground", tone === "danger" && "text-destructive-text")}>{title}</h3>
          {description && <div className="mt-1 text-sm text-muted-foreground">{description}</div>}
        </div>
        {action && <div className="shrink-0">{action}</div>}
      </div>
      {children && <div className={cn("px-5 pb-5 sm:px-6 sm:pb-6", bodyClassName)}>{children}</div>}
      {footer && <div className="flex flex-wrap items-center justify-end gap-2 border-t border-border bg-muted/40 px-5 py-3 sm:px-6">{footer}</div>}
    </div>
  );
}

export function SettingsRow({ label, htmlFor, description, children, align = "center" }: {
  label: string; htmlFor?: string; description?: React.ReactNode; children: React.ReactNode;
  align?: "center" | "start";
}) {
  return (
    <div className={cn("grid gap-3 py-4 sm:grid-cols-[minmax(0,14rem)_minmax(0,1fr)] sm:gap-x-8", align === "center" ? "sm:items-center" : "sm:items-start")}>
      <div>
        {htmlFor ? <label htmlFor={htmlFor} className="text-sm font-medium text-foreground">{label}</label> : <p className="text-sm font-medium text-foreground">{label}</p>}
        {description && <div className="mt-1 text-sm text-muted-foreground">{description}</div>}
      </div>
      <div className="min-w-0">{children}</div>
    </div>
  );
}

const pillTones = {
  success: "border-success/25 bg-success/10 text-success dark:text-foreground",
  warning: "border-warning/25 bg-warning/10 text-warning-foreground dark:text-foreground",
  muted: "border-border bg-muted text-muted-foreground",
  destructive: "border-destructive/25 bg-destructive/10 text-destructive-text",
  primary: "border-primary/25 bg-primary/10 text-primary",
};
const dotTones = { success: "bg-success", warning: "bg-warning", muted: "bg-muted-foreground", destructive: "bg-destructive", primary: "bg-primary" };

export function StatusPill({ tone, children }: { tone: keyof typeof pillTones; children: React.ReactNode }) {
  return <span className={cn("inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-xs font-medium", pillTones[tone])}><span aria-hidden="true" className={cn("size-1.5 shrink-0 rounded-full", dotTones[tone])} />{children}</span>;
}

export function EmptyState({ icon: Icon, title, description, action, secondaryAction, compact = false, tone = "default" }: {
  icon: LucideIcon; title: string; description: string; action?: React.ReactNode;
  secondaryAction?: React.ReactNode; compact?: boolean; tone?: "default" | "destructive";
}) {
  return (
    <div className={cn("flex flex-col items-center text-center", compact ? "px-2 py-6" : "px-5 py-10 sm:px-8 sm:py-12")}>
      <span className={cn("mb-6 flex size-12 items-center justify-center rounded-2xl ring-8", tone === "destructive" ? "bg-destructive/10 text-destructive-text ring-destructive/5" : "bg-primary/10 text-primary ring-primary/5")}><Icon className="size-6" aria-hidden="true" /></span>
      <h3 className="font-serif text-lg font-semibold text-foreground">{title}</h3>
      <p className="mt-2 max-w-sm text-sm text-muted-foreground">{description}</p>
      {(action || secondaryAction) && <div className="mt-6 flex flex-wrap items-center justify-center gap-2">{action}{secondaryAction}</div>}
    </div>
  );
}

export function ConfirmDialog({ open, onOpenChange, title, description, confirmLabel, pendingLabel, cancelLabel = "Cancel", onConfirm, pending, tone = "destructive", icon: Icon = TriangleAlert, children, onCloseAutoFocus }: {
  open: boolean; onOpenChange: (open: boolean) => void; title: string; description: React.ReactNode;
  confirmLabel: string; pendingLabel: string; cancelLabel?: string; onConfirm: () => void | Promise<void>;
  pending: boolean; tone?: "destructive" | "default"; icon?: LucideIcon; children?: React.ReactNode;
  onCloseAutoFocus?: React.ComponentProps<typeof AlertDialogContent>["onCloseAutoFocus"];
}) {
  return (
    <AlertDialog open={open} onOpenChange={(nextOpen) => { if (!pending || nextOpen) onOpenChange(nextOpen); }}>
      <AlertDialogContent onEscapeKeyDown={(event) => { if (pending) event.preventDefault(); }} onCloseAutoFocus={onCloseAutoFocus}>
        <AlertDialogHeader>
          <span className={cn("mb-2 flex size-11 items-center justify-center self-center rounded-full sm:self-start", tone === "destructive" ? "bg-destructive/10 text-destructive-text" : "bg-primary/10 text-primary")}><Icon className="size-5" aria-hidden="true" /></span>
          <AlertDialogTitle>{title}</AlertDialogTitle>
          <AlertDialogDescription asChild><div>{description}</div></AlertDialogDescription>
        </AlertDialogHeader>
        {children}
        <AlertDialogFooter>
          <AlertDialogCancel disabled={pending}>{cancelLabel}</AlertDialogCancel>
          <AlertDialogAction variant={tone === "destructive" ? "destructive" : "default"} disabled={pending} onClick={(event) => { event.preventDefault(); if (!pending) void onConfirm(); }}>
            {pending && <Loader2 className="animate-spin" aria-hidden="true" />}
            {pending ? pendingLabel : confirmLabel}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}

export function StrengthRing({ value, total, size = 88, children }: { value: number; total: number; size?: 64 | 72 | 88; children: React.ReactNode }) {
  const circumference = 2 * Math.PI * 46;
  const fraction = total > 0 ? Math.min(1, Math.max(0, value / total)) : 0;
  return (
    <div className="relative flex shrink-0 items-center justify-center" style={{ width: size, height: size }}>
      <svg viewBox="0 0 100 100" className="absolute inset-0 size-full -rotate-90" aria-hidden="true">
        <circle cx="50" cy="50" r="46" fill="none" strokeWidth="4" className="stroke-muted" />
        <circle cx="50" cy="50" r="46" fill="none" strokeWidth="4" strokeLinecap="round" strokeDasharray={circumference} strokeDashoffset={circumference * (1 - fraction)} className="stroke-primary transition-[stroke-dashoffset] duration-700 ease-premium" />
      </svg>
      {children}
    </div>
  );
}

export function Meter({ value, max, label, valueText, tone = "primary" }: {
  value: number; max: number; label: string; valueText: string; tone?: "primary" | "success" | "warning";
}) {
  const percentage = max > 0 ? Math.min(100, Math.max(0, value / max * 100)) : 0;
  return (
    <div className="h-1.5 overflow-hidden rounded-full bg-muted" role="progressbar" aria-label={label} aria-valuenow={value} aria-valuemin={0} aria-valuemax={max} aria-valuetext={valueText}>
      <div className={cn("h-full rounded-full transition-[width] duration-500 ease-premium", tone === "success" ? "bg-success" : tone === "warning" ? "bg-warning" : "bg-primary")} style={{ width: percentage + "%" }} />
    </div>
  );
}
