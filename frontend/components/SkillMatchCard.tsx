"use client";

import { Check, Target, X } from "lucide-react";
import HoverPrefetchLink from "@/components/HoverPrefetchLink";
import { Button } from "@/components/ui/button";
import { useSkillNames } from "@/lib/personalizationSkills";

export default function SkillMatchCard({ skills }: { skills: string[] }) {
  const { skillNames, hydrated } = useSkillNames();
  if (skills.length === 0) return null;

  const saved = new Set(skillNames.map((skill) => skill.trim().toLowerCase()));
  const matched = skills.filter((skill) => saved.has(skill.trim().toLowerCase()));
  const missing = skills.filter((skill) => !saved.has(skill.trim().toLowerCase()));
  const pct = Math.round(matched.length / skills.length * 100);

  return (
    <section className="rounded-lg border border-border border-t-[3px] border-t-primary bg-card p-5 sm:p-6" aria-labelledby="skill-match-heading">
      <h2 id="skill-match-heading" className="flex items-center gap-2 border-b border-border pb-4 text-sm font-semibold tracking-wide">
        <Target className="size-5 shrink-0 text-primary" aria-hidden="true" />
        Your skill match
      </h2>
      {/* Most visitors have no saved skills, so the server and pre-hydration render
          show that state rather than a skeleton: the card then never changes after
          load for them, which is what keeps this sidebar from shifting (CLS). */}
      {!hydrated || skillNames.length === 0 ? (
        <div className="flex flex-col items-start gap-4 pt-5">
          <p className="text-sm leading-6 text-muted-foreground">See which of these {skills.length} skills you already have.</p>
          <Button asChild variant="outline" className="min-h-11"><HoverPrefetchLink href="/resume">Check my resume</HoverPrefetchLink></Button>
        </div>
      ) : (
        <div className="space-y-5 pt-6">
          <p className="flex flex-wrap items-baseline gap-2">
            <span className={`font-serif text-5xl font-bold ${pct >= 70 ? "text-success" : pct >= 40 ? "text-primary" : "text-foreground"}`}>{pct}%</span>
            <span className="text-sm text-muted-foreground">skill match</span>
          </p>
          <p className="text-sm leading-6 text-muted-foreground">{matched.length} of {skills.length} skills in this listing are on your resume.</p>
          {matched.length > 0 && <div>
            <p className="mb-2 text-sm font-medium">Skills you have:</p>
            <ul className="flex flex-wrap gap-2">{matched.map((skill, index) => <li key={`${skill}-${index}`} className="inline-flex max-w-full items-center gap-1 rounded-md border border-success/25 bg-success/10 px-2 py-1 text-xs text-success"><Check className="size-3 shrink-0" aria-hidden="true" /><span className="break-words [overflow-wrap:anywhere]">{skill}</span></li>)}</ul>
          </div>}
          {missing.length > 0 && <div>
            <p className="mb-2 text-sm font-medium">Skills to build:</p>
            <ul className="flex flex-wrap gap-2">{missing.map((skill, index) => <li key={`${skill}-${index}`} className="inline-flex max-w-full items-center gap-1 rounded-md border border-destructive/25 bg-destructive/10 px-2 py-1 text-xs text-destructive"><X className="size-3 shrink-0" aria-hidden="true" /><span className="break-words [overflow-wrap:anywhere]">{skill}</span></li>)}</ul>
          </div>}
          {missing.length > 0 && <p className="text-sm leading-6 text-muted-foreground">Evidence of {missing.slice(0, 2).join(", ")} — a project, course or certificate — would strengthen this application.</p>}
          <p className="border-t border-border pt-4 text-xs leading-5 text-muted-foreground">Compares the skills we detected in this listing with the skills saved from your resume.</p>
          <HoverPrefetchLink href="/resume" className="inline-flex min-h-11 items-center text-sm font-medium text-primary underline-offset-4 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">Update skills</HoverPrefetchLink>
        </div>
      )}
    </section>
  );
}
