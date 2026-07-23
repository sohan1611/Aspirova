export type AtsCheck = {
  id: string;
  label: string;
  status: "pass" | "partial" | "fail";
  points: number;
  maxPoints: number;
  tip: string;
};

export type AtsResult = {
  score: number;
  checks: AtsCheck[];
};

type CheckStatus = AtsCheck["status"];

const ACTION_VERBS = [
  "led",
  "built",
  "developed",
  "designed",
  "implemented",
  "created",
  "managed",
  "improved",
  "launched",
  "analyzed",
  "analysed",
  "achieved",
  "increased",
  "reduced",
  "optimized",
  "optimised",
  "delivered",
  "automated",
  "researched",
  "organized",
  "organised",
] as const;

const ACTION_VERB_PATTERN = new RegExp(
  `\\b(?:${ACTION_VERBS.join("|")})\\b`,
  "g",
);

const QUANTIFIED_IMPACT_PATTERN =
  /(?:\b\d+(?:[,.]\d+)?\s*%|(?:[$€£₹]\s*|\b(?:usd|inr|eur|gbp)\s*)\d[\d,]*(?:\.\d+)?|\b\d+(?:[,.]\d+)?\s*(?:\+|x\b|(?:ms|s|secs?|seconds?|minutes?|mins?|hours?|days?|weeks?|months?|years?|users?|customers?|clients?|projects?|team\s+members?|members?|engineers?|people|requests?|downloads?|sales?|revenue|bugs?|tickets?|features?|tests?|deployments?|reports?|campaigns?|leads?|transactions?|records?|lines?)\b)|\b(?:team|teams|group|groups)\s+of\s+\d+(?:[,.]\d+)?\b)/g;

