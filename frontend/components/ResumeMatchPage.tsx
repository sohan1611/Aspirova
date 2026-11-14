"use client";

import {
  AlertTriangle,
  ArrowRight,
  FileText,
  Lightbulb,
  User,
  CheckCircle2,
  ChevronDown,
  ExternalLink,
  FileSearch,
  Loader2,
  RefreshCw,
  Search,
  Sparkles,
  Trash2,
  X,
  XCircle,
} from "lucide-react";
import HoverPrefetchLink from "@/components/HoverPrefetchLink";
import {
  type ChangeEvent,
  type FormEvent,
  type RefObject,
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
} from "react";
import { toast } from "sonner";
import HeaderAuth from "@/components/HeaderAuth";
import ProfileOpportunities from "@/components/ProfileOpportunities";
import SaveButton from "@/components/SaveButton";
import ScoreRing from "@/components/ScoreRing";
import { summarizeLocation } from "@/lib/location";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
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
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Textarea } from "@/components/ui/textarea";
import {
  getAccount,
  getResumeMatches,
  isProFeatureRequiredError,
  updateAccount,
  uploadResume,
} from "@/lib/api";
import { computeAtsScore, type AtsResult } from "@/lib/atsScore";
import { useFieldProfile } from "@/lib/fieldProfile";
import { extractPdfText, PdfTextExtractionError } from "@/lib/pdfText";
import { storeSkillNames } from "@/lib/personalizationSkills";
import { extractSkills } from "@/lib/resumeSkills";
import {
  formatSavedResumeUploadedAt,
  getSkillKey,
  MAX_PROFILE_SKILLS,
  mergeSkills,
  openResumePdf,
  removeResumePdf,
  uploadResumePdf,
  validateResumePdf,
  type ProfileSkill,
} from "@/lib/savedResume";
import { catalogSkills } from "@/lib/skillsCatalog";
import { expandToSearchTerms, getDivision, getStream, interestsFor, type FieldProfile } from "@/lib/taxonomy";
import type { AccountMe, MatchItem, ResumeMeta } from "@/lib/types";
import { useSession } from "@/lib/useSession";
import { cn } from "@/lib/utils";

// Embeddings are not generated while AI is deferred.
const RESUME_MATCHES_ENABLED = false;

type ExposureValues = {
  experience: string;
  notes: string;
};

const EMPTY_EXPOSURE: ExposureValues = {
  experience: "",
  notes: "",
};
const RESUME_PDF_INPUT_ID = "resume-pdf";

function areSkillsEqual(left: readonly ProfileSkill[], right: readonly ProfileSkill[]): boolean {
  return (
    left.length === right.length &&
    left.every(
      (skill, index) =>
        getSkillKey(skill.name) === getSkillKey(right[index].name) &&
        skill.source === right[index].source,
    )
  );
}

function toExposureValues(exposure: AccountMe["exposure"]): ExposureValues {
  return {
    experience: exposure?.experience ?? "",
    notes: exposure?.notes ?? "",
  };
}

function toSavedExposure(exposure: ExposureValues): NonNullable<AccountMe["exposure"]> {
  return {
    experience: exposure.experience.trim() || null,
    notes: exposure.notes.trim() || null,
  };
}

function areExposuresEqual(left: ExposureValues, right: ExposureValues): boolean {
  const savedLeft = toSavedExposure(left);
  const savedRight = toSavedExposure(right);

  return (
    savedLeft.experience === savedRight.experience && savedLeft.notes === savedRight.notes
  );
}

function getAtsStatusLabel(status: "pass" | "partial" | "fail"): string {
  if (status === "pass") return "Pass";
  if (status === "partial") return "Partial";
  return "Needs work";
}

function getAtsStatusClassName(status: "pass" | "partial" | "fail"): string {
  if (status === "pass") {
    return "border-primary/25 bg-primary/10 text-primary";
  }

  if (status === "partial") {
    return "border-primary/25 bg-accent text-accent-foreground";
  }

  return "border-border bg-secondary/70 text-muted-foreground";
}

function AtsStatusIcon({ status }: { status: "pass" | "partial" | "fail" }) {
  if (status === "pass") {
    return <CheckCircle2 className="size-4 shrink-0 text-success" aria-hidden="true" />;
  }

  if (status === "partial") {
    return <AlertTriangle className="size-4 shrink-0 text-warning" aria-hidden="true" />;
  }

  return <XCircle className="size-4 shrink-0 text-destructive" aria-hidden="true" />;
}

export default function ResumeMatchPage() {
  const session = useSession();

  return (
    <main className="mx-auto w-full max-w-7xl px-4 py-10 sm:px-6 sm:py-14 lg:px-8">
      <header className="max-w-3xl">
        <p className="eyebrow">Your resume</p>
        <h1 className="mt-4 font-serif text-4xl font-bold text-foreground sm:text-5xl">
          Matches
        </h1>
        <p className="mt-3 max-w-2xl text-sm leading-6 text-muted-foreground sm:text-base">
          Your resume, your skills, and the opportunities that fit them.
        </p>
      </header>

      <div className="mt-10 sm:mt-12">
        {!session ? (
          <SignedOutCard />
        ) : (
          <SignedInResumeWorkspace
            key={session.user.id}
            accessToken={session.access_token}
            userId={session.user.id}
          />
        )}
      </div>
    </main>
  );
}

