// Used by backend/tests/test_taxonomy.py; executes the real frontend expansion.
import fs from "node:fs";
import { stripTypeScriptTypes } from "node:module";

const taxonomy = JSON.parse(fs.readFileSync(new URL("../lib/taxonomy.json", import.meta.url), "utf8"));
// Node 24+: the backend test needs no frontend install. Replace only the Next
// import alias, then execute the actual TypeScript with its types stripped.
const source = fs.readFileSync(new URL("../lib/taxonomy.ts", import.meta.url), "utf8")
  .replace('import taxonomy from "@/lib/taxonomy.json";', `const taxonomy = ${JSON.stringify(taxonomy)};`);
const moduleUrl = "data:text/javascript;base64," + Buffer.from(stripTypeScriptTypes(source)).toString("base64");
const { expandToSearchTerms, buildFeedTerms } = await import(moduleUrl);
const profiles = JSON.parse(fs.readFileSync(0, "utf8"));
process.stdout.write(JSON.stringify(profiles.map(({ profile, skills, maxChars }) => ({
  expanded: expandToSearchTerms(profile),
  feed: buildFeedTerms(profile, skills, maxChars),
}))));
