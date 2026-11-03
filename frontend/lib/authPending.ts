// Mark likely signed-in visits before paint; the key regex excludes -code-verifier.
// Clear after 8000 ms so a stalled token refresh cannot keep Sign in hidden.
export const AUTH_PENDING_SCRIPT = `(function(){try{var pending=/(?:^|[?&])code(?:=|&|$)/.test(window.location.search);if(!pending){for(var i=0;i<localStorage.length;i++){if(/^sb-.+-auth-token$/.test(localStorage.key(i))){pending=true;break;}}}if(pending){document.documentElement.setAttribute("data-auth-pending","");setTimeout(function(){document.documentElement.removeAttribute("data-auth-pending");},8000);}}catch(e){}})();`;

export function isAuthPending(): boolean {
  return (
    typeof document !== "undefined" &&
    document.documentElement.hasAttribute("data-auth-pending")
  );
}

export function clearAuthPending() {
  if (typeof document !== "undefined") {
    document.documentElement.removeAttribute("data-auth-pending");
  }
}
