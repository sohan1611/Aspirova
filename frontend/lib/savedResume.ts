import { formatDate } from "@/lib/date";
import { createClient } from "@/lib/supabase/client";
import type { AccountMe } from "@/lib/types";

export const RESUME_BUCKET = "resumes";
export const MAX_RESUME_PDF_BYTES = 5 * 1024 * 1024;
export const RESUME_STORAGE_FILENAME = "resume.pdf";
export const MAX_PROFILE_SKILLS = 100;

export type ProfileSkill = NonNullable<AccountMe["skills"]>[number];

export function getStoredResumePath(userId: string): string {
  return `${userId}/${RESUME_STORAGE_FILENAME}`;
}

export function getSkillKey(name: string): string {
  return name.trim().toLowerCase();
}

export function mergeSkills(
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

export function formatSavedResumeUploadedAt(uploadedAt: string): string {
  const formattedDate = formatDate(uploadedAt);
  return formattedDate ? `Uploaded ${formattedDate}` : "Upload date unavailable";
}

export async function validateResumePdf(file: File): Promise<string | null> {
  try {
    if (await file.slice(0, 5).text() !== "%PDF-") {
      return "Choose a PDF resume to continue.";
    }
  } catch {
    return "Choose a PDF resume to continue.";
  }

  if (file.size > MAX_RESUME_PDF_BYTES) {
    return "Resume PDFs must be 5 MB or smaller.";
  }
  if (file.name.length > 255) {
    return "Use a shorter PDF filename before uploading.";
  }
  return null;
}

export async function uploadResumePdf(userId: string, file: File): Promise<string> {
  const path = getStoredResumePath(userId);
  const { error } = await createClient()
    .storage.from(RESUME_BUCKET)
    .upload(path, file, {
      upsert: true,
      contentType: "application/pdf",
    });

  if (error) throw error;
  return path;
}

export async function removeResumePdf(path: string): Promise<void> {
  const { error } = await createClient().storage.from(RESUME_BUCKET).remove([path]);
  if (error) throw error;
}

export async function openResumePdf(path: string): Promise<void> {
  const { data, error } = await createClient()
    .storage.from(RESUME_BUCKET)
    .createSignedUrl(path, 60);

  if (error || !data?.signedUrl) {
    throw error ?? new Error("Missing signed URL");
  }
  window.open(data.signedUrl, "_blank", "noopener,noreferrer");
}
