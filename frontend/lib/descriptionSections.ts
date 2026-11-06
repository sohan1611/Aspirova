import type { DescriptionBlock } from "@/lib/descriptionBlocks";

const ELIGIBILITY = /\b(eligib\w*|who can apply|who should apply)\b/i;
const REQUIREMENTS = /\b(requirements?|qualifications?|what you('ll| will)? need|who you are|you (have|bring)|must[- ]haves?|skills? required|preferred)\b/i;

/** Partitions whole sections, retaining each original block (including headings) once. */
export function splitDescriptionSections(blocks: DescriptionBlock[]): {
  about: DescriptionBlock[];
  requirements: DescriptionBlock[];
  eligibility: DescriptionBlock[];
} {
  const sections = { about: [], requirements: [], eligibility: [] } as {
    about: DescriptionBlock[];
    requirements: DescriptionBlock[];
    eligibility: DescriptionBlock[];
  };
  let destination: keyof typeof sections = "about";
  for (const block of blocks) {
    if (block.type === "heading") {
      const heading = block.text.trim().replace(/:$/, "").trim();
      destination = ELIGIBILITY.test(heading)
        ? "eligibility"
        : REQUIREMENTS.test(heading) ? "requirements" : "about";
    }
    sections[destination].push(block);
  }
  return sections;
}
