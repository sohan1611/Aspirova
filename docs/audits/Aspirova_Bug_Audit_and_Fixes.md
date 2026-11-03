# ASPIROVA — BUG HUNT & REMEDIATION BACKLOG

**Audit date:** 4 November 2026 (IST)  
**Target:** https://www.aspirova.org/  
**Code baseline:** [`sohan1611/Aspirova`, `master`, commit `a90c6e1`](https://github.com/sohan1611/Aspirova/tree/a90c6e1918b7145d653593922e81a6d541ab5c41), committed 3 November 2026 at 16:40 UTC.  
**Focus:** Account, profile, sign-in, security, preferences, saved searches, saved opportunities, opportunity integrity, application handoff, reliability.

> **Evidence integrity:** This document combines direct inspection of publicly served Aspirova pages with line-level inspection of the public source code. **Authenticated browser journeys, actual payment transactions, OAuth provider callbacks, mobile device rendering, production database inspection, email delivery, and destructive/security penetration tests were NOT executed.** The source commit is recent but may differ from production deployment. Therefore, a code-confirmed design defect is not described as an observed production exploit; reproduction steps specify how to confirm it. No credentials were requested or used. Do not turn test hypotheses into factual bug claims.

## Quick verdict

**Prioritize account privacy and account-creation concurrency, internship classification, source transparency, and account/settings trust before new features.** A public Stripe *New Grad* role is marked **Internship** and the rules-based normalizer explicitly categorizes `new grad` as internship. A SemiAnalysis page claims the Apply destination is the company's own page while its hyperlink goes to **himalayas.app**. The signup code distinguishes an already-registered address with a publicly visible message; whether a specific production Supabase configuration returns that response requires a controlled test. Profile/account UX has several independently identifiable shortcomings: false paid-toggle ON states, a very narrow “complete” score, guest-state flashing while auth loads, browser-only country selection presented in the account profile, lost unsaved edits, and deletion only by emailing support.

### Status and severity legend

- **E1 / observed public page:** Public page/text/link inspected; may change with refresh. Does not imply authenticated interaction testing.
- **E2 / code confirmed:** Exact implementation is present in pinned repository commit. Production parity and user-facing reproduction must still be confirmed.
- **E3 / plausible race or unexecuted scenario:** Static analysis identifies a credible failure path; explicitly needs stress/E2E testing.
- **P0:** Critical confirmed exploit/data loss/outage. **None is claimed here.**
- **P1:** High impact security/privacy, core workflow, or trust/data-integrity problem.
- **P2:** Significant UX/account correctness or reliability fault.
- **P3:** Lower-severity polish, consistency, or emerging risk.

## Severity-ranked index

| ID | Priority | Confidence | Area | Finding |
|---|---|---|---|---|
| A-01 | P1 | E2; production behavior conditional | Authentication | Signup announces whether an email is already registered; potential account enumeration |
| A-02 | P1 | E3 high-confidence race | First-time signup | Simultaneous first authenticated API calls can collide inserting the same user |
| D-01 | P1 | E1 + E2 | Opportunity classification | “New Grad” positions are misfiled as internships by explicit normalizer rule |
| D-02 | P1 | E1 | Listing provenance | “Company's own listing” claim contradicted by an aggregator Apply URL |
| D-03 | P2 | E1 + investigation | Company directory | Separate near-identical company identities; potential duplicate/forked employer records |
| D-04 | P2 | E1 + investigation | Listing quality | Suspicious concatenated/malformed titles in feed; verify raw row and visual DOM |
| A-03 | P2 | E2 | Account hydration | Signed-in account route initially renders signed-out prompt |
| A-04 | P2 | E2 | Notifications | Paid-only preferences can appear enabled on free plan |
| A-05 | P2 | E2 | Profile | Profile can appear 100% complete with no interests/skills/resume |
| A-06 | P2 | E2 | Profile preferences | Country selection on account page is local-only, not account-synced |
| A-07 | P2 | E2 | Profile | Changing college country leaves prior selected college intact |
| A-08 | P2 | E2 | Profile | Navigating to another account section discards unsaved edits without warning |
| A-09 | P2 | E2 | Account deletion | “Delete account” button leads only to support email instructions |
| A-10 | P2 | E2 | Saved searches | Destructive delete has no confirmation/undo |
| A-11 | P2 | E2 | Password/email signup | Sign-in/signup submit lacks catch for thrown transport errors |
| A-12 | P2 | E2; trigger conditional | Resume storage | PDF upload and profile metadata save are not atomic |
| A-13 | P2 | E2, policy choice | Apply conversion | Guest clicking external Apply is blocked by sign-in gate |
| A-17 | P2 | E2, only on first OAuth initialization | Profile onboarding | New social-login user is created without importing available display name |
| A-14 | P3 | E2 | Dashboard statistics | “Saved” count includes items in application stages |
| A-15 | P3 | E3 | Saved/bookmark UX | Fast repeated bookmark taps may race without in-flight lock |
| A-16 | P3 | E2 | Security/settings | Global sign-out failure and device-state clarity need explicit handling |

---

## Account and profile: line-level findings

### A-01 — Signup reveals account-existence state [P1, E2; production behavior conditional]

**Source:** [`frontend/components/AuthWidget.tsx#L133-L159`](https://github.com/sohan1611/Aspirova/blob/a90c6e1918b7145d653593922e81a6d541ab5c41/frontend/components/AuthWidget.tsx#L133-L159) and [`#L217-L225`](https://github.com/sohan1611/Aspirova/blob/a90c6e1918b7145d653593922e81a6d541ab5c41/frontend/components/AuthWidget.tsx#L217-L225).

**Evidence/root cause:** After `supabase.auth.signUp`, if `data.user.identities` is an empty array, the UI chooses `already-registered` and explicitly displays **“That email already has an account”**. This exposes an account-existence oracle **in Supabase configurations that return that decoy response**. The code even comments that Supabase's decoy avoids enumeration, then branches on it. This is more serious than ordinary wording: someone can attempt signup against addresses they do not own and learn that an address is registered.

**Controlled validation:** On nonproduction/test Supabase and with authorization, register a test address; submit that address and an unregistered test address in signup, compare visible notices, statuses, body structure, response timing. Do **not** enumerate real addresses. Assert no distinguishable existence message.

**Fix:** Return a **neutral, identical user-visible response** for both cases, e.g. “If the address is eligible, check your inbox for the next steps.” Provide both “Sign in” and “Reset password” navigation without confirming membership. Normalize server-side auth errors carefully; rate-limit signup/reset and retain provider security mechanisms. Add mocked Supabase response unit tests for `{identities: []}` vs ordinary signups, and an end-to-end privacy regression with test accounts.

**Done when:** No response text leaks whether an arbitrary email already has an Aspirova account. Genuine users can still move to sign-in or recovery.

### A-02 — First authenticated requests can race to create the same user [P1, E3]

**Source:** [`backend/api/auth.py#L61-L73`](https://github.com/sohan1611/Aspirova/blob/a90c6e1918b7145d653593922e81a6d541ab5c41/backend/api/auth.py#L61-L73).

**Evidence/root cause:** `get_current_user()` does `db.get(User, user_id)`, then if absent `db.add(User(...)); db.commit()` with no conflict recovery/upsert. The account page loads user info and bookmarks; other components may concurrently call authenticated endpoints immediately after signup. Two requests may both see no user, and one insert may hit a unique-key integrity error → 500. **This race has not been stress-reproduced against production**; it follows from the read-before-insert pattern.

**Repro to execute:** In a test database, create a Supabase test identity not yet mirrored in `users`. Issue 10–30 simultaneous authenticated requests to `/account/me`, `/bookmarks`, `/saved-searches` with synchronized start. Log response statuses and resulting user count. Repeat over several clean users.

**Fix:** Use PostgreSQL `INSERT ... ON CONFLICT (id) DO NOTHING` in a transaction, then select the row, or catch the specific uniqueness IntegrityError with rollback/re-read. Ensure dependent operations can safely proceed even when another request won the race. Log one successful initialization.

**Done when:** Every concurrent request returns its intended response, exactly one user row exists, and no duplicate-key 500 occurs. Add a concurrent-initialization integration test.

### A-03 — Signed-in user sees signed-out account state while auth resolves [P2, E2]

**Source:** [`frontend/app/account/page.tsx`](https://github.com/sohan1611/Aspirova/blob/a90c6e1918b7145d653593922e81a6d541ab5c41/frontend/app/account/page.tsx), `if (!session)` branch; [`frontend/lib/useSession.ts#L62-L99`](https://github.com/sohan1611/Aspirova/blob/a90c6e1918b7145d653593922e81a6d541ab5c41/frontend/lib/useSession.ts#L62-L99).

**Evidence/root cause:** `useSession()` initially returns `null` while `useSessionState()` explicitly tracks `resolved:false`. `AccountPageContent` treats `null` as signed-out immediately. On a slow session lookup, signed-in users can see “Sign in to manage your account” before content changes.

**Repro:** Be signed in; throttle network; hard-refresh `/account?section=profile`; record first painted account state with video. Validate across Chrome/Safari/mobile. This is a **code-confirmed potential transient UI**; its duration depends on runtime.

**Fix:** Use `const {session,resolved}=useSessionState()` and show the account skeleton while `!resolved`. Show the sign-in prompt only after resolved and no session. Verify accessibility `aria-busy` and avoid hydration mismatch.

**Done when:** Signed-in reload never paints a guest call-to-action; expired session eventually shows guest state.

### A-04 — Paid-only notification switches can show ON to free members [P2, E2]

**Source:** [`frontend/components/account/NotificationsSection.tsx#L77-L107`](https://github.com/sohan1611/Aspirova/blob/a90c6e1918b7145d653593922e81a6d541ab5c41/frontend/components/account/NotificationsSection.tsx#L77-L107), [`#L117-L149`](https://github.com/sohan1611/Aspirova/blob/a90c6e1918b7145d653593922e81a6d541ab5c41/frontend/components/account/NotificationsSection.tsx#L117-L149).

**Evidence/root cause:** `enabled = notificationPrefs[key] !== false` (so missing key is ON), while paid entitlement is evaluated separately as `includedWithPlan`. Switch remains interactive, even when UI says “Included with a paid plan”. A free user may see **Instant alerts** / **Weekly career report** ON although the plan cannot deliver them. This is **not evidence that backend sends paid email for free users**; it is a mismatched visible state.

**Repro:** Open `/account?section=notifications` as new free and paid test users, inspect switch state and entitlement labels, toggle, re-login and inspect persisted state and actual email schedule separately.

**Fix:** Represent 3 states: `available+enabled`, `available+disabled`, and `locked`. For locked features, display OFF/locked with a nearby upgrade action; don't silently persist a misleading enabled state. Align actual send logic with plan entitlements and test each plan transition.

**Done when:** Free users never see a paid capability described as active; a paid user's selected preference survives renewal/downgrade and accurately predicts delivery.

### A-05 — Three fields can produce a misleading “100% complete” profile [P2, E2]

**Source:** [`frontend/lib/profileCompleteness.ts#L1-L24`](https://github.com/sohan1611/Aspirova/blob/a90c6e1918b7145d653593922e81a6d541ab5c41/frontend/lib/profileCompleteness.ts#L1-L24); account progress shown in `frontend/app/account/page.tsx` and `ProfileSection.tsx`.

**Evidence/root cause:** Completeness is exactly **display name + college + graduation year**. A user who has added none of the interests, skills, resume, experience or search preferences can show 3/3. `ProfileSection` asks for “remaining academic details,” but the adjacent service promises personalization. Existing three-field score isn't itself a program error; it's **misleading product labeling**.

**Repro:** On a test account, set only these three fields, leave fields/interests/skills/resume blank; check profile badge and recommendations.

**Fix:** Either rename the indicator **“Academic basics: 3/3”**, or implement a richer, transparent profile-readiness checklist (identity, education, interests, skills, roles, location, resume optional) with optional items not coercively required. Don't infer employability from completeness.

**Done when:** A nominal 100% label cannot be achieved while essential personalization sections are absent unless explicitly scoped as “basics.”

### A-06 — Account-country preference does not follow the account [P2, E2, currently documented]

**Source:** [`frontend/components/account/ProfileSection.tsx#L117-L120`](https://github.com/sohan1611/Aspirova/blob/a90c6e1918b7145d653593922e81a6d541ab5c41/frontend/components/account/ProfileSection.tsx#L117-L120); [`frontend/lib/country.ts`](https://github.com/sohan1611/Aspirova/blob/a90c6e1918b7145d653593922e81a6d541ab5c41/frontend/lib/country.ts); [Privacy Policy](https://www.aspirova.org/privacy).

**Evidence/root cause:** Account → Profile lets the user select a country, but `storeCountryCode` writes only `localStorage`. Privacy Policy explicitly discloses this, so this is **not a hidden privacy bug**; it's an expectation/consistency defect in an *account-level* settings screen. The same user on another device can see a different country, currency and recommendations.

**Repro:** Sign in on laptop, choose a country; sign in to same account on clean phone browser; compare selected country and feed preferences. Then clear local storage and reload laptop.

**Fix:** Distinguish **Browsing country (this device)** from **Preferred opportunity locations (account)** and offer sync. Preserve privacy transparency and migrate existing local values only with clear selection rules; use server-authoritative country preference for authenticated users and device-local fallback for guests.

**Done when:** Users know whether the setting is local or synced and profile context behaves predictably across devices.

### A-07 — Changing country does not reset/validate already selected college [P2, E2]

**Source:** [`frontend/components/account/ProfileSection.tsx#L117-L120`](https://github.com/sohan1611/Aspirova/blob/a90c6e1918b7145d653593922e81a6d541ab5c41/frontend/components/account/ProfileSection.tsx#L117-L120), `CollegePicker` receives existing `college` at lines ~277–284.

**Evidence/root cause:** Country change calls `storeCountryCode(code)` and resets entry mode to `list`, **but does not clear or validate `college`**. Example: choose an Indian college, switch to US, and the stored college can remain selected despite US-specific selector context. Clearing unconditionally could lose legitimate data, so choose UX deliberately.

**Repro:** Set India → select Indian college → save; switch to another country → inspect selected text/available choices → save another field; reload.

**Fix:** If new country and chosen college are incompatible, show “Your college is outside the selected country—keep it or choose a new college?” Do not silently discard. Validate with country/college mapping; allow manual international colleges.

**Done when:** Changing country cannot silently imply a contradictory university context.

### A-08 — Unsaved profile edits disappear on settings-tab change [P2, E2]

**Source:** [`frontend/components/account/ProfileSection.tsx#L80-L86`](https://github.com/sohan1611/Aspirova/blob/a90c6e1918b7145d653593922e81a6d541ab5c41/frontend/components/account/ProfileSection.tsx#L80-L86) maintains unsaved component state; [`frontend/app/account/page.tsx`](https://github.com/sohan1611/Aspirova/blob/a90c6e1918b7145d653593922e81a6d541ab5c41/frontend/app/account/page.tsx) conditionally mounts one account section and changes `section` URL parameter.

**Evidence/root cause:** Editing name/college/year sets local state. Selecting Subscription, Security, etc. unmounts `ProfileSection`; returning reinitializes from last saved account data. There is no visible dirty-state guard.

**Repro:** Change display name but do **not** Save; click Notifications; return to Profile; inspect edit. Repeat via browser back and reload.

**Fix:** Warn “Discard unsaved changes?” on section change and route leave, or persist draft in parent store; preserve browser back and only clear after successfully saved. Keep focused user input intact.

**Done when:** A user can never lose an unsaved form silently by ordinary account navigation.

### A-09 — “Delete account” CTA is not a deletion workflow [P2, E2]

**Source:** [`frontend/components/account/SecuritySection.tsx#L196-L235`](https://github.com/sohan1611/Aspirova/blob/a90c6e1918b7145d653593922e81a6d541ab5c41/frontend/components/account/SecuritySection.tsx#L196-L235) + [Privacy Policy](https://www.aspirova.org/privacy).

**Evidence/root cause:** The primary red button reads “Delete account”; click opens a dialog saying it isn't self-serve and supplies support email. This is transparent once opened, but the button promises an action the app doesn't provide. No account deletion API was found in reviewed account module. **Not claiming rights violation; compliance and retention require separate counsel review.**

**Repro:** As test account visit Security → Delete account; inspect flow and whether deletion is executed automatically. No destructive testing against a real user.

**Fix now:** Rename CTA “Request account deletion”, open prefilled support request with status/tracking, include expected response timeline and data categories; keep user confirmation. **Feature follow-up:** Secure self-service deletion with recent-auth check, active-subscription coordination, Supabase identity removal, own DB cascade, storage removal, backups policy, audit receipt and grace window.

**Done when:** The name and effect of the control match; users can track their request and know what happens to their files and subscriptions.

### A-10 — Saved-search delete has no confirmation or undo [P2, E2]

**Source:** [`frontend/components/account/SavedSearchesSection.tsx#L137-L177`](https://github.com/sohan1611/Aspirova/blob/a90c6e1918b7145d653593922e81a6d541ab5c41/frontend/components/account/SavedSearchesSection.tsx#L137-L177), [`#L329-L350`](https://github.com/sohan1611/Aspirova/blob/a90c6e1918b7145d653593922e81a6d541ab5c41/frontend/components/account/SavedSearchesSection.tsx#L329-L350).

**Evidence/root cause:** Click Delete immediately performs optimistic removal and sends DELETE. On network failure it restores, but **on successful accidental click there is no recovery**. Saved search names/complex filters may be hard to recreate.

**Repro:** Use a disposable saved search; click Delete once and observe no confirmation/undo; reload to confirm persistence.

**Fix:** Confirmation dialog with name and clear destructive wording **or** temporary 6–10 second Undo with deferred commit (prefer both if UI is dense). Disable repeated clicks and retain failure restore.

**Done when:** One accidental tap cannot irreversibly erase a search with no second decision or undo opportunity.

### A-11 — Sign-in and signup may fail silently when SDK throws [P2, E2, conditional]

**Source:** [`frontend/components/AuthWidget.tsx#L109-L162`](https://github.com/sohan1611/Aspirova/blob/a90c6e1918b7145d653593922e81a6d541ab5c41/frontend/components/AuthWidget.tsx#L109-L162).

**Evidence/root cause:** Submit has `try { await ... } finally { setLoading(false); }`, but **no catch** for exceptional network/transport SDK errors. The SDK usually returns `{error}` for normal auth failures, but thrown exceptions can result in an unhandled rejection, no useful form error and a reset loading button. Forgot password/OAuth handlers do implement catches.

**Repro:** In Playwright, mock `signInWithPassword`/`signUp` to reject; assert error inline and retry possible. Also test network loss mid-request.

**Fix:** Catch exceptions and present safe, actionable status; don't echo raw internal stack/provider messages. Protect against form resubmission and preserve email field.

**Done when:** Every auth failure, including thrown exceptions, is recoverable without refreshing.

### A-12 — Resume PDF write can succeed while account metadata fails [P2, E2; failure path]

**Source:** [`frontend/components/ResumeMatchPage.tsx`](https://github.com/sohan1611/Aspirova/blob/a90c6e1918b7145d653593922e81a6d541ab5c41/frontend/components/ResumeMatchPage.tsx), `handleResumeUpload` around lines 335–420; `RESUME_MATCHES_ENABLED = false` at line 76.

**Evidence/root cause:** Browser uploads private PDF to Supabase Storage then PATCHes metadata/skills/ATS to API. On failure after upload, UI says “We stored the PDF but couldn't save its profile metadata.” Explicitly acknowledged partial success; can produce stored-file/profile mismatch. This is **not evidence of a public file**; policy states private storage and bucket permissions need independent validation.

**Repro:** With test account, make file upload succeed but mock PATCH failure; verify storage, account state, retries, open/delete behavior and orphan cleanup.

**Fix:** Prefer backend-orchestrated two-phase upload or idempotent staged metadata with rollback/reconciliation; use versioned object keys and atomic pointer swap when database confirmed. Enforce auth-UID path ownership via storage RLS, MIME+magic-byte/size validation, retention, error recovery. Distinguish **ATS readiness estimate** from **disabled AI resume matching** in copy.

**Done when:** Every failure leaves a clearly recoverable state without orphaned/stale resume references; two-user isolation tests succeed.

### A-13 — Guest Apply is intentionally gated before external destination [P2, E1 + E2, product-choice defect]

**Source:** [`frontend/components/ApplyLink.tsx#L80-L106`](https://github.com/sohan1611/Aspirova/blob/a90c6e1918b7145d653593922e81a6d541ab5c41/frontend/components/ApplyLink.tsx#L80-L106), [`#L127-L196`](https://github.com/sohan1611/Aspirova/blob/a90c6e1918b7145d653593922e81a6d541ab5c41/frontend/components/ApplyLink.tsx#L127-L196); [FAQ](https://www.aspirova.org/faq).

**Evidence/root cause:** `shouldGate()` returns true for guests and `handleClick` prevents navigation, opening a sign-in dialog. FAQ explicitly acknowledges sign-in to apply, so **this is intentional, not a code regression**. But Aspirova does not submit applications itself; blocking a source link increases friction and could create a misleading expectation that applying requires an Aspirova account.

**Repro:** In signed-out browser, open public opportunity → click Apply; observe authentication dialog instead of employer destination. Compare with signed-in state. Check SEO and accessibility of the underlying `<a href>`.

**Recommended product correction:** Let guests **open the original listing without signup**. Keep account-required Save, tracker, alerts. For guests optionally ask “Track your applications? Create a free account” *after* the source link has opened, never as a precondition.

**Done when:** Every public opportunity can be applied to via source link without registering on Aspirova, while account features remain properly protected.

### A-14 — Dashboard's “Saved” count includes applied/interviewing/offers [P3, E2]

**Source:** [`frontend/app/account/page.tsx`](https://github.com/sohan1611/Aspirova/blob/a90c6e1918b7145d653593922e81a6d541ab5c41/frontend/app/account/page.tsx), `setBookmarkStats({ saved: bookmarks.length, inProgress: ... })`.

**Evidence:** `saved` counts every bookmark regardless of stage, while `inProgress` is a subset. A user may see “Saved 20” and “In progress 12”; this is mathematically consistent as *tracked total*, but label “Saved” may imply status=`saved` only.

**Fix:** Rename tile “Tracked opportunities” or calculate strictly stage=`saved` and separately show applied/interview/offer. Add tooltip definitions and make counts consistent with `/saved` filters.

### A-15 — Bookmark rapid taps can race [P3, E3]

**Source:** [`frontend/components/BookmarksProvider.tsx#L86-L125`](https://github.com/sohan1611/Aspirova/blob/a90c6e1918b7145d653593922e81a6d541ab5c41/frontend/components/BookmarksProvider.tsx#L86-L125), [`frontend/components/SaveButton.tsx#L20-L35`](https://github.com/sohan1611/Aspirova/blob/a90c6e1918b7145d653593922e81a6d541ab5c41/frontend/components/SaveButton.tsx#L20-L35).

**Evidence:** `toggle` uses render-captured `wasSaved`; no explicit per-slug in-flight lock. Button has `aria-disabled` for initial data loading rather than native `disabled`, and is not disabled during requests. Two quick taps may queue conflicting mutations/reverts. **Requires deliberate latency injection to establish actual impact.**

**Repro:** Throttle save/delete endpoints; double-click bookmark at 50–100ms spacing, try save then unsave and inject one 500, compare final icon with GET `/bookmarks` after reload.

**Fix:** Per-slug pending guard or serialized operations, disable button while pending, version optimistic request state, invalidate from server on ambiguous failure. Test save→unsave, unsave→save and network reorder.

### A-17 — New Google/GitHub user profile does not initialize a display name [P2, E2, conditional]

**Source:** [`backend/api/auth.py#L64-L73`](https://github.com/sohan1611/Aspirova/blob/a90c6e1918b7145d653593922e81a6d541ab5c41/backend/api/auth.py#L64-L73), [`backend/core/models.py#L370-L382`](https://github.com/sohan1611/Aspirova/blob/a90c6e1918b7145d653593922e81a6d541ab5c41/backend/core/models.py#L370-L382) and [`frontend/app/account/page.tsx`](https://github.com/sohan1611/Aspirova/blob/a90c6e1918b7145d653593922e81a6d541ab5c41/frontend/app/account/page.tsx).

**Evidence/root cause:** On first authenticated request, user creation saves only `id` and `email`, not the name available in many social provider metadata payloads. `User.display_name` is optional, so even with a Google profile name, the Aspirova profile can start blank and the header falls back to the email's local part. This is conditional on the OAuth payload actually supplying a name and the UI's intended behavior; **no live Google login was run**.

**Repro:** Register one authorized new Google test user with `user_metadata.full_name` and avatar, open Account, compare name field, header display and completion state. Repeat with GitHub missing-name metadata and email signup as controls.

**Fix:** On *initial* mirror creation, derive a safe, length-validated proposed name from trusted provider metadata (`full_name` / `name`) **only when present**, and let user review/edit it; never overwrite an explicitly edited name at subsequent logins. If avoiding automatic import by policy, present one-click “Use name from Google” during onboarding rather than silent blank profile.

**Done when:** A first-time social user does not have to reenter name already shared with the provider unless that is a clearly communicated privacy choice.

### A-16 — Session operations lack robust user feedback [P3, E2]

**Source:** [`frontend/components/account/SecuritySection.tsx#L154-L190`](https://github.com/sohan1611/Aspirova/blob/a90c6e1918b7145d653593922e81a6d541ab5c41/frontend/components/account/SecuritySection.tsx#L154-L190), [`frontend/components/AccountMenu.tsx`](https://github.com/sohan1611/Aspirova/blob/a90c6e1918b7145d653593922e81a6d541ab5c41/frontend/components/AccountMenu.tsx).

**Evidence:** Sign-out and global sign-out invoke `supabase.auth.signOut()` without awaiting/displaying returned errors. Global dialog says every session ends immediately; auth providers may invalidate refresh tokens while short-lived access tokens remain valid until expiration. **Not a claim that global logout is broken.**

**Fix:** Await operations, show toast/error state, confirm local-state cleared on success. Clarify 'other devices may take a short time to be signed out' if consistent with actual provider security semantics; test stale-token rejection/refresh lifecycle.

---

## Opportunity data, discovery and source trust

### D-01 — Graduate jobs are categorized as internships [P1, E1 + E2]

**Observed:** [Stripe — Software Engineer, New Grad](https://www.aspirova.org/opportunity/stripe-software-engineer-new-grad-3e02d435) publicly shows **“Internship”**, despite requiring a degree by summer 2027 and referring to new graduate candidates. A separate actual [Stripe Software Engineer, Intern](https://www.aspirova.org/opportunity/stripe-software-engineer-intern-ecd0c8be) demonstrates the distinction. Current homepage also contains *“Software Engineer, Agent (New Grad 2027)”* with **Internship** badge. Public crawl snapshots can lag; verify same URL live before signoff.

**Source root cause:** [`backend/pipeline/normalize.py#L12-L23`](https://github.com/sohan1611/Aspirova/blob/a90c6e1918b7145d653593922e81a6d541ab5c41/backend/pipeline/normalize.py#L12-L23): regex `_INTERNSHIP_PATTERN` explicitly includes `new grad(uate)?`, routing all matched titles to `internship`.

**Impact:** Students filtering internships get full-time roles; new grads may miss relevant jobs if filtering `job`. Alerts and paid matching inherit the same misclassification.

**Fix:** Separate **employment type** (`internship`, `full_time`, `contract`, etc.) from **career stage** (`student`, `new_graduate`, `entry_level`). Remove “new grad” as an internship synonym; consider `graduate internship` exceptions. Prefer employer structured metadata over title heuristics; add disambiguating test cases for “new grad,” “intern,” “new graduate internship,” “trainee,” “apprenticeship,” and multilingual variants. Backfill existing wrong categories; compute impact counts *before and after*, not just code correctness.

**Done when:** Stripe/Sierra and all seed cases land in appropriate job category; both job and internship queries are reindexed; daily canary checks detect a recurrence.

### D-02 — Claimed employer Apply destination is an aggregator [P1, E1]

**Observed:** [SemiAnalysis — Research Intern EU](https://www.aspirova.org/opportunity/semianalysis-research-intern-eu-a319167f) shows **“Apply on SemiAnalysis”** and **“Opens the company's own listing”**, but the actual `<a>` points to **`himalayas.app`**. The same page acknowledges “Originally posted on Himalayas.” This conflicts with repeated sitewide “every Apply link takes you back to the company” claims on homepage, footer and FAQ.

**Impact:** User trust, scam vigilance, attribution accuracy, source transparency and potentially unwanted multiple redirects. Aggregator listing may be useful, but should not be represented as a verified direct employer link.

**Fix:** Track separate `source_listing_url`, `employer_apply_url`, `resolved_redirect_domain`, `source_type`, `verification_timestamp`, and `is_employer_direct`. Render “Apply via Himalayas” when no verified company destination exists; if genuinely direct, link to company ATS URL. Only use “company's own listing” if registrable domain/canonical ATS host has been verified. Run link-resolution checks without bypassing access restrictions or scraping prohibited destinations.

**Done when:** Displayed source and destination agree on every sampled source; footer uses a truthful qualified statement, e.g. “We link to source listings, usually the employer's site.”

### D-03 — Employer aliases appear as separate companies [P2, E1; requires identity verification]

**Observed:** [Companies directory](https://www.aspirova.org/companies) lists **“Unitedmedia”** and **“United Media”** as separate entities, and **“Graphcore Early Careers”** alongside **“Graphcore.”** Those *may* be different boards or divisions; do not merge blindly. Other potential alias pairs warrant review.

**Impact:** Duplicated company-follows, fractured search/filter results, weak trust signals, counts that reflect ATS boards rather than unique employers.

**Fix:** Separate canonical company from ATS/source board. Normalize domain and legal identity, maintain alias mapping and explicit parent/brand relationship, deduplicate only after exact-domain and provenance checks. Preserve URLs and opportunity attribution. Show one company page with labeled board sources when verified.

**Done when:** Same-employer aliases are merged or explicitly explained; false merges prevented with a fixture list and audited before/after entity counts.

### D-04 — Suspicious titles/description concatenation in some feed excerpts [P2, E1 observation; validation required]

**Observed signal:** Homepage extraction has entries such as **“Smart Contract Security Audit Intern (AI Audit)Contract Audit: Participate in code reviews...”** with no separator, and truncated-looking **“Secheron S Dot A”**. Text extraction concatenates adjacent markup, so this may be an **HTML text/preview formatting problem rather than corrupted DB columns**. An earlier served snapshot included a compound title joining “IT Support Apprentice” and “Signal Processing Engineer,” which requires independent row-level confirmation before marking data as corrupt.

**Validation:** Take URLs/slugs for 20 suspicious cards, inspect **actual DOM nodes** and rendered screenshots, compare title/description/employer fields in read-only API/DB against raw source and canonical link. Check if joining occurs at HTML-to-text extraction stage only.

**Fix if proven:** Enforce max length and reasonable title patterns; isolate card title from description in HTML; quarantine multi-title crawler payloads instead of silently publishing, and add source-specific parsers/split guards with fixture tests.

**Done when:** No observed merged or unescaped titles remain in a 100-row sample, and a rendered DOM audit—not only plain-text scrape—passes.

---

## End-to-end test cases the code review cannot substitute

These **are not claimed as passed**. They are acceptance/regression cases to run against a **staging environment**, preferably Playwright with Chrome, Firefox, WebKit plus one real Android and iOS browser.

| Case | Scenario | Success condition |
|---|---|---|
| AUTH-01 | Email signup, confirmation, login/logout | One identity and profile; stable redirect; no account-existence disclosure |
| AUTH-02 | Google and GitHub OAuth new/existing account | Returns to original page; no duplicate account; error and cancel recovery |
| AUTH-03 | Password reset expired/reused/invalid link | Human-readable state, recovery link; no token visible in URL after exchange |
| AUTH-04 | Password change while other session exists | Correct reauthentication policy and token revocation behavior |
| AUTH-05 | 30 concurrent first-use authorized API calls | All succeed; one user row, no 500, no lost bookmarks |
| AUTH-06 | Sign-out local/global and other tabs | UI and API access reflect intended session invalidation |
| PROF-01 | Edit each profile field, refresh and second device | Value persists when promised; country clearly scoped local/account |
| PROF-02 | Country switch with saved college | Old incompatible college flagged; no silent contradiction |
| PROF-03 | Leave profile while unsaved changes exist | Draft retained or explicit discard dialog |
| PROF-04 | Fields/interests save, browser storage disabled | Server sync feedback accurate; no stale preference after reload |
| PROF-05 | Empty/default/partial/long Unicode names, college manual entry | Correct validation, truncation, accessible errors |
| PROF-06 | 3/3 academic fields but no skills/resume | Completeness label scoped correctly, no false 'ready' impression |
| NOTIF-01 | Every notification toggle on Free, Pro Lite, Pro | Locking vs preference accurate; refresh preserves choice |
| NOTIF-02 | Upgrade/downgrade/cancel/rejoin | Effective capabilities, plan labels, billing period and notification options agree |
| NOTIF-03 | Email opt-out / unsubscribe links / instant vs digest | No sends contrary to choice or plan; one-click unsubscribe works |
| SAVED-01 | Save/edit stage/unsave under slow network | UI equals backend after reload; no race or duplicate state |
| SAVED-02 | 25 saved searches, create 26th, delete/undo | Clear limit and errors; no accidental permanent loss |
| SAVED-03 | Two accounts with same saved-search IDs | No cross-account reads/edits; API filters by authorized user |
| RESUME-01 | Upload valid/invalid/oversize PDF and empty scan | Correct feedback; no orphan; score clearly an estimate |
| RESUME-02 | User A's resume path requested by user B | Storage RLS rejects unauthorized access; signed URL scoped and short-lived |
| RESUME-03 | Delete PDF, inspect storage and account metadata | Both cleanly removed; backup retention disclosed |
| APPLY-01 | Guest Apply, mobile tap, middle-click, browser back | Source destination accessible without forced account signup (if product change approved) |
| APPLY-02 | Signed-in Apply and “Did you apply?” reminder | Only manual confirmation marks applied; not marked just by clicking |
| LIST-01 | Sample 100 roles per source | Correct type, company, location, expiry, primary apply link and updated timestamp |
| LIST-02 | New-grad and internship category fixtures | No conflation of employment type and career stage |
| BILL-01 | Checkout success, failed payment, duplicate webhook | Correct idempotent subscription state and no duplicate charge |
| BILL-02 | Cancel at end of period, renew, expired subscription | Clear access/billing state with provider reconciliation |
| ACCESS-01 | 320px width, 200% zoom, keyboard-only, screen reader | Dialog focus, contrast, accessible name/state and visible error messages |
| PERF-01 | Mobile slow 4G account / feed / directory | Measure LCP, INP, CLS, JS errors and repeated API calls; no fake pass labels |

### Explicitly out of scope / not verified

No authorized production test account was supplied, and the available page-reading method is not a full interactive browser session. Thus **profile save, signup provider configurations, private storage RLS, tenant isolation, checkout, emails, E2E sessions, browser screenshots, responsive design and real-core-vitals were not independently verified**. Source calls/URLs can diverge from deployment. These are audit limitations, **not** findings of failure. Avoid running heavy load or security attacks on the live service.

## Fix order and owner-ready execution checklist

**Sprint 0 — privacy & correctness gate (priority):** A-01 generic signup notice; A-02 concurrent user upsert; D-01 separate new-grad job classifier + backfill; D-02 truthful Apply source; A-04 locked notification state. Ship only with staging reproduction, automated assertions, and a small live read-only sanity sample.

**Sprint 1 — account trust and data safety:** A-03 auth hydration; A-07 consistent college/country; A-08 unsaved-change guard; A-09 truthful delete request; A-10 safe saved-search deletion; A-11 network error UI; A-12 upload reconciliation; A-17 social-profile name review.

**Sprint 2 — product clarity/reliability:** A-05 accurate profile progress; A-06 synced desired geography (with consent); A-13 guest Apply decision; A-14 count labels; A-15 concurrent bookmark mutation; D-03 employer aliases; D-04 rendered-card verification; A-16 feedback on session actions.

**Definition of done for every fix:** (1) reproduce/falsify on a pinned build, (2) quantify affected rows/users where applicable, (3) add a regression test, (4) run backend tests + frontend checks + browser E2E, (5) inspect actual rendered DOM or production read-only sample, (6) log result with screenshots/trace and exact commit, (7) deploy and verify behavior rather than equating “build green” with “bug fixed.”

## Source inventory

- Public homepage: https://www.aspirova.org/
- Public listing: https://www.aspirova.org/opportunity/stripe-software-engineer-new-grad-3e02d435
- Contrasting intern listing: https://www.aspirova.org/opportunity/stripe-software-engineer-intern-ecd0c8be
- Misleading apply-host example: https://www.aspirova.org/opportunity/semianalysis-research-intern-eu-a319167f
- Company directory: https://www.aspirova.org/companies
- Privacy policy (updated 3 Nov 2026): https://www.aspirova.org/privacy
- FAQ: https://www.aspirova.org/faq
- Code snapshot: https://github.com/sohan1611/Aspirova/tree/a90c6e1918b7145d653593922e81a6d541ab5c41

**Companion file:** `Aspirova_Expected_Features_and_Competitor_Gap.md` contains competitor-backed feature priorities and acceptance criteria. This file documents bugs, trust issues, UX defects and necessary fixes, not an inflated list of features that Aspirova already has.
