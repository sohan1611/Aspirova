"use client";

import { FileSearch, Info, Loader2, Plus, RefreshCw, Sparkles, X } from "lucide-react";
import Link from "next/link";
import {
  type ChangeEvent,
  type FormEvent,
  type RefObject,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { toast } from "sonner";
import HeaderAuth from "@/components/HeaderAuth";
import OpportunityCard from "@/components/OpportunityCard";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
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
import { computeAtsScore } from "@/lib/atsScore";
import { useFieldProfile } from "@/lib/fieldProfile";
import { extractPdfText, PdfTextExtractionError } from "@/lib/pdfText";
import { storeSkillNames } from "@/lib/personalizationSkills";
import { extractSkills } from "@/lib/resumeSkills";
import { expandToSearchTerms } from "@/lib/taxonomy";
import type { AccountMe, MatchItem } from "@/lib/types";
import { useSession } from "@/lib/useSession";

type ProfileSkill = NonNullable<AccountMe["skills"]>[number];

type ExposureValues = {
  experience: string;
  notes: string;
};

const EMPTY_EXPOSURE: ExposureValues = {
  experience: "",
  notes: "",
};
const MAX_PROFILE_SKILLS = 100;

function getSkillKey(name: string): string {
  return name.trim().toLowerCase();
}

function mergeSkills(
  ...groups: Array<readonly ProfileSkill[] | null | undefined>
): ProfileSkill[] {
  const merged: ProfileSkill[] = [];
  const indexByName = new Map<string, number>();

  for (const group of groups) {
    if (!group) continue;

    for (const skill of group) {
      const name = skill.name.trim();
      const key = getSkillKey(name);
      if (!key) continue;

      const source = skill.source === "manual" ? "manual" : "resume";
      const existingIndex = indexByName.get(key);

      if (existingIndex !== undefined) {
        if (source === "manual" && merged[existingIndex].source !== "manual") {
          merged[existingIndex] = { name, source };
        }
        continue;
      }

      if (merged.length >= MAX_PROFILE_SKILLS) {
        continue;
      }

      indexByName.set(key, merged.length);
      merged.push({ name, source });
    }
  }

  return merged;
}

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
    return "border-heritage/25 bg-heritage/10 text-heritage";
  }

  return "border-border bg-secondary/70 text-muted-foreground";
}

export default function ResumeMatchPage() {
  const session = useSession();

  return (
    <main className="mx-auto w-full max-w-7xl px-4 py-10 sm:px-6 sm:py-14 lg:px-8">
      <header className="mx-auto max-w-3xl text-center">
        <p className="eyebrow">Career intelligence</p>
        <h1 className="mt-4 text-3xl font-semibold text-foreground sm:text-4xl">
          Resume Match
        </h1>
        <p className="mx-auto mt-3 max-w-2xl text-sm leading-6 text-muted-foreground sm:text-base">
          Read your resume locally, review suggested skills, and check an ATS readiness estimate.
        </p>
      </header>

      <div className="mt-10 sm:mt-12">
        {!session ? (
          <SignedOutCard />
        ) : (
          <SignedInResumeWorkspace
            key={session.user.id}
            accessToken={session.access_token}
          />
        )}
      </div>
    </main>
  );
}

