"use client";

import { Loader2 } from "lucide-react";
import { type FormEvent, useState } from "react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { submitBugReport } from "@/lib/api";
import { useSession } from "@/lib/useSession";
import type { BugReportCategory } from "@/lib/types";

const REPORT_CATEGORIES: Array<{ value: BugReportCategory; label: string }> = [
  { value: "dead_link", label: "Dead link" },
  { value: "wrong_info", label: "Wrong info" },
  { value: "bug", label: "Something's broken" },
  { value: "other", label: "Other" },
];

interface ReportIssueFormProps {
  opportunitySlug?: string;
}

export function ReportIssueForm({ opportunitySlug }: ReportIssueFormProps) {
  const session = useSession();
  const [category, setCategory] = useState<BugReportCategory>("dead_link");
  const [message, setMessage] = useState("");
  const [contactEmail, setContactEmail] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [submitted, setSubmitted] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmedMessage = message.trim();

    if (!trimmedMessage) {
      setError("Please describe the problem before sending your report.");
      return;
    }

    setError(null);
    setSubmitting(true);

    try {
      await submitBugReport(
        {
          category,
          message: trimmedMessage,
          ...(opportunitySlug ? { opportunity_slug: opportunitySlug } : {}),
          page_url: window.location.href,
          ...(contactEmail.trim() ? { contact_email: contactEmail.trim() } : {}),
        },
        session?.access_token,
      );
      setSubmitted(true);
    } catch {
      setError("We couldn't send your report. Please try again.");
    } finally {
      setSubmitting(false);
    }
  }

  if (submitted) {
    return (
      <div
        className="rounded-lg border border-primary/20 bg-primary/5 p-4"
        role="status"
        aria-live="polite"
      >
        <p className="font-medium text-foreground">Thanks — we&apos;ll look into it.</p>
        <p className="mt-1 text-sm leading-6 text-muted-foreground">
          Your report has been sent straight to the founder.
        </p>
      </div>
    );
  }

  return (
    <form onSubmit={handleSubmit} className="grid gap-5">
      <div className="grid gap-2">
        <Label htmlFor="report-category">What happened?</Label>
        <Select
          value={category}
          onValueChange={(value) => setCategory(value as BugReportCategory)}
        >
          <SelectTrigger id="report-category" className="w-full" aria-label="Report category">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {REPORT_CATEGORIES.map((reportCategory) => (
              <SelectItem key={reportCategory.value} value={reportCategory.value}>
                {reportCategory.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      <div className="grid gap-2">
        <Label htmlFor="report-message">What should we fix?</Label>
        <Textarea
          id="report-message"
          required
          maxLength={2000}
          value={message}
          onChange={(event) => setMessage(event.target.value)}
          placeholder="Tell us what happened, and include any details that could help us fix it."
          aria-describedby="report-message-help"
          aria-invalid={error ? true : undefined}
        />
        <p id="report-message-help" className="text-xs leading-5 text-muted-foreground">
          {message.length}/2000 characters
        </p>
      </div>

      <div className="grid gap-2">
        <Label htmlFor="report-contact-email">Email (optional)</Label>
        <Input
          id="report-contact-email"
          type="email"
          value={contactEmail}
          onChange={(event) => setContactEmail(event.target.value)}
          placeholder="you@example.com"
          autoComplete="email"
          aria-describedby="report-contact-help"
        />
        <p id="report-contact-help" className="text-xs leading-5 text-muted-foreground">
          Add an email only if you&apos;d like us to follow up.
        </p>
      </div>

      {error && (
        <p
          className="rounded-md border border-destructive/30 bg-destructive/5 px-3 py-2 text-sm text-destructive"
          role="alert"
        >
          {error}
        </p>
      )}

      <div>
        <Button type="submit" disabled={submitting}>
          {submitting && <Loader2 className="animate-spin" aria-hidden="true" />}
          {submitting ? "Sending…" : "Send report"}
        </Button>
      </div>
    </form>
  );
}

export default function ReportIssueDialog({ opportunitySlug }: ReportIssueFormProps) {
  return (
    <Dialog>
      <DialogTrigger asChild>
        <Button
          type="button"
          variant="ghost"
          size="sm"
          className="text-xs text-muted-foreground hover:text-foreground"
        >
          Report an issue
        </Button>
      </DialogTrigger>
      <DialogContent className="max-h-[calc(100vh-2rem)] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>Report an issue</DialogTitle>
          <DialogDescription>
            Found a dead link or something inaccurate? Your report goes straight to the founder.
          </DialogDescription>
        </DialogHeader>
        <ReportIssueForm opportunitySlug={opportunitySlug} />
      </DialogContent>
    </Dialog>
  );
}
