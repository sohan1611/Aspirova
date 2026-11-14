"use client";

import { ExternalLink, FileText, Loader2, Lock, RefreshCw, Trash2, TriangleAlert, Upload } from "lucide-react";
import Link from "next/link";
import { type ChangeEvent, useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { ConfirmDialog, SectionHeader, SettingsCard } from "@/components/account/primitives";
import ScoreRing from "@/components/ScoreRing";
import { Button } from "@/components/ui/button";
import { updateAccount } from "@/lib/api";
import { computeAtsScore } from "@/lib/atsScore";
import { useFieldProfile } from "@/lib/fieldProfile";
import { extractPdfText, PdfTextExtractionError } from "@/lib/pdfText";
import { storeSkillNames } from "@/lib/personalizationSkills";
import { extractSkills } from "@/lib/resumeSkills";
import {
  formatSavedResumeUploadedAt, mergeSkills, openResumePdf, removeResumePdf,
  uploadResumePdf, validateResumePdf, type ProfileSkill,
} from "@/lib/savedResume";
import { expandToSearchTerms } from "@/lib/taxonomy";
import type { AccountMe, ResumeMeta } from "@/lib/types";

export default function ResumeSection({
  account,
  accessToken,
  userId,
  onAccountChange,
}: {
  account: AccountMe;
  accessToken: string;
  userId: string;
  onAccountChange: (account: AccountMe) => void;
}) {
  const { profile } = useFieldProfile();
  const inputRef = useRef<HTMLInputElement>(null);
  const removeButtonRef = useRef<HTMLButtonElement>(null);
  const [phase, setPhase] = useState<"checking" | "reading" | "uploading" | "saving" | null>(null);
  const [uploading, setUploading] = useState(false);
  const [opening, setOpening] = useState(false);
  const [removing, setRemoving] = useState(false);
  const [savingDetails, setSavingDetails] = useState(false);
  const [removeDialogOpen, setRemoveDialogOpen] = useState(false);
  const [pendingResumeSave, setPendingResumeSave] = useState<{
    meta: ResumeMeta;
    skills: ProfileSkill[];
  } | null>(null);
  const resume = pendingResumeSave?.meta ?? account.resume;
  const busy = uploading || removing || savingDetails;
  const hasUnsavedChanges = busy || pendingResumeSave !== null;

  useEffect(() => {
    if (!hasUnsavedChanges) return;
    const beforeUnload = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", beforeUnload);
    return () => window.removeEventListener("beforeunload", beforeUnload);
  }, [hasUnsavedChanges]);

  async function saveResumeDetails(meta: ResumeMeta, skills: ProfileSkill[]) {
    const updated = await updateAccount(accessToken, { skills, resume: meta });
    onAccountChange(updated);
    const persistedSkills = mergeSkills(updated.skills ?? skills);
    storeSkillNames(persistedSkills.map((skill) => skill.name));
    setPendingResumeSave(null);
  }

  async function retryResumeSave() {
    if (!pendingResumeSave || busy) return;
    setSavingDetails(true);
    try {
      await saveResumeDetails(pendingResumeSave.meta, pendingResumeSave.skills);
      toast.success("Resume saved");
    } catch {
      toast.error("We couldn't save your resume details. Please try again.");
    } finally {
      setSavingDetails(false);
    }
  }

  async function handlePdfChange(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file || busy) return;

    setUploading(true);
    let uploadedMeta: ResumeMeta | null = null;
    let uploadedSkills: ProfileSkill[] = [];
    try {
      setPhase("checking");
      const validationError = await validateResumePdf(file);
      if (validationError) {
        toast.error(validationError);
        return;
      }

      setPhase("reading");
      const text = await extractPdfText(file);
      const ats = computeAtsScore(text, expandToSearchTerms(profile));
      const nextSkills = mergeSkills(account.skills, extractSkills(text));
      setPhase("uploading");
      const path = await uploadResumePdf(userId, file);
      const meta: ResumeMeta = {
        path,
        filename: file.name,
        uploaded_at: new Date().toISOString(),
        ats,
      };
      uploadedMeta = meta;
      uploadedSkills = nextSkills;
      setPhase("saving");
      await saveResumeDetails(meta, nextSkills);
      toast.success("Resume saved", {
        description: "Your private PDF, skills, and ATS estimate were updated.",
      });
    } catch (error: unknown) {
      if (error instanceof PdfTextExtractionError) {
        toast.error("We couldn't read text from that PDF.", {
          description: "Try a text-based PDF, or paste your resume text on Matches.",
        });
      } else if (uploadedMeta) {
        let removed = false;
        if (!account.resume) {
          try {
            await removeResumePdf(uploadedMeta.path);
            removed = true;
          } catch {
            // Keep a retry path if cleanup could not be confirmed.
          }
        }
        if (removed) {
          setPendingResumeSave(null);
          toast.error("We couldn't save your resume, so we didn't keep the file. Please try again.");
        } else {
          setPendingResumeSave({ meta: uploadedMeta, skills: uploadedSkills });
        }
      } else {
        toast.error("We couldn't store your resume PDF.", {
          description: "No resume metadata was saved. Try again in a moment.",
        });
      }
    } finally {
      setUploading(false);
      setPhase(null);
    }
  }

  async function handleViewResume() {
    if (!resume || busy || opening) return;
    setOpening(true);
    try {
      await openResumePdf(resume.path);
    } catch {
      toast.error("We couldn't open your saved resume. Please try again.");
    } finally {
      setOpening(false);
    }
  }

  async function handleRemoveResume() {
    if (!resume || busy) return;
    setRemoving(true);
    let fileRemoved = false;
    try {
      await removeResumePdf(resume.path);
      fileRemoved = true;
      setPendingResumeSave(null);
      const updated = await updateAccount(accessToken, { resume: null });
      onAccountChange(updated);
      setRemoveDialogOpen(false);
      toast.success("Your resume has been removed.");
    } catch {
      toast.error(
        fileRemoved
          ? "Your file was removed, but we couldn't update your account. Please refresh."
          : "We couldn't remove your resume. Please try again.",
      );
    } finally {
      setRemoving(false);
    }
  }

  const phaseLabel = phase === "checking" ? "Checking your file…"
    : phase === "reading" ? "Reading text…"
    : phase === "uploading" ? "Uploading securely…"
    : "Saving details…";

  return (
    <section aria-labelledby="account-resume-heading" className="grid gap-6">
      <SectionHeader id="account-resume-heading" eyebrow="You" title="Resume" description="Your private PDF and ATS readiness estimate. Only you can open it." />
      <input ref={inputRef} type="file" accept="application/pdf,.pdf" aria-label="Upload resume PDF" className="sr-only" tabIndex={-1} disabled={busy} onChange={(event) => void handlePdfChange(event)} />

      {pendingResumeSave && (
        <div role="alert" className="flex items-start gap-3 rounded-xl border border-warning/40 bg-warning/10 p-4 text-sm">
          <TriangleAlert className="mt-0.5 size-5 shrink-0 text-warning-foreground dark:text-warning" aria-hidden="true" />
          <div className="grid min-w-0 gap-3">
            <p>Your new PDF is stored, but its details didn&apos;t save, so your ATS estimate may be out of date.</p>
            <Button type="button" variant="outline" className="w-fit" disabled={busy} onClick={() => void retryResumeSave()}>
              {savingDetails && <Loader2 className="animate-spin" aria-hidden="true" />}
              {savingDetails ? "Saving…" : "Try again"}
            </Button>
          </div>
        </div>
      )}

      <SettingsCard icon={FileText} title="Your resume" footer={resume && (
        <>
          <Button type="button" variant="soft" disabled={busy || opening} onClick={() => void handleViewResume()}>
            {opening ? <Loader2 className="animate-spin" aria-hidden="true" /> : <ExternalLink aria-hidden="true" />}
            {opening ? "Opening…" : "View"}
          </Button>
          <Button type="button" variant="outline" disabled={busy} onClick={() => inputRef.current?.click()}>
            {uploading || savingDetails ? <Loader2 className="animate-spin" aria-hidden="true" /> : <RefreshCw aria-hidden="true" />}
            {uploading || savingDetails ? "Replacing…" : "Replace"}
          </Button>
          <Button ref={removeButtonRef} type="button" variant="destructive-ghost" disabled={busy} onClick={() => setRemoveDialogOpen(true)}><Trash2 aria-hidden="true" />Remove</Button>
        </>
      )}>
        {uploading || savingDetails ? (
          <div role="status" aria-live="polite" className="grid min-h-44 content-center gap-4 px-2 py-8 sm:px-8">
            <div className="h-1.5 overflow-hidden rounded-full bg-muted" aria-hidden="true"><div className="animate-account-upload h-full w-2/5 rounded-full bg-primary" /></div>
            <p className="text-center text-sm font-medium text-muted-foreground">{phaseLabel}</p>
          </div>
        ) : resume ? (
          <div className="flex min-w-0 flex-col gap-6 py-2 sm:flex-row sm:items-center sm:justify-between">
            <div className="flex min-w-0 flex-1 items-start gap-3">
              <span className="flex size-11 shrink-0 items-center justify-center rounded-lg bg-destructive/10 text-destructive-text"><FileText className="size-5" aria-hidden="true" /></span>
              <div className="min-w-0">
                <p className="break-words font-medium text-foreground [overflow-wrap:anywhere]">{resume.filename}</p>
                <p className="mt-1 text-sm text-muted-foreground">{formatSavedResumeUploadedAt(resume.uploaded_at)}</p>
              </div>
            </div>
            <div className="grid shrink-0 justify-items-center gap-1.5 border-t border-border pt-5 text-center sm:max-w-44 sm:border-t-0 sm:border-l sm:pt-0 sm:pl-5">
              <ScoreRing size="sm" score={resume.ats.score} />
              <p className="text-xs text-muted-foreground">ATS readiness estimate</p>
              <Link href="/resume" className="inline-flex min-h-11 items-center rounded text-xs font-medium text-primary underline-offset-4 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring sm:min-h-0">Full check on Matches →</Link>
            </div>
          </div>
        ) : (
          <button type="button" disabled={busy} onClick={() => inputRef.current?.click()} className="group min-h-11 w-full rounded-xl border border-border bg-muted/30 p-6 text-left outline-none transition-colors duration-200 ease-premium hover:bg-muted/50 focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50 sm:p-8 sm:text-center">
            <span className="mb-5 inline-flex size-12 items-center justify-center rounded-2xl bg-primary/10 text-primary ring-8 ring-primary/5"><Upload className="size-6" aria-hidden="true" /></span>
            <span className="block font-serif text-xl font-semibold text-foreground">Upload your resume</span>
            <span className="mt-2 block text-sm text-muted-foreground">PDF only, up to 5 MB. Stored privately in your account.</span>
            <span className="mt-6 inline-flex min-h-11 items-center rounded-full bg-primary px-5 text-sm font-semibold text-primary-foreground">Choose PDF</span>
          </button>
        )}
      </SettingsCard>

      <p className="flex items-start gap-2 px-1 text-sm text-muted-foreground"><Lock className="mt-0.5 size-4 shrink-0 text-primary" aria-hidden="true" /><span>Only you can open your PDF. Skills you keep stay on your account even if you remove it.</span></p>

      <ConfirmDialog open={removeDialogOpen} onOpenChange={setRemoveDialogOpen} title="Remove your resume?" description={<>This deletes the saved PDF and your resume check score. The skills you&apos;ve kept stay on your account.</>} confirmLabel="Remove" pendingLabel="Removing…" pending={removing} onConfirm={handleRemoveResume} onCloseAutoFocus={(event) => {
        event.preventDefault();
        const target = removeButtonRef.current ?? document.getElementById("account-resume-heading");
        target?.focus({ preventScroll: true });
      }} />
    </section>
  );
}
