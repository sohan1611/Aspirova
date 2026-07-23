#!/usr/bin/env node

import { mkdir, readdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";

const REQUIRED_OPTIONS = ["aicte", "ugc-csv", "curated", "hipo", "out"];
const COUNTRY_FILE_PATTERN = /^([A-Z]{2})\.json$/;
const NON_DEGREE_PATTERN = /POLYTECHNIC|INDUSTRIAL TRAINING|\bITI\b/i;
const DOTTED_INITIALS_PATTERN = /^(?:[A-Za-z]\.)+[A-Za-z]?$/;
const ROMAN_NUMERAL_PATTERN =
  /^(?=.+$)M{0,3}(?:CM|CD|D?C{0,3})(?:XC|XL|L?X{0,3})(?:IX|IV|V?I{0,3})$/;
const SMALL_WORDS = new Set(["of", "and", "for", "the", "in", "at", "on", "to", "by"]);
const KNOWN_ACRONYMS = new Set([
  "IIT",
  "IIM",
  "NIT",
  "IIIT",
  "AIIMS",
  "IISER",
  "IIEST",
  "NIFT",
  "NID",
  "SRM",
  "VIT",
  "KIIT",
  "JIS",
  "BIT",
  "MIT",
  "PSG",
  "SSN",
  "BMS",
  "RV",
  "PES",
  "CMR",
  "DAV",
  "SNDT",
  "LNCT",
  "KCG",
  "PPP",
  "ESTD",
  "GOVT",
]);
const caseInsensitiveCollator = new Intl.Collator("en", { sensitivity: "base" });

function assertSupportedNodeVersion() {
  const majorVersion = Number.parseInt(process.versions.node.split(".")[0], 10);

  if (!Number.isInteger(majorVersion) || majorVersion < 20) {
    throw new Error("Node.js 20 or newer is required.");
  }
}

function parseArguments(args) {
  const options = new Map();

  for (let index = 0; index < args.length; index += 1) {
    const flag = args[index];

    if (!flag.startsWith("--")) {
      throw new Error(`Unexpected argument: ${flag}`);
    }

    const optionName = flag.slice(2);
    if (!REQUIRED_OPTIONS.includes(optionName)) {
      throw new Error(`Unknown option: ${flag}`);
    }

    if (options.has(optionName)) {
      throw new Error(`Option may only be supplied once: ${flag}`);
    }

    const value = args[index + 1];
    if (!value || value.startsWith("--")) {
      throw new Error(`Missing value for ${flag}`);
    }

    options.set(optionName, value);
    index += 1;
  }

  for (const optionName of REQUIRED_OPTIONS) {
    if (!options.has(optionName)) {
      throw new Error(`Missing required option: --${optionName}`);
    }
  }

  return Object.fromEntries(
    REQUIRED_OPTIONS.map((optionName) => [optionName, path.resolve(options.get(optionName))]),
  );
}

function normalizeDisplayName(value) {
  if (typeof value !== "string") return null;

  const normalized = value.trim().replace(/\s+/gu, " ");
  if (normalized.startsWith('"') && normalized.endsWith('"')) {
    const interior = normalized.slice(1, -1).trim();
    if (interior && !interior.includes('"')) return interior;
  }

  return normalized || null;
}

function dedupeKey(name) {
  return name
    .toLowerCase()
    .replace(/&/gu, " and ")
    .replace(/\p{P}/gu, "")
    .replace(/\s+/gu, " ")
    .trim();
}

function normalizeCountryCode(value) {
  if (typeof value !== "string") return null;

  const countryCode = value.trim().toUpperCase();
  return /^[A-Z]{2}$/.test(countryCode) ? countryCode : null;
}

function isAllCaps(name) {
  return name === name.toUpperCase() && name !== name.toLowerCase();
}

function titleCaseCore(core, isFirstWord) {
  const upperCore = core.toUpperCase();
  const comparisonCore = upperCore.replace(/\.+$/u, "");

  if (
    DOTTED_INITIALS_PATTERN.test(core) ||
    KNOWN_ACRONYMS.has(comparisonCore) ||
    ROMAN_NUMERAL_PATTERN.test(comparisonCore)
  ) {
    return upperCore;
  }

  if (core.includes("-") || core.includes("/")) {
    return core
      .split(/([-/])/u)
      .map((part, index) => {
        if (part === "-" || part === "/") return part;
        return titleCaseCore(part, isFirstWord && index === 0);
      })
      .join("");
  }

  const lowerCore = core.toLowerCase();
  if (!isFirstWord && SMALL_WORDS.has(lowerCore)) return lowerCore;

  return lowerCore.charAt(0).toUpperCase() + lowerCore.slice(1);
}

function titleCaseToken(token, isFirstWord) {
  if (token === "&") return token;

  const leading = token.match(/^[\(\[\{"“‘]+/u)?.[0] ?? "";
  const trailing = token.match(/[\)\]\}"”’',;:!?]+$/u)?.[0] ?? "";
  const core = token.slice(leading.length, token.length - trailing.length);

  if (!core) return token;

  return leading + titleCaseCore(core, isFirstWord) + trailing;
}

function titleCaseAllCaps(name) {
  let wordIndex = 0;
  const titleCased = name
    .split(/(\s+)/u)
    .map((token) => {
      if (!token || /^\s+$/u.test(token)) return token;

      const titleCasedToken = titleCaseToken(token, wordIndex === 0);
      wordIndex += 1;
      return titleCasedToken;
    })
    .join("");

  return titleCased.replace(/\(([a-z])/gu, (_match, firstLetter) => `(${firstLetter.toUpperCase()}`);
}

function isNonDegreeInstitution(name) {
  return NON_DEGREE_PATTERN.test(name);
}

function cleanAicteName(value) {
  const name = normalizeDisplayName(value);
  if (!name || isNonDegreeInstitution(name)) return null;

  return isAllCaps(name) ? titleCaseAllCaps(name) : name;
}

function parseJsonArray(contents, label) {
  let data;

  try {
    data = JSON.parse(contents.replace(/^\uFEFF/u, ""));
  } catch (error) {
    throw new Error(`Could not parse ${label}: ${error.message}`);
  }

  if (!Array.isArray(data)) {
    throw new Error(`${label} must contain a JSON array.`);
  }

  return data;
}

async function readJsonArray(filePath, label) {
  const contents = await readFile(filePath, "utf8");
  return parseJsonArray(contents, label);
}

function requireStringName(value, sourceLabel, index) {
  const name = normalizeDisplayName(value);

  if (!name) {
    throw new Error(`${sourceLabel} entry ${index + 1} must be a non-empty string.`);
  }

  return name;
}

async function readUgcNames(filePath) {
  const lines = (await readFile(filePath, "utf8"))
    .replace(/^\uFEFF/u, "")
    .split(/\r\n|\n|\r/u);

  if (lines[0]?.split(",")[1]?.trim() !== "Name") {
    throw new Error("UGC CSV must have Name as its second column.");
  }

  const names = [];

  for (const line of lines.slice(1)) {
    if (!/^\s*\d+\s*,/u.test(line)) continue;

    const firstCommaIndex = line.indexOf(",");
    const rest = line.slice(firstCommaIndex + 1);
    let name = "";

    if (rest[0] === '"') {
      for (let index = 1; index < rest.length; index += 1) {
        const character = rest[index];

        if (character === '"') {
          if (rest[index + 1] === '"') {
            name += '"';
            index += 1;
          } else {
            break;
          }
        } else {
          name += character;
        }
      }
    } else {
      const nextCommaIndex = rest.indexOf(",");
      name = nextCommaIndex === -1 ? rest : rest.slice(0, nextCommaIndex);
    }

    const normalizedName = normalizeDisplayName(name);
    if (!normalizedName || Number.isFinite(Number(normalizedName))) continue;

    names.push(normalizedName);
  }

  if (names.length === 0) {
    throw new Error("UGC CSV did not contain any university names.");
  }

  return names;
}

async function readExistingCountryFiles(outputDirectory) {
  const entries = await readdir(outputDirectory, { withFileTypes: true });
  const countries = new Map();

  for (const entry of entries) {
    if (!entry.isFile()) continue;

    const match = COUNTRY_FILE_PATTERN.exec(entry.name);
    if (!match) continue;

    const countryCode = match[1];
    const filePath = path.join(outputDirectory, entry.name);
    const contents = await readFile(filePath, "utf8");
    const data = parseJsonArray(contents, entry.name);
    const names = data.map((value, index) => requireStringName(value, entry.name, index));

    countries.set(countryCode, {
      contents,
      filePath,
      names,
      originalCount: data.length,
    });
  }

  return countries;
}

function groupHipoNames(records) {
  const namesByCountry = new Map();

  for (const record of records) {
    if (!record || typeof record !== "object") continue;

    const countryCode = normalizeCountryCode(record.alpha_two_code);
    const name = normalizeDisplayName(record.name);
    if (!countryCode || !name) continue;

    const names = namesByCountry.get(countryCode) ?? [];
    names.push(name);
    namesByCountry.set(countryCode, names);
  }

  return namesByCountry;
}

function mergeNameSources(sources) {
  const namesByKey = new Map();
  const contributions = Object.fromEntries(sources.map(({ label }) => [label, 0]));

  for (const { label, names } of sources) {
    for (const rawName of names) {
      const name = normalizeDisplayName(rawName);
      if (!name) continue;

      const key = dedupeKey(name);
      if (!key || namesByKey.has(key)) continue;

      namesByKey.set(key, name);
      contributions[label] += 1;
    }
  }

  return {
    contributions,
    names: [...namesByKey.values()].sort(caseInsensitiveCollator.compare),
  };
}

function printStats({ changedCountryFiles, globalAfter, globalBefore, indiaAfter, indiaBefore, indiaContributions }) {
  console.log("IN source contributions");
  console.table(
    Object.entries(indiaContributions).map(([source, contribution]) => ({
      source,
      contribution,
    })),
  );

  console.log("College dataset summary");
  console.table([
    { metric: "IN before", value: indiaBefore },
    { metric: "IN after", value: indiaAfter },
    { metric: "Country files changed", value: changedCountryFiles },
    { metric: "Global total before", value: globalBefore },
    { metric: "Global total after", value: globalAfter },
  ]);
}

async function main() {
  assertSupportedNodeVersion();
  const options = parseArguments(process.argv.slice(2));

  await mkdir(options.out, { recursive: true });

  const [aicteRecords, curatedData, hipoRecords, ugcNames, existingCountries] = await Promise.all([
    readJsonArray(options.aicte, "AICTE dump"),
    readJsonArray(options.curated, "curated India list"),
    readJsonArray(options.hipo, "Hipo dataset"),
    readUgcNames(options["ugc-csv"]),
    readExistingCountryFiles(options.out),
  ]);

  const curatedNames = curatedData.map((value, index) =>
    requireStringName(value, "curated India list", index),
  );
  const aicteNames = aicteRecords
    .map((record) => (record && typeof record === "object" ? cleanAicteName(record.institute_name) : null))
    .filter((name) => name !== null);
  const hipoNamesByCountry = groupHipoNames(hipoRecords);
  const existingIndia = existingCountries.get("IN");
  // Keep the final India list degree-focused even when its legacy or Hipo baseline has a match.
  const existingIndiaNames = (existingIndia?.names ?? []).filter(
    (name) => !isNonDegreeInstitution(name),
  );
  const hipoIndiaNames = (hipoNamesByCountry.get("IN") ?? []).filter(
    (name) => !isNonDegreeInstitution(name),
  );

  const countryCodes = new Set([...existingCountries.keys(), ...hipoNamesByCountry.keys(), "IN"]);
  const updates = [];
  let indiaContributions = null;
  let indiaAfter = 0;

  for (const countryCode of [...countryCodes].sort()) {
    const existingCountry = existingCountries.get(countryCode);
    const existingNames =
      countryCode === "IN" ? existingIndiaNames : existingCountry?.names ?? [];
    const sources =
      countryCode === "IN"
        ? [
            { label: "Curated", names: curatedNames },
            { label: "Existing IN.json", names: existingNames },
            { label: "UGC", names: ugcNames },
            { label: "AICTE", names: aicteNames },
            { label: "Hipo", names: hipoIndiaNames },
          ]
        : [
            { label: "Existing", names: existingNames },
            { label: "Hipo", names: hipoNamesByCountry.get(countryCode) ?? [] },
          ];
    const merged = mergeNameSources(sources);
    const contents = JSON.stringify(merged.names);
    const dedupedExistingCount = new Set(
      existingNames.map(dedupeKey).filter(Boolean),
    ).size;

    if (countryCode === "IN") {
      indiaContributions = merged.contributions;
      indiaAfter = merged.names.length;
    }

    updates.push({
      contents,
      countryCode,
      dedupedExistingCount,
      existingCountry,
      filePath: existingCountry?.filePath ?? path.join(options.out, `${countryCode}.json`),
      names: merged.names,
    });
  }

  const shrinkingFiles = updates.filter(
    ({ dedupedExistingCount, existingCountry, names }) =>
      existingCountry && names.length < dedupedExistingCount,
  );

  if (shrinkingFiles.length > 0) {
    const details = shrinkingFiles
      .map(
        ({ countryCode, dedupedExistingCount, names }) =>
          `${countryCode}: ${dedupedExistingCount} (unique existing) -> ${names.length}`,
      )
      .join(", ");
    throw new Error(`Refusing to write a smaller country file: ${details}`);
  }

  const changedUpdates = updates.filter(
    ({ contents, existingCountry }) => !existingCountry || existingCountry.contents !== contents,
  );

  await Promise.all(changedUpdates.map(({ contents, filePath }) => writeFile(filePath, contents, "utf8")));

  const globalBefore = [...existingCountries.values()].reduce(
    (total, country) => total + country.originalCount,
    0,
  );
  const globalAfter = updates.reduce((total, update) => total + update.names.length, 0);

  printStats({
    changedCountryFiles: changedUpdates.length,
    globalAfter,
    globalBefore,
    indiaAfter,
    indiaBefore: existingIndia?.originalCount ?? 0,
    indiaContributions: indiaContributions ?? {},
  });
}

main().catch((error) => {
  console.error(`College dataset build failed: ${error.message}`);
  process.exitCode = 1;
});
