"use client";

import { ExternalLink, FileText, Loader2, RefreshCw, Trash2, Upload } from "lucide-react";
import Link from "next/link";
import { type ChangeEvent, useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { updateAccount } from "@/lib/api";
import { computeAtsScore } from "@/lib/atsScore";
import { useFieldProfile } from "@/lib/fieldProfile";
import { extractPdfText, PdfTextExtractionError } from "@/lib/pdfText";
import { storeSkillNames } from "@/lib/personalizationSkills";
import { extractSkills } from "@/lib/resumeSkills";
import {
  formatSavedResumeUploadedAt,
  mergeSkills,
  openResumePdf,
  removeResumePdf,
  uploadResumePdf,
  validateResumePdf,
  type ProfileSkill,
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
      const validationError = await validateResumePdf(file);
      if (validationError) {
        toast.error(validationError);
        return;
      }

      const text = await extractPdfText(file);
      const ats = computeAtsScore(text, expandToSearchTerms(profile));
      const nextSkills = mergeSkills(account.skills, extractSkills(text));
      const path = await uploadResumePdf(userId, file);
      const meta: ResumeMeta = {
        path,
        filename: file.name,
        uploaded_at: new Date().toISOString(),
        ats,
      };
      uploadedMeta = meta;
      uploadedSkills = nextSkills;
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

  return (
    <section aria-labelledby="account-resume-heading">
      <Card>
        <CardHeader>
          <CardTitle className="font-serif text-2xl">
            <h2 id="account-resume-heading">Resume</h2>
          </CardTitle>
          <CardDescription>Your private PDF and ATS readiness estimate.</CardDescription>
        </CardHeader>
        <CardContent className="grid gap-6">
          <input
            ref={inputRef}
            type="file"
            accept="application/pdf,.pdf"
            aria-label="Upload resume PDF"
            className="sr-only"
            tabIndex={-1}
            disabled={busy}
            onChange={(event) => void handlePdfChange(event)}
          />

          {pendingResumeSave && (
            <div role="alert" className="grid gap-3 rounded-lg border border-warning/40 bg-warning/5 p-4 text-sm">
              <p>Your new PDF is stored, but its details didn&apos;t save, so your ATS estimate may be out of date.</p>
              <Button type="button" variant="outline" className="w-fit" disabled={busy} onClick={() => void retryResumeSave()}>
                {savingDetails && <Loader2 className="animate-spin" aria-hidden="true" />}
                {savingDetails ? "Saving..." : "Try again"}
              </Button>
            </div>
          )}

          {resume ? (
            <div className="flex min-w-0 items-start gap-3">
              <div className="flex size-10 shrink-0 items-center justify-center rounded-md bg-destructive/10 text-destructive">
                <FileText className="size-5" aria-hidden="true" />
              </div>
              <div className="grid min-w-0 gap-3">
                <div className="min-w-0">
                  <p className="break-words font-medium text-foreground [overflow-wrap:anywhere]">{resume.filename}</p>
                  <p className="mt-1 text-sm text-muted-foreground">
                    {formatSavedResumeUploadedAt(resume.uploaded_at)}
                  </p>
                </div>
                <Badge variant="outline" className="tnum max-w-full whitespace-normal border-primary/25 bg-accent text-accent-foreground">
                  {resume.ats.score}/100 ATS readiness estimate
                </Badge>
              </div>
            </div>
          ) : (
            <div className="grid gap-2">
              <p className="font-medium text-foreground">No resume is saved yet.</p>
              <p className="text-sm text-muted-foreground">PDF only, up to 5 MB. Stored privately in your account.</p>
            </div>
          )}

          <p className="text-sm text-muted-foreground">
            <Link href="/resume" className="underline underline-offset-4">
              See your skills and full resume check on Matches
            </Link>
          </p>

          <div className="flex flex-wrap items-center justify-end gap-3 border-t border-border pt-6">
            {resume && (
              <Button type="button" variant="outline" disabled={busy || opening} onClick={() => void handleViewResume()}>
                {opening ? <Loader2 className="animate-spin" aria-hidden="true" /> : <ExternalLink aria-hidden="true" />}
                {opening ? "Opening..." : "View"}
              </Button>
            )}
            <Button type="button" variant={resume ? "secondary" : "default"} disabled={busy} onClick={() => inputRef.current?.click()}>
              {uploading || savingDetails ? (
                <Loader2 className="animate-spin" aria-hidden="true" />
              ) : resume ? (
                <RefreshCw aria-hidden="true" />
              ) : (
                <Upload aria-hidden="true" />
              )}
              {uploading || savingDetails ? (resume ? "Replacing..." : "Uploading...") : (resume ? "Replace" : "Upload PDF")}
            </Button>
            {resume && (
              <Dialog open={removeDialogOpen} onOpenChange={(open) => {
                if (!removing) setRemoveDialogOpen(open);
              }}>
                <DialogTrigger asChild>
                  <Button type="button" variant="outline" disabled={busy}>
                    {removing ? <Loader2 className="animate-spin" aria-hidden="true" /> : <Trash2 aria-hidden="true" />}
                    {removing ? "Removing..." : "Remove"}
                  </Button>
                </DialogTrigger>
                <DialogContent showCloseButton={!removing}>
                  <DialogHeader>
                    <DialogTitle>Remove your resume?</DialogTitle>
                    <DialogDescription>
                      This deletes the saved PDF and your resume check score. The skills
                      you&apos;ve kept stay on your account.
                    </DialogDescription>
                  </DialogHeader>
                  <DialogFooter>
                    <DialogClose asChild>
                      <Button type="button" variant="outline" disabled={removing}>Cancel</Button>
                    </DialogClose>
                    <Button type="button" variant="destructive" disabled={busy} onClick={() => void handleRemoveResume()}>
                      {removing && <Loader2 className="animate-spin" aria-hidden="true" />}
                      {removing ? "Removing..." : "Remove"}
                    </Button>
                  </DialogFooter>
                </DialogContent>
              </Dialog>
            )}
          </div>
        </CardContent>
      </Card>
    </section>
  );
}
