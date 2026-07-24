import skillsLexicon from "@/lib/skillsLexicon.json";

export type CatalogSkill = { name: string; field: string };

type LexiconSkill = CatalogSkill & {
  aliases?: readonly string[];
};

type SkillsLexicon = {
  skills: readonly LexiconSkill[];
  field_streams: Record<string, readonly string[]>;
};

const lexicon = skillsLexicon as unknown as SkillsLexicon;

export const ALL_SKILLS: CatalogSkill[] = lexicon.skills.map(({ name, field }) => ({
  name,
  field,
}));

const aliasesByName = new Map(
  lexicon.skills.map((skill) => [skill.name.toLowerCase(), skill.aliases ?? []]),
);

export function skillMatchesStream(field: string, streamKey: string | null): boolean {
  if (streamKey === null) {
    return true;
  }

  const streams = lexicon.field_streams[field] ?? [];
  return streams.includes(streamKey) || streams.includes("*");
}

export function catalogSkills(opts: {
  streamKey: string | null;
  query: string;
  exclude: ReadonlySet<string>;
  limit?: number;
}): CatalogSkill[] {
  const limit = opts.limit ?? 60;
  const query = opts.query.trim().toLowerCase();
  const excludedNames = new Set(Array.from(opts.exclude, (name) => name.toLowerCase()));

  if (query.length === 0) {
    return ALL_SKILLS.filter(
      (skill) =>
        !excludedNames.has(skill.name.toLowerCase()) &&
        skillMatchesStream(skill.field, opts.streamKey),
    ).slice(0, limit);
  }

  const startsWithMatches: CatalogSkill[] = [];
  const substringMatches: CatalogSkill[] = [];

  for (const skill of ALL_SKILLS) {
    const skillName = skill.name.toLowerCase();

    if (excludedNames.has(skillName)) {
      continue;
    }

    const aliases = aliasesByName.get(skillName) ?? [];
    const matches =
      skillName.includes(query) ||
      aliases.some((alias) => alias.toLowerCase().includes(query));

    if (!matches) {
      continue;
    }

    if (skillName.startsWith(query)) {
      startsWithMatches.push(skill);
    } else {
      substringMatches.push(skill);
    }
  }

  return [...startsWithMatches, ...substringMatches].slice(0, limit);
}
