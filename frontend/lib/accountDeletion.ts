/** UI-only comparison; the API verifies the token before trusting its claims. */
export function tokenIssuedAt(token: string): number | null {
  try {
    const payload = token.split(".")[1].replace(/-/g, "+").replace(/_/g, "/");
    const issued = JSON.parse(atob(payload)).iat;
    return typeof issued === "number" ? issued : null;
  } catch {
    return null;
  }
}

/** App data on this device. Bookmarks are held in memory and reset on sign-out. */
export function clearDeletedAccountStorage(): void {
  for (const name of ["localStorage", "sessionStorage"] as const) {
    try {
      const storage = window[name];
      for (let index = storage.length - 1; index >= 0; index--) {
        const key = storage.key(index);
        if (key && (/^aspirova[.:_]/.test(key) || /^sb-.+-auth-token(?:-code-verifier)?$/.test(key))) {
          storage.removeItem(key);
        }
      }
    } catch {
      // Storage may be unavailable in privacy-restricted contexts.
    }
  }
  window.dispatchEvent(new Event("storage"));
}
