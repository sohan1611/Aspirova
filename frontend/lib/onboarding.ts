const ONBOARDED_STORAGE_KEY = "aspirova.onboarded";
const ONBOARDED_EVENT = "aspirova:onboarded-change";

let inMemoryOnboardingComplete = false;

export function hasCompletedOnboarding(): boolean {
  try {
    return window.localStorage.getItem(ONBOARDED_STORAGE_KEY) === "true";
  } catch {
    return inMemoryOnboardingComplete;
  }
}

export function subscribeToOnboarding(onStoreChange: () => void): () => void {
  window.addEventListener(ONBOARDED_EVENT, onStoreChange);
  window.addEventListener("storage", onStoreChange);

  return () => {
    window.removeEventListener(ONBOARDED_EVENT, onStoreChange);
    window.removeEventListener("storage", onStoreChange);
  };
}

export function markOnboardingComplete(): void {
  inMemoryOnboardingComplete = true;

  try {
    window.localStorage.setItem(ONBOARDED_STORAGE_KEY, "true");
  } catch {
    // A later visit can ask again if storage is unavailable.
  }
  window.dispatchEvent(new Event(ONBOARDED_EVENT));
}

export function getServerOnboardingState(): boolean {
  return false;
}