function SignedInResumeWorkspace({ accessToken }: { accessToken: string }) {
  const { profile } = useFieldProfile();
  const [resumeText, setResumeText] = useState("");
  const [readingPdf, setReadingPdf] = useState(false);
  const [shortPdfExtraction, setShortPdfExtraction] = useState(false);
  const [hasPdfExtraction, setHasPdfExtraction] = useState(false);
  const [skills, setSkills] = useState<ProfileSkill[]>([]);
  const [savedSkills, setSavedSkills] = useState<ProfileSkill[]>([]);
  const [manualSkill, setManualSkill] = useState("");
  const [exposure, setExposure] = useState<ExposureValues>(EMPTY_EXPOSURE);
  const [savedExposure, setSavedExposure] = useState<ExposureValues>(EMPTY_EXPOSURE);
  const [accountLoading, setAccountLoading] = useState(true);
  const [savingProfile, setSavingProfile] = useState(false);
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
        storeSkillNames(accountSkills.map((skill) => skill.name));
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
        setAccountLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [accessToken]);

  function seedResumeSkills(text: string) {
    const suggestedSkills = extractSkills(text).filter(
      (skill) => !dismissedSkillNamesRef.current.has(getSkillKey(skill.name)),
    );

    if (suggestedSkills.length === 0) return;

    setSkills((currentSkills) => mergeSkills(currentSkills, suggestedSkills));
  }

  async function handlePdfChange(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;

    setShortPdfExtraction(false);
    setHasPdfExtraction(false);

    const isPdf =
      file.type === "application/pdf" || file.name.toLowerCase().endsWith(".pdf");
    if (!isPdf) {
      toast.error("Choose a PDF resume to continue.");
      return;
    }

    setReadingPdf(true);
    try {
      const extractedText = await extractPdfText(file);
      setResumeText(extractedText);
      setShortPdfExtraction(extractedText.trim().length < 50);
      setHasPdfExtraction(true);
      seedResumeSkills(extractedText);
    } catch (error: unknown) {
      if (error instanceof PdfTextExtractionError) {
        toast.error("We couldn't read text from that PDF.", {
          description: "Try a text-based PDF or paste your resume text instead.",
        });
      } else {
        toast.error("We couldn't read that file.", {
          description: "Try again or paste your resume text instead.",
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

  function handleAddManualSkill(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    const name = manualSkill.trim();
    const key = getSkillKey(name);
    if (!key) return;

    if (skills.some((skill) => getSkillKey(skill.name) === key)) {
      toast.error("That skill is already in your list.");
      return;
    }

    if (skills.length >= MAX_PROFILE_SKILLS) {
      toast.error("You can save up to 100 skills.");
      return;
    }

    dismissedSkillNamesRef.current.delete(key);
    setSkills((currentSkills) =>
      mergeSkills(currentSkills, [{ name, source: "manual" }]),
    );
    setManualSkill("");
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
      storeSkillNames(nextSkills.map((skill) => skill.name));
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
    <div className="grid gap-12 sm:gap-14">
      <section aria-label="Free resume workspace" className="grid gap-5">
        <ResumeInputCard
          resumeText={resumeText}
          readingPdf={readingPdf}
          shortPdfExtraction={shortPdfExtraction}
          onPdfChange={handlePdfChange}
          onResumeTextChange={handleResumeTextChange}
        />

        {atsResult && (
          <div className="mx-auto grid w-full max-w-5xl gap-5 lg:grid-cols-2">
            <AtsScoreCard result={atsResult} />
            <SkillsExposureCard
              skills={skills}
              manualSkill={manualSkill}
              exposure={exposure}
              accountLoading={accountLoading}
              savingProfile={savingProfile}
              profileIsDirty={profileIsDirty}
              onManualSkillChange={setManualSkill}
              onAddManualSkill={handleAddManualSkill}
              onRemoveSkill={handleRemoveSkill}
              onExposureChange={handleExposureChange}
              onSaveProfile={handleSaveProfile}
            />
          </div>
        )}
      </section>

      <ProMatchesSection
        resumeReady={Boolean(resumeText.trim())}
        findingMatches={findingMatches}
        matchesUpsell={matchesUpsell}
        submissionError={submissionError}
        matches={matches}
        formRef={matchFormRef}
        onSubmit={handleFindMatches}
      />
    </div>
  );
}

function ResumeInputCard({
  resumeText,
  readingPdf,
  shortPdfExtraction,
  onPdfChange,
  onResumeTextChange,
}: {
  resumeText: string;
  readingPdf: boolean;
  shortPdfExtraction: boolean;
  onPdfChange: (event: ChangeEvent<HTMLInputElement>) => void;
  onResumeTextChange: (value: string) => void;
}) {
  return (
    <Card
      id="resume-workspace"
      className="mx-auto w-full max-w-3xl scroll-mt-24 border-primary/20 shadow-soft-md"
    >
      <CardHeader className="px-5 sm:px-8">
        <p className="eyebrow">Your experience</p>
        <CardTitle className="font-serif text-2xl leading-tight">
          Start with your resume
        </CardTitle>
        <CardDescription className="max-w-2xl leading-6">
          Upload a PDF for a local text read, or paste your resume below. Your PDF stays on your
          device.
        </CardDescription>
      </CardHeader>
      <CardContent className="grid gap-6 px-5 sm:px-8">
        <div className="grid gap-2.5">
          <Label className="eyebrow" htmlFor="resume-pdf">
            Upload a PDF
          </Label>
          <div className="rounded-lg border border-dashed border-primary/30 bg-primary/5 p-3">
            <Input
              id="resume-pdf"
              name="resume_pdf"
              type="file"
              accept="application/pdf,.pdf"
              onChange={onPdfChange}
              disabled={readingPdf}
              aria-describedby="resume-pdf-help"
              className="cursor-pointer bg-background/70"
            />
            <p id="resume-pdf-help" className="mt-2 text-xs leading-5 text-muted-foreground">
              We only read selectable text in your browser. The PDF is never uploaded.
            </p>
          </div>
          {readingPdf && (
            <p className="flex items-center gap-2 text-sm text-muted-foreground" role="status">
              <Loader2 className="size-4 animate-spin" aria-hidden="true" />
              Reading your PDF…
            </p>
          )}
          {shortPdfExtraction && (
            <p className="text-sm leading-6 text-heritage" role="status">
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
            Your text powers the free suggestions below. You can review or edit everything before
            saving it.
          </p>
        </div>
      </CardContent>
    </Card>
  );
}

function AtsScoreCard({ result }: { result: ReturnType<typeof computeAtsScore> }) {
  return (
    <Card className="h-full border-primary/20 shadow-soft-md">
      <CardHeader className="px-5 sm:px-6">
        <p className="eyebrow">Free ATS estimate</p>
        <CardTitle className="font-serif text-2xl leading-tight">ATS readiness</CardTitle>
        <CardDescription className="leading-6">
          A transparent estimate to help you improve — not a guarantee.
        </CardDescription>
      </CardHeader>
      <CardContent className="grid gap-5 px-5 sm:px-6">
        <div className="flex items-start justify-between gap-4 rounded-lg border border-primary/15 bg-primary/5 p-4">
          <div>
            <p className="text-sm font-medium text-muted-foreground">ATS readiness</p>
            <p className="mt-1 text-3xl font-semibold tracking-tight text-foreground sm:text-4xl">
              {result.score} <span className="text-lg font-medium text-muted-foreground">/ 100</span>
            </p>
          </div>
          <Popover>
            <PopoverTrigger asChild>
              <Button
                type="button"
                variant="outline"
                size="icon-sm"
                aria-label="Show ATS score breakdown and improvement tips"
              >
                <Info aria-hidden="true" />
              </Button>
            </PopoverTrigger>
            <PopoverContent
              align="end"
              className="max-h-[min(32rem,75vh)] overflow-y-auto"
              aria-label="ATS score breakdown and improvement tips"
            >
              <div className="grid gap-4">
                <div>
                  <p className="eyebrow">ATS score breakdown</p>
                  <p className="mt-1 text-sm leading-5 text-muted-foreground">
                    Each check is a suggestion based on the text currently in your resume.
                  </p>
                </div>
                <ul className="grid gap-3">
                  {result.checks.map((check) => (
                    <li key={check.id} className="border-b border-border pb-3 last:border-b-0 last:pb-0">
                      <div className="flex flex-wrap items-center justify-between gap-2">
                        <span className="text-sm font-medium text-foreground">{check.label}</span>
                        <span className="flex items-center gap-2">
                          <Badge
                            variant="outline"
                            className={getAtsStatusClassName(check.status)}
                          >
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
              </div>
            </PopoverContent>
          </Popover>
        </div>
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
  manualSkill,
  exposure,
  accountLoading,
  savingProfile,
  profileIsDirty,
  onManualSkillChange,
  onAddManualSkill,
  onRemoveSkill,
  onExposureChange,
  onSaveProfile,
}: {
  skills: ProfileSkill[];
  manualSkill: string;
  exposure: ExposureValues;
  accountLoading: boolean;
  savingProfile: boolean;
  profileIsDirty: boolean;
  onManualSkillChange: (value: string) => void;
  onAddManualSkill: (event: FormEvent<HTMLFormElement>) => void;
  onRemoveSkill: (index: number) => void;
  onExposureChange: (field: keyof ExposureValues, value: string) => void;
  onSaveProfile: () => void;
}) {
  const canAddSkill = Boolean(manualSkill.trim()) && skills.length < MAX_PROFILE_SKILLS;

  return (
    <Card className="h-full border-primary/20 shadow-soft-md">
      <CardHeader className="px-5 sm:px-6">
        <p className="eyebrow">Free profile signals</p>
        <CardTitle className="font-serif text-2xl leading-tight">Skills &amp; exposure</CardTitle>
        <CardDescription className="leading-6">
          Resume skills are suggestions. Edit them so your saved profile reflects you.
        </CardDescription>
      </CardHeader>
      <CardContent className="grid gap-6 px-5 sm:px-6">
        <div className="grid gap-3">
          <div className="flex items-center justify-between gap-3">
            <Label className="eyebrow" htmlFor="manual-skill">
              Skills
            </Label>
            <span className="text-xs text-muted-foreground">{skills.length}/100</span>
          </div>

          {skills.length > 0 ? (
            <ul className="flex flex-wrap gap-2" aria-label="Skills to save to your profile">
              {skills.map((skill, index) => (
                <li key={getSkillKey(skill.name)}>
                  <Badge
                    variant={skill.source === "manual" ? "outline" : "secondary"}
                    className="gap-1.5 normal-case tracking-normal"
                  >
                    <span>{skill.name}</span>
                    <span className="text-[0.625rem] text-muted-foreground">
                      {skill.source === "manual" ? "Manual" : "Suggested"}
                    </span>
                    <button
                      type="button"
                      onClick={() => onRemoveSkill(index)}
                      className="rounded-sm p-0.5 text-muted-foreground transition-colors hover:bg-background/70 hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
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

          <form onSubmit={onAddManualSkill} className="flex gap-2">
            <Input
              id="manual-skill"
              value={manualSkill}
              onChange={(event) => onManualSkillChange(event.target.value)}
              placeholder="Add a skill"
              maxLength={80}
              aria-describedby="manual-skill-help"
            />
            <Button type="submit" variant="outline" disabled={!canAddSkill}>
              <Plus aria-hidden="true" />
              Add
            </Button>
          </form>
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
      <CardFooter className="flex-col items-stretch gap-3 px-5 sm:flex-row sm:items-center sm:justify-between sm:px-6">
        <p className="text-xs leading-5 text-muted-foreground" role={accountLoading ? "status" : undefined}>
          {accountLoading
            ? "Loading saved profile details…"
            : "Save the suggestions and notes you want to keep in your profile."}
        </p>
        <Button
          type="button"
          onClick={onSaveProfile}
          disabled={savingProfile || !profileIsDirty || accountLoading}
          className="w-full sm:w-auto"
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
          <p className="eyebrow">Personal matching</p>
          <h2 id="pro-matches-heading" className="mt-2 text-2xl font-semibold text-foreground sm:text-3xl">
            Find your opportunity matches
          </h2>
          <p className="mt-2 max-w-2xl text-sm leading-6 text-muted-foreground">
            Your free skills and ATS estimate stay yours. Pro adds a ranked shortlist from the same
            resume text.
          </p>
        </div>
        <Badge variant="heritage">
          <Sparkles aria-hidden="true" />
          Pro
        </Badge>
      </div>

      <Card className="mx-auto w-full max-w-3xl border-heritage/25 shadow-soft-md">
        <CardHeader className="px-5 sm:px-8">
          <p className="eyebrow">The Pro shortlist</p>
          <CardTitle className="font-serif text-2xl leading-tight">
            Rank opportunities against your experience
          </CardTitle>
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
    <Card className="mx-auto max-w-2xl border-primary/20 text-center shadow-soft-md">
      <CardHeader className="justify-items-center px-5 sm:px-8">
        <div className="mb-1 rounded-xl border border-primary/20 bg-primary/10 p-3">
          <FileSearch className="size-6 text-primary" aria-hidden="true" />
        </div>
        <p className="eyebrow">Personal matching</p>
        <CardTitle className="font-serif text-2xl leading-tight sm:text-3xl">
          Sign in to match your resume
        </CardTitle>
        <CardDescription className="max-w-lg leading-6">
          Use your Aspirova account to save your resume profile and see personalized matches.
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
    <Card className="mx-auto max-w-2xl border-heritage/25 text-center shadow-soft-md">
      <CardHeader className="justify-items-center px-5 sm:px-8">
        <div className="mb-1 rounded-xl border border-heritage/20 bg-heritage/10 p-3">
          <Sparkles className="size-6 text-heritage" aria-hidden="true" />
        </div>
        <p className="eyebrow">The Pro shortlist</p>
        <Badge variant="heritage">Pro feature</Badge>
        <CardTitle className="font-serif text-2xl leading-tight sm:text-3xl">
          Unlock matches built around your experience
        </CardTitle>
        <CardDescription className="max-w-lg leading-6">
          The free skills and ATS readiness estimate above are yours to keep. Pro adds ranked
          opportunities based on your experience, education, and goals.
        </CardDescription>
      </CardHeader>
      <CardFooter className="justify-center px-5 sm:px-8">
        <Button asChild size="lg">
          <Link href="/pricing">View Pro pricing</Link>
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
      className="mx-auto w-full max-w-3xl border-primary/20 shadow-soft-md"
      role="alert"
    >
      <CardHeader className="px-5 sm:px-8">
        <p className="eyebrow">Analysis interrupted</p>
        <CardTitle className="font-serif text-2xl leading-tight">
          We couldn&apos;t refresh your matches
        </CardTitle>
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
          <h2 id="matches-heading" className="mt-2 text-2xl font-semibold text-foreground sm:text-3xl">
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
        <Card className="mt-6 border-primary/20 text-center shadow-soft-md">
          <CardHeader className="justify-items-center px-5 sm:px-8">
            <div className="mb-1 rounded-xl border border-border bg-secondary/50 p-3">
              <FileSearch className="size-6 text-primary" aria-hidden="true" />
            </div>
            <p className="eyebrow">Catalog watch</p>
            <CardTitle className="font-serif text-2xl leading-tight">
              No strong matches yet
            </CardTitle>
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
        <ol className="mt-6 grid grid-cols-1 gap-6 sm:grid-cols-2 lg:grid-cols-3">
          {matches.map((match, index) => (
            <li key={match.opportunity.slug} className="flex h-full min-w-0 flex-col gap-3">
              <div className="flex items-center justify-between gap-3 px-1">
                <span className="eyebrow tnum">
                  Rank {String(index + 1).padStart(2, "0")}
                </span>
                <Badge
                  variant="outline"
                  className="tnum border-primary/25 bg-primary/10 text-primary"
                >
                  {Math.round(match.score * 100)}% fit
                </Badge>
              </div>
              <div className="min-h-0 flex-1">
                <OpportunityCard item={match.opportunity} />
              </div>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}
