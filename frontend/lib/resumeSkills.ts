import skillsLexicon from "@/lib/skillsLexicon.json";

export type ExtractedSkill = {
  name: string;
  source: "resume";
};

const MAX_EXTRACTED_SKILLS = 60;
const REGEXP_SPECIAL_CHARACTERS = new Set([
  ".",
  "*",
  "+",
  "?",
  "^",
  "$",
  "{",
  "}",
  "(",
  ")",
  "|",
  "[",
  "]",
  "\\",
]);

function escapeRegExp(value: string): string {
  return Array.from(value, (character) =>
    REGEXP_SPECIAL_CHARACTERS.has(character) ? "\\" + character : character,
  ).join("");
}

function aliasMatches(resumeTextLower: string, alias: string): boolean {
  const normalizedAlias = alias.trim().toLowerCase();

  if (!normalizedAlias) {
    return false;
  }

  const escapedAlias = escapeRegExp(normalizedAlias);
  const hasPunctuation = /[^a-z0-9\s]/.test(normalizedAlias);
  const pattern = hasPunctuation
    ? new RegExp(
        "(?:^|[^a-z0-9])" + escapedAlias + "(?=$|[^a-z0-9])",
      )
    : new RegExp("\\b" + escapedAlias + "\\b");

  return pattern.test(resumeTextLower);
}

/**
 * Extracts lexicon skills mentioned as complete terms or phrases in resume text.
 */
export function extractSkills(resumeText: string): ExtractedSkill[] {
  const resumeTextLower = resumeText.toLowerCase();
  const extractedSkills: ExtractedSkill[] = [];
  const seenNames = new Set<string>();

  for (const skill of skillsLexicon.skills) {
    if (extractedSkills.length >= MAX_EXTRACTED_SKILLS) {
      break;
    }

    if (seenNames.has(skill.name)) {
      continue;
    }

    const matchesAlias = skill.aliases.some((alias) =>
      aliasMatches(resumeTextLower, alias),
    );

    if (matchesAlias) {
      seenNames.add(skill.name);
      extractedSkills.push({ name: skill.name, source: "resume" });
    }
  }

  return extractedSkills;
}