function SignedInResumeWorkspace({
  accessToken,
  userId,
}: {
  accessToken: string;
  userId: string;
}) {
  const { profile, hydrated: profileHydrated } = useFieldProfile();
  const [resumeText, setResumeText] = useState("");
  const [readingPdf, setReadingPdf] = useState(false);
  const [shortPdfExtraction, setShortPdfExtraction] = useState(false);
  const [hasPdfExtraction, setHasPdfExtraction] = useState(false);
  const [skills, setSkills] = useState<ProfileSkill[]>([]);
  const [savedSkills, setSavedSkills] = useState<ProfileSkill[]>([]);
  const [exposure, setExposure] = useState<ExposureValues>(EMPTY_EXPOSURE);
  const [savedExposure, setSavedExposure] = useState<ExposureValues>(EMPTY_EXPOSURE);
  const [savedResume, setSavedResume] = useState<ResumeMeta | null>(null);
  const [pendingResumeSave, setPendingResumeSave] = useState<{ meta: ResumeMeta; skills: ProfileSkill[] } | null>(null);
  const [savingResumeDetails, setSavingResumeDetails] = useState(false);
  const [accountLoading, setAccountLoading] = useState(true);
  const [savingProfile, setSavingProfile] = useState(false);
  const [openingResume, setOpeningResume] = useState(false);
  const [removingResume, setRemovingResume] = useState(false);
  const [matches, setMatches] = useState<MatchItem[] | null>(null);
  const [matchesUpsell, setMatchesUpsell] = useState(false);
  const [submissionError, setSubmissionError] = useState(false);
  const [findingMatches, setFindingMatches] = useState(false);
  const matchFormRef = useRef<HTMLFormElement>(null);
  const exposureTouchedRef = useRef(false);
  const dismissedSkillNamesRef = useRef(new Set<string>());

  const profileTerms = useMemo(() => expandToSearchTerms(profile), [profile]);
  const hasResumeAnalysis = Boolean(resumeText.trim()) || hasPdfExtraction;
  const atsResult = useMemo(
    () =>
      hasResumeAnalysis
        ? computeAtsScore(resumeText, profileTerms)
        : null,
    [hasResumeAnalysis, profileTerms, resumeText],
  );
  const displayedAtsResult = atsResult ?? savedResume?.ats ?? null;
  const profileIsDirty = useMemo(
    () =>
      !areSkillsEqual(skills, savedSkills) ||
      !areExposuresEqual(exposure, savedExposure),
    [exposure, savedExposure, savedSkills, skills],
  );

  useEffect(() => {
    let cancelled = false;

    getAccount(accessToken)
      .then((account) => {
        if (cancelled) return;

        const accountSkills = mergeSkills(account.skills);
        const accountExposure = toExposureValues(account.exposure);

        setSavedSkills(accountSkills);
        setSavedResume(account.resume ?? null);
        storeSkillNames(accountSkills.map((skill) => skill.name), userId);
        setSavedExposure(accountExposure);
        setSkills((currentSkills) => mergeSkills(accountSkills, currentSkills));
        setExposure((currentExposure) =>
          exposureTouchedRef.current ? currentExposure : accountExposure,
        );
        setAccountLoading(false);
      })
      .catch(() => {
        if (cancelled) return;

        setSavedSkills([]);
        setSavedExposure(EMPTY_EXPOSURE);
        setSavedResume(null);
        setAccountLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [accessToken, userId]);

  function getSuggestedResumeSkills(text: string): ProfileSkill[] {
    return extractSkills(text).filter(
      (skill) => !dismissedSkillNamesRef.current.has(getSkillKey(skill.name)),
    );
  }

  function seedResumeSkills(text: string) {
    const suggestedSkills = getSuggestedResumeSkills(text);

    if (suggestedSkills.length === 0) return;

    setSkills((currentSkills) => mergeSkills(currentSkills, suggestedSkills));
  }

  async function saveResumeDetails(meta: ResumeMeta, nextSkills: ProfileSkill[]) {
    const account = await updateAccount(accessToken, {
      skills: nextSkills,
      resume: meta,
    });
    const persistedSkills = mergeSkills(account.skills ?? nextSkills);
    const accountExposure = toExposureValues(account.exposure);

    setSkills(persistedSkills);
    setSavedSkills(persistedSkills);
    storeSkillNames(persistedSkills.map((skill) => skill.name), userId);
    setSavedExposure(accountExposure);
    setExposure((currentExposure) =>
      exposureTouchedRef.current ? currentExposure : accountExposure,
    );
    setSavedResume(account.resume ?? meta);
    setPendingResumeSave(null);
  }

  async function retryResumeSave() {
    if (!pendingResumeSave || savingResumeDetails || readingPdf || removingResume) return;
    setSavingResumeDetails(true);
    try {
      await saveResumeDetails(pendingResumeSave.meta, pendingResumeSave.skills);
      toast.success("Resume saved");
    } catch {
      toast.error("We couldn't save your resume details. Please try again.");
    } finally {
      setSavingResumeDetails(false);
    }
  }

  async function handlePdfChange(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file || readingPdf || removingResume || savingResumeDetails) return;

    const validationError = await validateResumePdf(file);
    if (validationError === "Choose a PDF resume to continue.") {
      toast.error(validationError);
      return;
    }

    // Preserve the extraction reset after the PDF signature check, even for an
    // oversized file or a filename that is too long.
    setShortPdfExtraction(false);
    setHasPdfExtraction(false);
    if (validationError) {
      toast.error(validationError);
      return;
    }

    setReadingPdf(true);
    let uploaded = false;
    let uploadedMeta: ResumeMeta | null = null;
    let uploadedSkills: ProfileSkill[] = [];
    try {
      const extractedText = await extractPdfText(file);
      const suggestedSkills = getSuggestedResumeSkills(extractedText);
      const nextSkills = mergeSkills(skills, suggestedSkills);
      const nextAtsResult = computeAtsScore(extractedText, profileTerms);

      setResumeText(extractedText);
      setShortPdfExtraction(extractedText.trim().length < 50);
      setHasPdfExtraction(true);
      setSkills(nextSkills);

      const resumePath = await uploadResumePdf(userId, file);
      uploaded = true;

      const resumeMeta: ResumeMeta = {
        path: resumePath,
        filename: file.name,
        uploaded_at: new Date().toISOString(),
        ats: nextAtsResult,
      };
      uploadedMeta = resumeMeta;
      uploadedSkills = nextSkills;
      await saveResumeDetails(resumeMeta, nextSkills);
      toast.success("Resume saved", {
        description: "Your private PDF, skills, and ATS estimate were updated.",
      });
    } catch (error: unknown) {
      if (error instanceof PdfTextExtractionError) {
        toast.error("We couldn't read text from that PDF.", {
          description: "Try a text-based PDF or paste your resume text instead.",
        });
      } else if (uploaded && uploadedMeta) {
        let removed = false;
        if (!savedResume) {
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
      setReadingPdf(false);
    }
  }

  function handleResumeTextChange(value: string) {
    setResumeText(value);
    setShortPdfExtraction(false);
    setHasPdfExtraction(false);
    seedResumeSkills(value);
  }

  function handleRemoveSkill(index: number) {
    const removedSkill = skills[index];
    if (!removedSkill) return;

    dismissedSkillNamesRef.current.add(getSkillKey(removedSkill.name));
    setSkills((currentSkills) =>
      currentSkills.filter((_, currentIndex) => currentIndex !== index),
    );
  }

  function handleAddManualSkill(value: string): boolean {
    const name = value.trim();
    const key = getSkillKey(name);
    if (!key) return false;

    if (skills.some((skill) => getSkillKey(skill.name) === key)) {
      toast.error("That skill is already in your list.");
      return false;
    }

    if (skills.length >= MAX_PROFILE_SKILLS) {
      toast.error("You can save up to 100 skills.");
      return false;
    }

    dismissedSkillNamesRef.current.delete(key);
    setSkills((currentSkills) =>
      mergeSkills(currentSkills, [{ name, source: "manual" }]),
    );
    return true;
  }

  function handleExposureChange(field: keyof ExposureValues, value: string) {
    exposureTouchedRef.current = true;
    setExposure((currentExposure) => ({
      ...currentExposure,
      [field]: value,
    }));
  }

  async function handleSaveProfile() {
    if (!profileIsDirty || savingProfile || accountLoading) return;

    const skillsToSave = mergeSkills(skills);
    const exposureToSave = toSavedExposure(exposure);

    setSavingProfile(true);
    try {
      const account = await updateAccount(accessToken, {
        skills: skillsToSave,
        exposure: exposureToSave,
      });
      const nextSkills = mergeSkills(account.skills ?? skillsToSave);
      const nextExposure = toExposureValues(account.exposure ?? exposureToSave);

      setSkills(nextSkills);
      setSavedSkills(nextSkills);
      storeSkillNames(nextSkills.map((skill) => skill.name), userId);
      setExposure(nextExposure);
      setSavedExposure(nextExposure);
      exposureTouchedRef.current = false;
      toast.success("Saved to your profile", {
        description: "Your skills and exposure are ready for future recommendations.",
      });
    } catch {
      toast.error("We couldn't save your profile changes. Please try again.");
    } finally {
      setSavingProfile(false);
    }
  }

  async function handleViewSavedResume() {
    const resumeToView = pendingResumeSave?.meta ?? savedResume;
    if (!resumeToView || openingResume || removingResume) return;

    setOpeningResume(true);
    try {
      await openResumePdf(resumeToView.path);
    } catch {
      toast.error("We couldn't open your saved resume. Please try again.");
    } finally {
      setOpeningResume(false);
    }
  }

  async function handleRemoveSavedResume() {
    const resumeToRemove = pendingResumeSave?.meta ?? savedResume;
    if (!resumeToRemove || removingResume || readingPdf || savingResumeDetails) return;

    setRemovingResume(true);
    let fileRemoved = false;
    try {
      await removeResumePdf(resumeToRemove.path);
      fileRemoved = true;
      setPendingResumeSave(null);

      await updateAccount(accessToken, { resume: null });

      setSavedResume(null);
      setResumeText("");
      setShortPdfExtraction(false);
      setHasPdfExtraction(false);
      toast.success("Your resume has been removed.");
    } catch {
      toast.error(
        fileRemoved
          ? "Your file was removed, but we couldn't update your account. Please refresh."
          : "We couldn't remove your resume. Please try again.",
      );
    } finally {
      setRemovingResume(false);
    }
  }

  function handleReplaceSavedResume() {
    if (readingPdf || removingResume || savingResumeDetails) return;

    const input = document.getElementById(RESUME_PDF_INPUT_ID);
    if (input instanceof HTMLInputElement) {
      input.click();
    }
  }

  async function handleFindMatches(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    const normalizedResume = resumeText.trim();
    if (!normalizedResume) {
      toast.error("Upload or paste your resume before finding matches.");
      return;
    }

    setSubmissionError(false);
    setMatchesUpsell(false);
    setFindingMatches(true);
    try {
      const { version } = await uploadResume(normalizedResume, accessToken);
      toast.success("Resume updated", {
        description: "Version " + version + " is now powering your matches.",
      });

      const items = await getResumeMatches(accessToken);
      setMatches(items);
      setSubmissionError(false);
    } catch (error: unknown) {
      if (isProFeatureRequiredError(error)) {
        setMatchesUpsell(true);
        setMatches(null);
        setSubmissionError(false);
      } else {
        setSubmissionError(true);
        toast.error("We couldn't update your matches. Please try again.");
      }
    } finally {
      setFindingMatches(false);
    }
  }

  return (
    <div className="grid min-w-0 items-start gap-6 [overflow-wrap:anywhere] [&_button]:min-h-11 [&_input]:min-h-11 lg:grid-cols-[360px_minmax(0,1fr)]">
      <section aria-label="Free resume workspace" className="grid min-w-0 gap-6">
        {pendingResumeSave && (
          <div role="alert" className="grid gap-3 rounded-lg border border-warning/40 bg-warning/5 p-4 text-sm">
            <p>Your new PDF is stored, but its details didn&apos;t save, so your ATS estimate may be out of date.</p>
            <Button type="button" variant="outline" className="w-fit" disabled={savingResumeDetails || readingPdf || removingResume} onClick={() => void retryResumeSave()}>
              {savingResumeDetails ? "Saving…" : "Try again"}
            </Button>
          </div>
        )}
        <section className="min-w-0 rounded-lg border border-border bg-card p-5" aria-labelledby="profile-context-heading">
          <h2 id="profile-context-heading" className="mb-5 flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground"><User className="size-4" aria-hidden="true" />Profile context</h2>
          {(savedResume || pendingResumeSave) && (
            <SavedResumeCard
              resume={(pendingResumeSave?.meta ?? savedResume)!}
              openingResume={openingResume}
              replacingResume={readingPdf || savingResumeDetails}
              removingResume={removingResume}
              onViewResume={handleViewSavedResume}
              onReplaceResume={handleReplaceSavedResume}
              onRemoveResume={handleRemoveSavedResume}
            />
          )}

          {displayedAtsResult && (
            <SkillsExposureCard
              skills={skills}
              streamKey={profile.stream}
              exposure={exposure}
              accountLoading={accountLoading}
              savingProfile={savingProfile}
              profileIsDirty={profileIsDirty}
              onAddManualSkill={handleAddManualSkill}
              onRemoveSkill={handleRemoveSkill}
              onExposureChange={handleExposureChange}
              onSaveProfile={handleSaveProfile}
            />
          )}
        </section>

        <ResumeInputCard
          hasSavedResume={Boolean(savedResume)}
          resumeText={resumeText}
          readingPdf={readingPdf || savingResumeDetails}
          removingResume={removingResume}
          shortPdfExtraction={shortPdfExtraction}
          onPdfChange={handlePdfChange}
          onResumeTextChange={handleResumeTextChange}
        />

        {displayedAtsResult && <AtsScoreCard result={displayedAtsResult} />}

      </section>

      <div className="grid min-w-0 gap-8">
        <ProfileSignals profile={profile} />
        {!RESUME_MATCHES_ENABLED && (
          <ProfileOpportunities
            profile={profile}
            skillNames={savedSkills.map((skill) => skill.name)}
            accountLoading={accountLoading || !profileHydrated}
          />
        )}
        {RESUME_MATCHES_ENABLED && (
          <ProMatchesSection
            resumeReady={Boolean(resumeText.trim())}
            findingMatches={findingMatches}
            matchesUpsell={matchesUpsell}
            submissionError={submissionError}
            matches={matches}
            formRef={matchFormRef}
            onSubmit={handleFindMatches}
          />
        )}
      </div>
    </div>
  );
}

function ProfileSignals({ profile }: { profile: FieldProfile }) {
  const stream = getStream(profile.stream);
  const fields = [
    ...(stream ? [stream.label] : []),
    ...profile.divisions.map((key) => getDivision(profile.stream, key)?.label).filter((label): label is string => Boolean(label)),
    ...interestsFor(profile.stream, profile.divisions).filter((interest) => profile.interests.includes(interest.key)).map((interest) => interest.label),
  ];
  if (fields.length === 0) return null;
  return (
    <section className="rounded-lg border border-border bg-card p-6" aria-labelledby="profile-signals-heading">
      <h2 id="profile-signals-heading" className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground"><Lightbulb className="size-4" aria-hidden="true" />Profile signals</h2>
      <ul className="mt-5 flex flex-wrap gap-3">{fields.map((field, index) => <li key={index} className="inline-flex max-w-full items-center gap-2 rounded-full border border-border bg-card px-4 py-2 text-sm"><span className={`size-2 shrink-0 rounded-full ${index === 0 ? "bg-primary" : "bg-secondary"}`} aria-hidden="true" /><span className="break-words">{field}</span></li>)}</ul>
    </section>
  );
}

function SavedResumeCard({
  resume,
  openingResume,
  replacingResume,
  removingResume,
  onViewResume,
  onReplaceResume,
  onRemoveResume,
}: {
  resume: ResumeMeta;
  openingResume: boolean;
  replacingResume: boolean;
  removingResume: boolean;
  onViewResume: () => void;
  onReplaceResume: () => void;
  onRemoveResume: () => void;
}) {
  const [removeDialogOpen, setRemoveDialogOpen] = useState(false);

  return (
    <Card className="min-w-0 gap-4 rounded-none border-0 bg-card py-0 shadow-none">
      <CardHeader className="px-0">
        <p className="eyebrow">Your saved resume</p>
        <div className="flex min-w-0 items-start gap-3">
          <div className="flex size-10 shrink-0 items-center justify-center rounded-md bg-destructive/10 text-destructive"><FileText className="size-5" aria-hidden="true" /></div>
          <div className="flex min-w-0 flex-col gap-3">
            <div className="min-w-0">
              <h3 className="break-words font-serif text-lg font-bold leading-tight">
                {resume.filename}
              </h3>
              <CardDescription className="mt-2 leading-6">
                {formatSavedResumeUploadedAt(resume.uploaded_at)}. Stored privately in your
                account and replaced when you upload a new PDF.
              </CardDescription>
            </div>
            <div className="flex min-w-0 max-w-full items-center gap-1.5">
              <Badge
                variant="outline"
                className="tnum max-w-full whitespace-normal border-primary/25 bg-accent text-accent-foreground"
              >
                {resume.ats.score}/100 ATS readiness estimate
              </Badge>
            </div>
          </div>
        </div>
      </CardHeader>
      <CardFooter className="flex-col items-stretch gap-2 px-0">
        <Button
          type="button"
          variant="outline"
          onClick={onViewResume}
          disabled={openingResume || removingResume}
          className="min-h-11 w-full"
        >
          {openingResume ? (
            <Loader2 className="animate-spin" aria-hidden="true" />
          ) : (
            <ExternalLink aria-hidden="true" />
          )}
          {openingResume ? "Opening..." : "View resume"}
        </Button>
        <Button
          type="button"
          variant="secondary"
          onClick={onReplaceResume}
          disabled={replacingResume || removingResume}
          className="min-h-11 w-full"
        >
          {replacingResume ? (
            <Loader2 className="animate-spin" aria-hidden="true" />
          ) : (
            <RefreshCw aria-hidden="true" />
          )}
          {replacingResume ? "Replacing..." : "Replace resume"}
        </Button>
        <Dialog
          open={removeDialogOpen}
          onOpenChange={(open) => {
            if (!removingResume) setRemoveDialogOpen(open);
          }}
        >
          <DialogTrigger asChild>
            <Button
              type="button"
              variant="outline"
              disabled={removingResume || replacingResume}
              className="min-h-11 w-full"
            >
              {removingResume ? (
                <Loader2 className="animate-spin" aria-hidden="true" />
              ) : (
                <Trash2 aria-hidden="true" />
              )}
              {removingResume ? "Removing..." : "Remove"}
            </Button>
          </DialogTrigger>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>Remove your resume?</DialogTitle>
              <DialogDescription>
                This deletes the saved PDF and your resume check score. The skills
                you&apos;ve kept stay on your account.
              </DialogDescription>
            </DialogHeader>
            <DialogFooter>
              <DialogClose asChild>
                <Button type="button" variant="outline" disabled={removingResume}>
                  Cancel
                </Button>
              </DialogClose>
              <Button
                type="button"
                variant="destructive"
                onClick={onRemoveResume}
                disabled={removingResume || replacingResume}
              >
                {removingResume && (
                  <Loader2 className="animate-spin" aria-hidden="true" />
                )}
                {removingResume ? "Removing..." : "Remove"}
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      </CardFooter>
    </Card>
  );
}

function ResumeInputCard({
  hasSavedResume,
  resumeText,
  readingPdf,
  removingResume,
  shortPdfExtraction,
  onPdfChange,
  onResumeTextChange,
}: {
  hasSavedResume: boolean;
  resumeText: string;
  readingPdf: boolean;
  removingResume: boolean;
  shortPdfExtraction: boolean;
  onPdfChange: (event: ChangeEvent<HTMLInputElement>) => void;
  onResumeTextChange: (value: string) => void;
}) {
  return (
    <Card
      id="resume-workspace"
      className="w-full min-w-0 scroll-mt-24 border-border bg-card shadow-none"
    >
      <CardHeader className="px-5 sm:px-8">
        <p className="eyebrow">Your experience</p>
        <h2 className="font-serif text-2xl font-bold leading-tight">
          {hasSavedResume ? "Replace or quick-check your resume" : "Start with your resume"}
        </h2>
        <CardDescription className="max-w-2xl leading-6">
          Upload your resume PDF. It&apos;s stored privately in your account, only you can view
          it, and uploading another PDF replaces it. We read the text in your browser to
          estimate your skills and ATS readiness.
        </CardDescription>
      </CardHeader>
      <CardContent className="grid gap-6 px-5 sm:px-8">
        <div className="grid gap-2.5">
          <Label className="eyebrow" htmlFor={RESUME_PDF_INPUT_ID}>
            {hasSavedResume ? "Upload a replacement PDF" : "Upload a PDF"}
          </Label>
          <div className="rounded-lg border border-dashed border-primary/30 bg-primary/5 p-3">
            <Input
              id={RESUME_PDF_INPUT_ID}
              name="resume_pdf"
              type="file"
              accept="application/pdf,.pdf"
              onChange={onPdfChange}
              disabled={readingPdf || removingResume}
              aria-describedby="resume-pdf-help"
              className="cursor-pointer bg-background/70"
            />
            <p id="resume-pdf-help" className="mt-2 text-xs leading-5 text-muted-foreground">
              Stored privately in your account at up to 5 MB. Uploading a new PDF replaces the
              saved file.
            </p>
          </div>
          {readingPdf && (
            <p className="flex items-center gap-2 text-sm text-muted-foreground" role="status">
              <Loader2 className="size-4 animate-spin" aria-hidden="true" />
              Reading and saving your PDF...
            </p>
          )}
          {shortPdfExtraction && (
            <p className="text-sm leading-6 text-primary" role="status">
              We couldn&apos;t read much text — this looks like a scanned/image PDF. Paste your
              resume text below instead.
            </p>
          )}
        </div>

        <div className="flex items-center gap-3" aria-hidden="true">
          <div className="h-px flex-1 bg-border" />
          <span className="eyebrow text-muted-foreground">or paste text</span>
          <div className="h-px flex-1 bg-border" />
        </div>

        <div className="grid gap-2.5">
          <Label className="eyebrow" htmlFor="resume-text">
            Resume text
          </Label>
          <Textarea
            id="resume-text"
            name="resume_text"
            rows={12}
            value={resumeText}
            onChange={(event) => onResumeTextChange(event.target.value)}
            placeholder="Paste your education, experience, projects, and skills here…"
            aria-describedby="resume-text-help"
            className="min-h-72 bg-background/60 px-4 py-3 leading-6 shadow-soft"
          />
          <p id="resume-text-help" className="text-xs leading-5 text-muted-foreground">
            Ephemeral quick check: pasted text updates the estimate and suggestions in this
            browser only. It does not upload a PDF or replace your saved resume.
          </p>
        </div>
      </CardContent>
    </Card>
  );
}

function AtsChecksList({ result }: { result: AtsResult }) {
  const checks = Array.isArray(result.checks) ? result.checks : [];

  return (
    <div className="grid gap-4">
      <div>
        <p className="eyebrow">ATS readiness estimate breakdown</p>
        <p className="mt-1 text-sm leading-5 text-muted-foreground">
          Each check is a suggestion based on the text currently in your resume.
        </p>
      </div>
      {checks.length > 0 ? (
        <ul className="grid gap-3">
          {checks.map((check) => (
            <li
              key={check.id}
              className="border-b border-border pb-3 last:border-b-0 last:pb-0"
            >
              <div className="flex flex-wrap items-center justify-between gap-2">
                <span className="flex min-w-0 items-center gap-2 text-sm font-medium text-foreground">
                  <AtsStatusIcon status={check.status} />
                  <span>{check.label}</span>
                </span>
                <span className="flex items-center gap-2">
                  <Badge variant="outline" className={getAtsStatusClassName(check.status)}>
                    {getAtsStatusLabel(check.status)}
                  </Badge>
                  <span className="text-xs font-medium text-muted-foreground">
                    {check.points}/{check.maxPoints} pts
                  </span>
                </span>
              </div>
              {check.status !== "pass" && check.tip && (
                <p className="mt-2 text-xs leading-5 text-muted-foreground">{check.tip}</p>
              )}
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-sm leading-5 text-muted-foreground">
          No breakdown was saved for this resume.
        </p>
      )}
    </div>
  );
}

function AtsScoreCard({ result }: { result: AtsResult }) {
  return (
    <Card className="h-full border-border bg-card shadow-none">
      <CardHeader className="px-5 sm:px-6">
        <p className="eyebrow">Free ATS estimate</p>
        <h2 className="font-serif text-2xl font-bold leading-tight">ATS readiness estimate</h2>
      </CardHeader>
      <CardContent className="grid gap-5 px-5 sm:px-6">
        <ScoreRing score={result.score} />
        <p className="text-center text-sm leading-6 text-muted-foreground">Checks formatting and content signals, not your odds of being hired.</p>
        <details className="border-t border-border pt-3">
          <summary className="min-h-11 cursor-pointer content-center text-sm font-medium text-primary">See the checks</summary>
          <div className="mt-3"><AtsChecksList result={result} /></div>
        </details>

        <p className="text-xs leading-5 text-muted-foreground">
          This score is an estimate for improving your resume, not a guarantee of ATS or hiring
          outcomes.
        </p>
      </CardContent>
    </Card>
  );
}

function SkillsExposureCard({
  skills,
  streamKey,
  exposure,
  accountLoading,
  savingProfile,
  profileIsDirty,
  onAddManualSkill,
  onRemoveSkill,
  onExposureChange,
  onSaveProfile,
}: {
  skills: ProfileSkill[];
  streamKey: string | null;
  exposure: ExposureValues;
  accountLoading: boolean;
  savingProfile: boolean;
  profileIsDirty: boolean;
  onAddManualSkill: (value: string) => boolean;
  onRemoveSkill: (index: number) => void;
  onExposureChange: (field: keyof ExposureValues, value: string) => void;
  onSaveProfile: () => void;
}) {
  const excludedSkillNames = useMemo(
    () => new Set(skills.map((skill) => getSkillKey(skill.name))),
    [skills],
  );

  return (
    <Card className="mt-5 min-w-0 gap-5 rounded-none border-0 border-t border-border bg-card pt-5 pb-0 shadow-none">
      <CardHeader className="px-0">
        <p className="eyebrow">Free profile signals</p>
        <h3 className="font-serif text-2xl font-bold leading-tight">Skills &amp; exposure</h3>
        <CardDescription className="leading-6">
          Resume skills are suggestions. Edit them so your saved profile reflects you.
        </CardDescription>
      </CardHeader>
      <CardContent className="grid gap-6 px-0">
        <div className="grid gap-3">
          <div className="flex items-center justify-between gap-3">
            <span className="eyebrow">Skills</span>
            <span className="text-xs text-muted-foreground">{skills.length}/100</span>
          </div>

          {skills.length > 0 ? (
            <ul className="flex flex-wrap gap-2" aria-label="Skills to save to your profile">
              {skills.map((skill, index) => (
                <li key={getSkillKey(skill.name)} className="max-w-full">
                  <Badge
                    variant={skill.source === "manual" ? "outline" : "secondary"}
                    className="max-w-full gap-1.5 whitespace-normal break-words normal-case tracking-normal"
                  >
                    <span className="min-w-0 break-words [overflow-wrap:anywhere]">{skill.name}</span>
                    <span className="text-[0.625rem] text-muted-foreground">
                      {skill.source === "manual" ? "Manual" : "Suggested"}
                    </span>
                    <button
                      type="button"
                      onClick={() => onRemoveSkill(index)}
                      className="inline-flex min-h-11 min-w-11 shrink-0 items-center justify-center rounded-sm text-muted-foreground transition-colors hover:bg-background/70 hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                      aria-label={"Remove " + skill.name}
                    >
                      <X className="size-3" aria-hidden="true" />
                    </button>
                  </Badge>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-sm leading-6 text-muted-foreground">
              No skills suggested yet. Add the ones that best represent your experience.
            </p>
          )}

          <div className="grid gap-2">
            <Label className="eyebrow" htmlFor="manual-skill">
              Add a skill
            </Label>
            <SkillCatalogPicker
              id="manual-skill"
              streamKey={streamKey}
              exclude={excludedSkillNames}
              describedById="manual-skill-help"
              onAddSkill={onAddManualSkill}
            />
          </div>
          <p id="manual-skill-help" className="text-xs leading-5 text-muted-foreground">
            Add or remove suggestions before saving. You can save up to 100 skills.
          </p>
        </div>

        <div className="grid gap-4 border-t border-border pt-5">
          <div className="grid gap-2.5">
            <Label className="eyebrow" htmlFor="profile-experience">
              Experience
            </Label>
            <Input
              id="profile-experience"
              value={exposure.experience}
              onChange={(event) => onExposureChange("experience", event.target.value)}
              placeholder="e.g. Two internships, campus leadership, freelance projects"
              maxLength={500}
            />
          </div>
          <div className="grid gap-2.5">
            <Label className="eyebrow" htmlFor="profile-notes">
              Notes
            </Label>
            <Textarea
              id="profile-notes"
              rows={4}
              value={exposure.notes}
              onChange={(event) => onExposureChange("notes", event.target.value)}
              placeholder="Anything else you want to remember about your goals or exposure"
              maxLength={2000}
              className="resize-y bg-background/60 leading-6 shadow-soft"
            />
          </div>
        </div>
      </CardContent>
      <CardFooter className="flex-col items-stretch gap-3 px-0">
        <p className="text-xs leading-5 text-muted-foreground" role={accountLoading ? "status" : undefined}>
          {accountLoading
            ? "Loading saved profile details…"
            : "Save the suggestions and notes you want to keep in your profile."}
        </p>
        <Button
          type="button"
          onClick={onSaveProfile}
          disabled={savingProfile || !profileIsDirty || accountLoading}
          className="min-h-11 w-full"
        >
          {savingProfile ? (
            <Loader2 className="animate-spin" aria-hidden="true" />
          ) : (
            <Sparkles aria-hidden="true" />
          )}
          {savingProfile ? "Saving…" : "Save to profile"}
        </Button>
      </CardFooter>
    </Card>
  );
}

function SkillCatalogPicker({
  id,
  streamKey,
  exclude,
  describedById,
  onAddSkill,
}: {
  id: string;
  streamKey: string | null;
  exclude: ReadonlySet<string>;
  describedById?: string;
  onAddSkill: (value: string) => boolean;
}) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const searchInputRef = useRef<HTMLInputElement>(null);
  const searchInputId = useId();
  const skillListId = useId();
  const resultCountId = useId();
  const trimmedQuery = query.trim();
  const matchingSkills = useMemo(
    () => catalogSkills({ streamKey, query, exclude, limit: 60 }),
    [exclude, query, streamKey],
  );

  function handleOpenChange(nextOpen: boolean) {
    setOpen(nextOpen);
    if (!nextOpen) setQuery("");
  }

  function handleSelect(skillName: string) {
    if (onAddSkill(skillName)) {
      handleOpenChange(false);
    }
  }

  function handleOther() {
    if (!trimmedQuery) {
      searchInputRef.current?.focus();
      return;
    }

    if (onAddSkill(trimmedQuery)) {
      handleOpenChange(false);
    }
  }

  return (
    <Popover open={open} onOpenChange={handleOpenChange}>
      <PopoverTrigger asChild>
        <Button
          id={id}
          type="button"
          variant="outline"
          className="min-h-11 w-full justify-between font-normal"
          aria-expanded={open}
          aria-describedby={describedById}
        >
          <span className="min-w-0 flex-1 truncate text-left">Add a skill</span>
          <ChevronDown className="shrink-0 text-muted-foreground" aria-hidden="true" />
        </Button>
      </PopoverTrigger>
      <PopoverContent
        align="start"
        aria-label="Add a skill"
        className="w-[min(22rem,calc(100vw-2rem))] p-2"
        onOpenAutoFocus={(event) => {
          event.preventDefault();
          searchInputRef.current?.focus();
        }}
      >
        <div className="relative">
          <Search
            aria-hidden="true"
            className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted-foreground"
          />
          <label htmlFor={searchInputId} className="sr-only">
            Search skills
          </label>
          <Input
            ref={searchInputRef}
            id={searchInputId}
            type="search"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Search skills..."
            maxLength={80}
            autoComplete="off"
            aria-controls={skillListId}
            aria-describedby={resultCountId}
            className="pl-9"
          />
        </div>

        <p id={resultCountId} className="sr-only" aria-live="polite">
          {matchingSkills.length +
            " " +
            (matchingSkills.length === 1 ? "skill" : "skills") +
            " available"}
        </p>

        <ul
          id={skillListId}
          aria-label="Skills"
          className="mt-2 max-h-72 space-y-0.5 overflow-y-auto pr-1"
        >
          {matchingSkills.length === 0 ? (
            <li className="px-2 py-6 text-center text-sm text-muted-foreground">
              {trimmedQuery
                ? "No skills match \"" + trimmedQuery + "\"."
                : "No skills available."}
            </li>
          ) : (
            matchingSkills.map((skill) => (
              <li key={skill.name}>
                <button
                  type="button"
                  aria-pressed={false}
                  onClick={() => handleSelect(skill.name)}
                  className={cn(
                    "flex min-h-11 w-full items-center gap-3 rounded-sm px-2 py-2 text-left text-sm transition-colors duration-200 ease-[var(--ease-premium)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                    "hover:bg-accent/70 hover:text-accent-foreground",
                  )}
                >
                  <span className="min-w-0 flex-1 truncate">{skill.name}</span>
                </button>
              </li>
            ))
          )}
        </ul>

        <div className="mt-2 border-t border-border pt-2">
          <button
            type="button"
            aria-pressed={false}
            onClick={handleOther}
            className={cn(
              "flex min-h-11 w-full items-center rounded-sm px-2 py-2 text-left text-sm transition-colors duration-200 ease-[var(--ease-premium)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
              "hover:bg-accent/70 hover:text-accent-foreground",
            )}
          >
            <span className="min-w-0 flex-1 truncate">
              {trimmedQuery
                ? "Other — add \"" + trimmedQuery + "\""
                : "Other — type a custom skill"}
            </span>
          </button>
        </div>
      </PopoverContent>
    </Popover>
  );
}

function ProMatchesSection({
  resumeReady,
  findingMatches,
  matchesUpsell,
  submissionError,
  matches,
  formRef,
  onSubmit,
}: {
  resumeReady: boolean;
  findingMatches: boolean;
  matchesUpsell: boolean;
  submissionError: boolean;
  matches: MatchItem[] | null;
  formRef: RefObject<HTMLFormElement | null>;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
}) {
  return (
    <section aria-labelledby="pro-matches-heading" className="grid gap-6">
      <div className="mx-auto flex w-full max-w-3xl flex-col items-start justify-between gap-4 sm:flex-row sm:items-end">
        <div>
          <p className="eyebrow">Resume workspace</p>
          <h2 id="pro-matches-heading" className="mt-2 font-serif text-2xl font-bold text-foreground sm:text-3xl">
            Curated opportunities
          </h2>
          <p className="mt-2 max-w-2xl text-sm leading-6 text-muted-foreground">
            Your free skills and ATS estimate stay yours. Pro adds a ranked shortlist from the same
            resume text.
          </p>
        </div>
        <Badge variant="secondary">
          <Sparkles aria-hidden="true" />
          Pro
        </Badge>
      </div>

      <Card className="w-full min-w-0 border-border shadow-none">
        <CardHeader className="px-5 sm:px-8">
          <p className="eyebrow">The Pro shortlist</p>
          <h3 className="font-serif text-2xl font-bold leading-tight">
            Rank opportunities against your experience
          </h3>
          <CardDescription className="max-w-2xl leading-6">
            When you&apos;re ready, use the current resume text above to find your personalized
            matches.
          </CardDescription>
        </CardHeader>
        <CardContent className="px-5 sm:px-8">
          <form ref={formRef} onSubmit={onSubmit} aria-busy={findingMatches}>
            <Button
              type="submit"
              size="lg"
              disabled={findingMatches || !resumeReady}
              className="w-full sm:w-auto"
            >
              {findingMatches ? (
                <Loader2 className="animate-spin" aria-hidden="true" />
              ) : (
                <FileSearch aria-hidden="true" />
              )}
              {findingMatches ? "Finding matches…" : "Find my matches"}
            </Button>
          </form>
        </CardContent>
      </Card>

      {matchesUpsell ? (
        <UpsellCard />
      ) : (
        <>
          {submissionError && (
            <SubmissionErrorCard
              submitting={findingMatches}
              onRetry={() => {
                if (!findingMatches) formRef.current?.requestSubmit();
              }}
            />
          )}
          {matches !== null && <MatchesList matches={matches} />}
        </>
      )}
    </section>
  );
}

function SignedOutCard() {
  return (
    <Card className="mx-auto max-w-2xl border-primary/20 text-center shadow-none">
      <CardHeader className="justify-items-center px-5 sm:px-8">
        <div className="mb-1 rounded-xl border border-primary/20 bg-primary/10 p-3">
          <FileSearch className="size-6 text-primary" aria-hidden="true" />
        </div>
        <p className="eyebrow">Resume workspace</p>
        <h2 className="font-serif text-2xl font-bold leading-tight sm:text-3xl">
          Sign in to check your resume
        </h2>
        <CardDescription className="max-w-lg leading-6">
          Use your Aspirova account to save your resume, review skills and check an ATS readiness estimate.
        </CardDescription>
      </CardHeader>
      <CardFooter className="justify-center px-5 sm:px-8">
        <HeaderAuth triggerLabel="Sign in to continue" triggerSize="default" />
      </CardFooter>
    </Card>
  );
}

function UpsellCard() {
  return (
    <Card className="mx-auto max-w-2xl border-border text-center shadow-none">
      <CardHeader className="justify-items-center px-5 sm:px-8">
        <div className="mb-1 rounded-xl border border-primary/20 bg-accent p-3">
          <Sparkles className="size-6 text-primary" aria-hidden="true" />
        </div>
        <p className="eyebrow">The Pro shortlist</p>
        <Badge variant="secondary">Pro feature</Badge>
        <h3 className="font-serif text-2xl font-bold leading-tight sm:text-3xl">
          Unlock matches built around your experience
        </h3>
        <CardDescription className="max-w-lg leading-6">
          The free skills and ATS readiness estimate above are yours to keep. Pro adds ranked
          opportunities based on your experience, education, and goals.
        </CardDescription>
      </CardHeader>
      <CardFooter className="justify-center px-5 sm:px-8">
        <Button asChild size="lg">
          <HoverPrefetchLink href="/pricing">View Pro pricing</HoverPrefetchLink>
        </Button>
      </CardFooter>
    </Card>
  );
}

function SubmissionErrorCard({
  submitting,
  onRetry,
}: {
  submitting: boolean;
  onRetry: () => void;
}) {
  return (
    <Card
      className="w-full min-w-0 border-border bg-card shadow-none"
      role="alert"
    >
      <CardHeader className="px-5 sm:px-8">
        <p className="eyebrow">Analysis interrupted</p>
        <h3 className="font-serif text-2xl font-bold leading-tight">
          We couldn&apos;t refresh your matches
        </h3>
        <CardDescription className="max-w-2xl leading-6">
          Your current shortlist is unchanged. Try analyzing the same resume again.
        </CardDescription>
      </CardHeader>
      <CardFooter className="flex-col items-stretch gap-4 px-5 sm:flex-row sm:items-center sm:justify-between sm:px-8">
        <p className="text-xs leading-5 text-muted-foreground">
          Your resume text is still ready in the editor above.
        </p>
        <Button
          type="button"
          onClick={onRetry}
          disabled={submitting}
          className="w-full sm:w-auto"
        >
          {submitting ? (
            <Loader2 className="animate-spin" aria-hidden="true" />
          ) : (
            <RefreshCw aria-hidden="true" />
          )}
          {submitting ? "Trying again…" : "Try again"}
        </Button>
      </CardFooter>
    </Card>
  );
}

function MatchesList({ matches }: { matches: MatchItem[] }) {
  return (
    <section aria-labelledby="matches-heading">
      <div className="flex flex-col items-start justify-between gap-4 sm:flex-row sm:items-end">
        <div>
          <p className="eyebrow">Curated shortlist</p>
          <h2 id="matches-heading" className="mt-2 font-serif text-2xl font-bold text-foreground sm:text-3xl">
            Matches for you
          </h2>
          <p className="mt-2 max-w-2xl text-sm leading-6 text-muted-foreground">
            Ranked from the experience and skills in your latest resume.
          </p>
        </div>
        {matches.length > 0 && (
          <Badge variant="outline" className="tnum border-primary/25 bg-primary/10 text-primary">
            {matches.length} {matches.length === 1 ? "match" : "matches"}
          </Badge>
        )}
      </div>

      {matches.length === 0 ? (
        <Card className="mt-6 border-primary/20 text-center shadow-none">
          <CardHeader className="justify-items-center px-5 sm:px-8">
            <div className="mb-1 rounded-xl border border-border bg-secondary/50 p-3">
              <FileSearch className="size-6 text-primary" aria-hidden="true" />
            </div>
            <p className="eyebrow">Catalog watch</p>
            <h3 className="font-serif text-2xl font-bold leading-tight">
              No strong matches yet
            </h3>
            <CardDescription className="max-w-lg leading-6">
              We&apos;re still enriching opportunities. Check back as the catalog grows.
            </CardDescription>
          </CardHeader>
          <CardFooter className="justify-center px-5 sm:px-8">
            <Button asChild variant="outline">
              <a href="#resume-workspace">Refine your resume</a>
            </Button>
          </CardFooter>
        </Card>
      ) : (

        <ol className="mt-6 grid gap-4">
          {matches.map((match, index) => (
            <li key={match.opportunity.slug} className={`min-w-0 rounded-lg border border-border border-l-4 bg-card p-5 sm:p-6 ${match.score >= 0.85 ? "border-l-success" : "border-l-primary/40"}`}>
              <div className="flex min-w-0 flex-col gap-5 sm:flex-row sm:items-center sm:justify-between">
                <div className="min-w-0 flex-1">
                  <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
                    <span className="text-xs font-medium text-muted-foreground">Rank {String(index + 1).padStart(2, "0")}</span>
                    <Badge variant="outline" className={`tnum ${match.score >= 0.85 ? "border-success/25 bg-success/10 text-success" : "border-primary/25 bg-accent text-accent-foreground"}`}>{Math.round(match.score * 100)}% fit</Badge>
                  </div>
                  <h3 className="font-serif text-2xl font-bold">
                    <HoverPrefetchLink href={`/opportunity/${match.opportunity.slug}`} className="inline-flex min-h-11 items-center break-words hover:text-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">{match.opportunity.title}</HoverPrefetchLink>
                  </h3>
                  <p className="mt-1 break-words text-sm text-muted-foreground">{[match.opportunity.company?.name, summarizeLocation(match.opportunity.location).short].filter(Boolean).join(" · ")}</p>
                </div>
                <div className="flex shrink-0 items-center gap-3 sm:flex-col sm:items-stretch">
                  <Button asChild className="min-h-11"><HoverPrefetchLink href={`/opportunity/${match.opportunity.slug}`}>View<ArrowRight className="size-4" aria-hidden="true" /></HoverPrefetchLink></Button>
                  <SaveButton slug={match.opportunity.slug} title={match.opportunity.title} className="min-h-11 min-w-11 sm:w-full" />
                </div>
              </div>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}
