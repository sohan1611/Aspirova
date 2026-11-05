import {
  isAuthError,
  isAuthRetryableFetchError,
  isAuthSessionMissingError,
  isAuthWeakPasswordError,
} from "@supabase/supabase-js";

export const AUTH_CONNECTION_ERROR = "We couldn't reach the sign-in service. Check your connection and try again.";

export function passwordUpdateErrorMessage(error: unknown, context: "reset" | "account"): string {
  const code = isAuthError(error) ? error.code : undefined;
  const status = isAuthError(error) ? error.status : undefined;

  // supabase-js also calls 5xx responses "retryable". The student's connection is fine then, so
  // only a request that never got an answer (status 0) should send them to check it.
  if (isAuthRetryableFetchError(error) && error.status >= 500) {
    return "We couldn't update your password. Please try again.";
  }
  if (isAuthRetryableFetchError(error) || error instanceof TypeError || code === "request_timeout") {
    return AUTH_CONNECTION_ERROR;
  }
  if (code === "same_password") {
    return "That's already your password. Choose a different one.";
  }
  if (isAuthWeakPasswordError(error) && error.reasons.includes("pwned")) {
    return "This password has appeared in a data breach. Choose a different one.";
  }
  if (isAuthWeakPasswordError(error) || code === "weak_password") {
    return "That password is too easy to guess. Choose a longer or less common one.";
  }
  if (code === "over_request_rate_limit" || status === 429) {
    return "Too many attempts. Wait a minute and try again.";
  }
  if (code === "reauthentication_needed" || code === "reauthentication_not_valid") {
    return "For your security, sign in again, then change your password.";
  }
  if (
    isAuthSessionMissingError(error) ||
    code === "session_not_found" ||
    code === "session_expired" ||
    code === "bad_jwt" ||
    code === "refresh_token_not_found"
  ) {
    return context === "reset"
      ? "This reset link has expired. Request a new one from the sign-in form."
      : "Your session has expired. Sign in again, then change your password.";
  }
  return "We couldn't update your password. Please try again.";
}
