# Account Area V2 — Refinement Handoff

*Architect: Claude Opus. Engineer: Codex. Status: HANDED OFF (work order 2, after the college picker).*

## 1. Goal
The account area built from `ACCOUNT-AREA-HANDOFF.md` is structurally right: left sidebar (mobile Select), per-section cards with serif titles, per-section saves, a visually distinct danger zone, deep links via `?section=`. V2 is **not a reskin** — the almanac identity (cream, serif, heritage badge, `forcedTheme="light"`) stays untouched. V2 is an **information-hierarchy and trust pass**: every glanceable becomes meaningful and actionable, save states become honest, inputs get constrained, and billing reads in plain language.

## 2. Research grounding (why these changes)
Surveyed 2026-07-23: Shopify Polaris *App settings layout* pattern, uxpatterns.dev *Account Settings* anatomy, SaaSUI *SaaS Settings Page UX Patterns* (June 2026). The applicable findings:
- **Billing is the highest-stakes section** — current plan, next charge, and amount must be stated in plain language without hunting; hiding them erodes trust.
- **Save states must be honest** — disable Save when nothing changed; users must be able to tell whether a change took.
- **Glanceables must earn their place** — a settings hub is organization, not delight; every tile should answer a question or go somewhere.
- **Danger/destructive actions separated with proportional friction** — already done here; keep.
- What we already match (sidebar nav, grouped cards, per-section save, confirm dialogs) needs no change.

## 3. Changes by surface (frontend only)

### 3.1 Summary card (`app/account/page.tsx`)
- **Tile 3 (“Member since”) → Plan tile.** Member-since already lives in the Profile card footer; the tile slot is wasted on it. New tile:
  - Paid: value `{Plan name}`, caption `Renews {formatDate(current_period_end)}` — or `Cancels {date}` when `cancel_at_period_end`. Links to `/account?section=subscription`.
  - Free: value `Free plan`, caption `Upgrade →`. Links to `/pricing`.
- **Tile 2 (“In progress”)** becomes a link to `/saved` (same treatment as the Saved tile — no dead tiles).
- **Completeness strip.** When profile completeness < 3/3, render one compact row under the tiles: thin progress bar + `Profile {n} of 3 · Finish your profile` linking to `?section=profile`. Extract the completeness computation (currently inline in `ProfileSection`) into a small shared helper (e.g. `lib/profileCompleteness.ts`) so page and section use one source of truth. When 3/3, render nothing.

### 3.2 Profile (`components/account/ProfileSection.tsx`)
- **Do not touch the college picker** (landed in work order 1). Build on top of it.
- **Graduation year → constrained Select** (house `Select` primitive): years `currentYear − 8 … currentYear + 8`, newest-relevant ordering (ascending). A legacy stored value outside the range still displays as the selected value and is never clobbered by an untouched save. Clearable (an explicit “—” / none item → null).
- **Dirty-state Save**: compute the same normalized diff the submit already computes; `Save changes` is disabled until something actually differs. Remove the “already up to date” toast path (it becomes unreachable).

### 3.3 Subscription (`components/account/SubscriptionSection.tsx`)
- **Plain-language billing sentence** at the top of the plan card, one line: paid → `₹{price}/{month|year} · renews {date}` (or `Access until {date}` when cancelling); free → `You’re on the free plan.` Use `price_paise` + `billing` from `plan`; no new API calls.
- **Reassurance line** `Billing handled securely by Razorpay.` as muted small text if not already present.
- Cancel flow unchanged — canon: cancel-then-resubscribe is the only plan-change path (Decision log; do not add plan-switch UI).

### 3.4 Notifications (`components/account/NotificationsSection.tsx`)
- Same **dirty-state Save** rule if the section has an explicit save; if toggles save instantly, instead ensure each toggle gives per-change feedback (existing toast pattern). Whichever it is, make the save state honest — no silent writes, no always-armed Save.

### 3.5 Security (`components/account/SecuritySection.tsx`)
- **“Sign out of all devices.”** Next to the existing sign-out row: outline button, confirm dialog (“This ends your session on every device, including this one.”), then `supabase.auth.signOut({ scope: "global" })`.
- **Password minimum → 8 chars** (frontend `minLength`, validation message, helper text). Server accepts ≥6; the frontend being stricter is intentional.
- Danger zone unchanged.

### 3.6 Sidebar — unchanged. Mobile Select fallback already exists; do **not** add an Appearance section (theme is deliberately forced light).

## 4. Hard scope
- **Frontend only.** No backend, no migrations, no new dependencies, no new API calls.
- Do not regress the college picker (work order 1) or any `?section=` deep link.
- House idiom only: existing ui primitives, `cn()`, lucide, aria patterns already in these files.
- Merge gate: `pnpm lint` + `tsc --noEmit` green (architect runs them).

## 5. Deferred backlog (requires backend / founder config — explicitly NOT in this work order)
- Active-sessions list; 2FA (Supabase MFA); email change with re-verification; invoice/receipt history (Razorpay fetch); self-serve account deletion.

## 6. Acceptance criteria
1. Summary card: plan tile shows correct state for free / active / cancelling users and deep-links correctly; In-progress tile links to `/saved`; completeness strip appears only when incomplete and links to the profile section.
2. Profile: graduation year is a Select with the specified range; legacy out-of-range values display and survive an untouched save; Save disabled until dirty.
3. Subscription: one-line plain-language billing sentence correct for free / active / cancelling; Razorpay reassurance present.
4. Security: global sign-out works behind a confirm dialog; password form enforces 8+.
5. No visual identity drift: cream/serif/heritage styling and spacing consistent with the rest of the account area.
6. Lint + types green.
