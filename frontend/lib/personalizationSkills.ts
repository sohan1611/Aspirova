import { useSyncExternalStore } from "react";
import { useHydrated } from "@/lib/useHydrated";

export const SKILLS_STORAGE_KEY = "aspirova.skills";
const SKILLS_OWNER_STORAGE_KEY = "aspirova.skills.owner";
export const SKILLS_EVENT = "aspirova:skills-change";

const EMPTY_SKILL_NAMES: string[] = [];

let cachedRawValue: string | null | undefined;
let cachedSnapshot = EMPTY_SKILL_NAMES;
let inMemoryRawValue: string | null = null;
let inMemoryOwnerId: string | null = null;
let storageUnavailable = false;

function normalizeSkillNames(values: unknown): string[] {
  if (!Array.isArray(values)) return [];

  const skillNames: string[] = [];
  const seen = new Set<string>();
  for (const value of values) {
    if (typeof value !== "string") continue;

    const skillName = value.trim();
    const normalizedName = skillName.toLowerCase();
    if (!skillName || seen.has(normalizedName)) continue;

    seen.add(normalizedName);
    skillNames.push(skillName);

    if (skillNames.length === 100) break;
  }

  return skillNames;
}

function readStoredValue(): string | null {
  if (typeof window === "undefined") return null;
  if (storageUnavailable) return inMemoryRawValue;

  try {
    return window.localStorage.getItem(SKILLS_STORAGE_KEY);
  } catch {
    // Storage can be unavailable in privacy-restricted browser contexts.
    storageUnavailable = true;
    return inMemoryRawValue;
  }
}

function getSkillNamesSnapshot(): string[] {
  const rawValue = readStoredValue();
  if (rawValue === cachedRawValue) return cachedSnapshot;

  cachedRawValue = rawValue;
  if (!rawValue) {
    cachedSnapshot = EMPTY_SKILL_NAMES;
    return cachedSnapshot;
  }

  try {
    const parsed: unknown = JSON.parse(rawValue);
    cachedSnapshot = normalizeSkillNames(parsed);
  } catch {
    cachedSnapshot = EMPTY_SKILL_NAMES;
  }

  return cachedSnapshot;
}

function getSkillNamesOwnerSnapshot(): string | null {
  if (typeof window === "undefined") return null;
  if (storageUnavailable) return inMemoryOwnerId;

  try {
    return window.localStorage.getItem(SKILLS_OWNER_STORAGE_KEY);
  } catch {
    // Keep ownership available alongside the in-memory skills fallback.
    storageUnavailable = true;
    return inMemoryOwnerId;
  }
}

function subscribeToSkillNames(onStoreChange: () => void): () => void {
  if (typeof window === "undefined") return () => {};

  window.addEventListener(SKILLS_EVENT, onStoreChange);
  window.addEventListener("storage", onStoreChange);

  return () => {
    window.removeEventListener(SKILLS_EVENT, onStoreChange);
    window.removeEventListener("storage", onStoreChange);
  };
}

function getServerSnapshot(): string[] {
  return EMPTY_SKILL_NAMES;
}

export function readStoredSkillNames(): string[] {
  return getSkillNamesSnapshot();
}

export function storeSkillNames(names: string[], ownerId: string): void {
  const normalizedNames = normalizeSkillNames(names);
  const rawValue = JSON.stringify(normalizedNames);

  cachedRawValue = rawValue;
  cachedSnapshot = normalizedNames;
  inMemoryRawValue = rawValue;
  inMemoryOwnerId = ownerId;

  if (typeof window === "undefined") return;

  try {
    window.localStorage.setItem(SKILLS_STORAGE_KEY, rawValue);
    window.localStorage.setItem(SKILLS_OWNER_STORAGE_KEY, ownerId);
    storageUnavailable = false;
  } catch {
    // The in-memory snapshot remains available for this browser session.
    storageUnavailable = true;
  }

  window.dispatchEvent(new Event(SKILLS_EVENT));
}

export function clearStoredSkillNames(): void {
  cachedRawValue = null;
  cachedSnapshot = EMPTY_SKILL_NAMES;
  inMemoryRawValue = null;
  inMemoryOwnerId = null;

  if (typeof window === "undefined") return;

  try {
    window.localStorage.removeItem(SKILLS_STORAGE_KEY);
    window.localStorage.removeItem(SKILLS_OWNER_STORAGE_KEY);
    storageUnavailable = false;
  } catch {
    // The in-memory snapshot is still cleared when storage is unavailable.
    storageUnavailable = true;
  }

  window.dispatchEvent(new Event(SKILLS_EVENT));
}

export function useSkillNamesOwner(): string | null {
  return useSyncExternalStore(
    subscribeToSkillNames,
    getSkillNamesOwnerSnapshot,
    () => null,
  );
}

export function useSkillNames(): { skillNames: string[]; hydrated: boolean } {
  const skillNames = useSyncExternalStore(
    subscribeToSkillNames,
    getSkillNamesSnapshot,
    getServerSnapshot,
  );
  const hydrated = useHydrated();

  return { skillNames, hydrated };
}