const PROFILE_TOKEN_PATTERN = /[a-z0-9]+(?:[+#.][a-z0-9+#.]*)*/g;

function getStatus(points: number, maxPoints: number): CheckStatus {
  if (points === maxPoints) {
    return "pass";
  }

  return points > 0 ? "partial" : "fail";
}

function buildCheck(
  id: string,
  label: string,
  points: number,
  maxPoints: number,
  tip: string,
): AtsCheck {
  return {
    id,
    label,
    status: getStatus(points, maxPoints),
    points,
    maxPoints,
    tip,
  };
}

function hasSectionHeading(textLower: string, headings: string[]): boolean {
  return textLower.split(/\r?\n/).some((line) => {
    const normalizedLine = line
      .trim()
      .replace(/^[#*_\s]+|[*_:\-–—\s]+$/g, "")
      .trim();

    const wordCount = normalizedLine ? normalizedLine.split(/\s+/).length : 0;
    if (
      !normalizedLine ||
      normalizedLine.length > 40 ||
      wordCount > 6 ||
      !/[a-z]/.test(normalizedLine)
    ) {
      return false;
    }

    return headings.some((heading) =>
      new RegExp(`\\b${escapeRegExp(heading)}\\b`).test(normalizedLine),
    );
  });
}

function countQuantifiedResults(textLower: string): number {
  return textLower.match(QUANTIFIED_IMPACT_PATTERN)?.length ?? 0;
}

function countDistinctActionVerbs(textLower: string): number {
  return new Set(textLower.match(ACTION_VERB_PATTERN) ?? []).size;
}

function countWords(text: string): number {
  const trimmedText = text.trim();
  return trimmedText ? trimmedText.split(/\s+/).length : 0;
}

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function matchesProfileTerm(textLower: string, term: string): boolean {
  const tokens = term.match(PROFILE_TOKEN_PATTERN) ?? [];

  if (tokens.length === 0) {
    return false;
  }

  return tokens.some((token) => {
    const escapedToken = escapeRegExp(token);
    const pattern = new RegExp(`(?:^|[^a-z0-9])${escapedToken}(?=$|[^a-z0-9])`);
    return pattern.test(textLower);
  });
}

function getLengthPoints(wordCount: number): number {
  if (wordCount >= 400 && wordCount <= 1000) {
    return 10;
  }

  if (
    (wordCount >= 250 && wordCount <= 399) ||
    (wordCount >= 1001 && wordCount <= 1400)
  ) {
    return 5;
  }

  if (
    (wordCount >= 100 && wordCount <= 249) ||
    (wordCount >= 1401 && wordCount <= 1600)
  ) {
    return 2;
  }

  return 0;
}

export function computeAtsScore(
  resumeText: string,
  profileTerms?: string[],
): AtsResult {
  const trimmedText = resumeText.trim();
  const textLower = resumeText.toLowerCase();
  const checks: AtsCheck[] = [];

  const looksLikeText = /[a-z]/.test(textLower) && /\s/.test(trimmedText);
  const parseabilityPoints =
    trimmedText.length >= 200 && looksLikeText
      ? 20
      : trimmedText.length >= 50 && trimmedText.length <= 199
        ? 10
        : 0;
  const parseabilityTip =
    parseabilityPoints === 20
      ? ""
      : parseabilityPoints === 10
        ? "Estimate: We found limited readable text. Use a text-based PDF with your experience, education, skills, and projects in selectable text."
        : "Estimate: We couldn't read much text — export a text-based PDF (not a scanned image) so ATS systems can parse it.";
  checks.push(
    buildCheck(
      "parseability",
      "PDF parseability",
      parseabilityPoints,
      20,
      parseabilityTip,
    ),
  );

  const hasEmail = /\b[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}\b/.test(textLower);
  const hasPhone = (resumeText.match(/(?:\+?\d[\d\s().-]{8,}\d)/g) ?? []).some(
    (candidate) => (candidate.match(/\d/g) ?? []).length >= 10,
  );
  const hasProfileLink =
    /(?:https?:\/\/|www\.)\S+/.test(textLower) ||
    /\b(?:linkedin|github|portfolio)\b/.test(textLower);
  const contactPoints =
    (hasEmail ? 7 : 0) + (hasPhone ? 4 : 0) + (hasProfileLink ? 4 : 0);
  const missingContactDetails = [
    ...(hasEmail ? [] : ["an email address"]),
    ...(hasPhone ? [] : ["a phone number"]),
    ...(hasProfileLink ? [] : ["a LinkedIn, GitHub, or portfolio link"]),
  ];
  checks.push(
    buildCheck(
      "contact",
      "Contact details",
      contactPoints,
      15,
      contactPoints === 15
        ? ""
        : `Estimate: Add ${missingContactDetails.join(", ")} so recruiters can contact you easily.`,
    ),
  );

  const sections = [
    {
      label: "experience",
      headings: [
        "experience",
        "work experience",
        "professional experience",
        "work history",
        "employment",
        "employment history",
      ],
      points: 6,
    },
    {
      label: "education",
      headings: [
        "education",
        "academic background",
        "academic qualifications",
        "qualifications",
      ],
      points: 5,
    },
    {
      label: "skills",
      headings: [
        "skills",
        "technical skills",
        "key skills",
        "core competencies",
        "areas of expertise",
      ],
      points: 5,
    },
    {
      label: "projects",
      headings: [
        "projects",
        "academic projects",
        "personal projects",
        "key projects",
      ],
      points: 4,
    },
  ];
  const missingSections = sections.filter(
    (section) => !hasSectionHeading(textLower, section.headings),
  );
  const sectionPoints = sections
    .filter((section) => !missingSections.includes(section))
    .reduce((total, section) => total + section.points, 0);
  checks.push(
    buildCheck(
      "sections",
      "Standard sections",
      sectionPoints,
      20,
      sectionPoints === 20
        ? ""
        : `Estimate: Add clear section headings for ${missingSections
            .map((section) => section.label)
            .join(", ")}.`,
    ),
  );

  const quantifiedResults = countQuantifiedResults(textLower);
  const quantifiedImpactPoints =
    quantifiedResults >= 3 ? 15 : quantifiedResults >= 1 ? 8 : 0;
  checks.push(
    buildCheck(
      "quantified-impact",
      "Quantified impact",
      quantifiedImpactPoints,
      15,
      quantifiedImpactPoints === 15
        ? ""
        : "Estimate: Add measurable impact (e.g. 'improved load time by 40%', 'led a team of 6').",
    ),
  );

  const actionVerbCount = countDistinctActionVerbs(textLower);
  const actionVerbPoints =
    actionVerbCount >= 5 ? 10 : actionVerbCount >= 2 ? 5 : 0;
  checks.push(
    buildCheck(
      "action-verbs",
      "Action verbs",
      actionVerbPoints,
      10,
      actionVerbPoints === 10
        ? ""
        : "Estimate: Start more bullet points with strong action verbs such as built, led, designed, or improved.",
    ),
  );

  const wordCount = countWords(resumeText);
  const lengthPoints = getLengthPoints(wordCount);
  const lengthDirection = wordCount < 400 ? "shorter" : "longer";
  checks.push(
    buildCheck(
      "length",
      "Resume length",
      lengthPoints,
      10,
      lengthPoints === 10
        ? ""
        : `Estimate: For a student resume, aim for roughly 400–1,000 words; this one is ${lengthDirection} than that range.`,
    ),
  );

  const normalizedProfileTerms = Array.from(
    new Set(
      (profileTerms ?? [])
        .map((term) => term.trim().toLowerCase())
        .filter(Boolean),
    ),
  );

  if (normalizedProfileTerms.length === 0) {
    checks.push(
      buildCheck(
        "relevance",
        "Role relevance",
        6,
        10,
        "Estimate: Set your field & interests so we can tailor this score to your target roles.",
      ),
    );
  } else {
    const matchedProfileTerms = normalizedProfileTerms.filter((term) =>
      matchesProfileTerm(textLower, term),
    );
    const overlap = matchedProfileTerms.length / normalizedProfileTerms.length;
    const relevancePoints =
      overlap >= 0.5 ? 10 : overlap > 0 ? Math.max(1, Math.round(overlap * 10)) : 0;
    checks.push(
      buildCheck(
        "relevance",
        "Role relevance",
        relevancePoints,
        10,
        relevancePoints === 10
          ? ""
          : relevancePoints > 0
            ? `Estimate: Your resume matches ${matchedProfileTerms.length} of ${normalizedProfileTerms.length} selected target terms. Add more relevant skills and project keywords.`
            : "Estimate: Add target-role skills and project keywords so this relevance check can find them.",
      ),
    );
  }

  const score = Math.min(
    100,
    Math.max(
      0,
      Math.round(checks.reduce((total, check) => total + check.points, 0)),
    ),
  );

  return { score, checks };
}
