import type { SupabaseClient } from "@supabase/supabase-js";
import { toast } from "sonner";
import { clearStoredSkillNames } from "@/lib/personalizationSkills";

export async function signOutWithFeedback(
  supabase: SupabaseClient,
  scope?: "global",
): Promise<boolean> {
  try {
    const { error } = await supabase.auth.signOut(scope ? { scope } : undefined);
    if (error) throw error;
  } catch {
    toast.error("We couldn't sign you out. Check your connection and try again.");
    return false;
  }
  clearStoredSkillNames();
  try {
    for (let index = sessionStorage.length - 1; index >= 0; index--) {
      const key = sessionStorage.key(index);
      if (key?.startsWith("aspirova:profile-draft:")) sessionStorage.removeItem(key);
    }
  } catch {
    // Storage may be unavailable in privacy-restricted browser contexts.
  }
  return true;
}
