import taxonomy from "@/lib/taxonomy.json";

export type Interest = {
  key: string;
  label: string;
  keywords?: string[];
};

export type Division = {
  key: string;
  label: string;
  interests: Interest[];
};

export type Stream = {
  key: string;
  label: string;
  divisions: Division[];
};

export const STREAMS: readonly Stream[] = taxonomy.streams;

export type StreamKey = (typeof STREAMS)[number]["key"];

export type FieldProfile = {
  stream: string | null;
  divisions: string[];
  interests: string[];
};

export function getStream(key: string | null | undefined): Stream | undefined {
  if (typeof key !== "string") return undefined;

  return STREAMS.find((stream) => stream.key === key);
}

export function getDivision(
  streamKey: string | null | undefined,
  divisionKey: string | null | undefined,
): Division | undefined {
  if (typeof divisionKey !== "string") return undefined;

  return getStream(streamKey)?.divisions.find((division) => division.key === divisionKey);
}

export function interestsFor(
  streamKey: string | null | undefined,
  divisionKeys: readonly string[],
): Interest[] {
  const stream = getStream(streamKey);
  if (!stream) return [];

  const selectedDivisionKeys = new Set(divisionKeys);
  const seenInterestKeys = new Set<string>();
  const interests: Interest[] = [];

  for (const division of stream.divisions) {
    if (!selectedDivisionKeys.has(division.key)) continue;

    for (const interest of division.interests) {
      if (seenInterestKeys.has(interest.key)) continue;
      seenInterestKeys.add(interest.key);
      interests.push(interest);
    }
  }

  return interests;
}

export function expandToSearchTerms(profile: FieldProfile): string[] {
  const stream = getStream(profile.stream);
  if (!stream) return [];

  const selectedInterestKeys = new Set(profile.interests);
  const selectedInterests = interestsFor(stream.key, profile.divisions).filter((interest) =>
    selectedInterestKeys.has(interest.key),
  );
  const seenTerms = new Set<string>();
  const terms: string[] = [];

  for (const interest of selectedInterests) {
    for (const candidate of interest.keywords ?? [interest.label]) {
      const term = candidate.trim().toLowerCase();
      if (!term || seenTerms.has(term)) continue;
      seenTerms.add(term);
      terms.push(term);
    }
  }

  return terms;
}

export function buildFeedTerms(
  profile: FieldProfile,
  skillNames: readonly string[],
  maxChars = 480,
): string[] {
  const interestTerms = expandToSearchTerms(profile);
  const terms: string[] = [];
  const seenTerms = new Set<string>();

  for (const candidate of [...interestTerms, ...skillNames]) {
    if (typeof candidate !== "string") continue;

    const term = candidate.trim().toLowerCase();
    if (!term || seenTerms.has(term)) continue;

    seenTerms.add(term);
    terms.push(term);
  }

  const cappedTerms: string[] = [];
  let csvLength = 0;
  for (const term of terms) {
    const nextLength = csvLength + (cappedTerms.length > 0 ? 1 : 0) + term.length;
    if (nextLength > maxChars) break;

    cappedTerms.push(term);
    csvLength = nextLength;
  }

  return cappedTerms;
}
