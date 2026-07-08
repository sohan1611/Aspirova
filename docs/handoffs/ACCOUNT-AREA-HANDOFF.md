# Account Area — Architecture Handoff (Phase 4 · Part 3)

*Architect: Claude Opus. Engineer: Codex. Status: HANDED OFF.*

## 1. Goal
A premium, best-in-class **account & settings area** — Profile, Subscription & Billing, Notifications, Appearance, Security — modeled on the settings surfaces of Vercel / Linear / Stripe / GitHub. Gives a paying user a place to *see* their plan, manage it, and control their experience. Closes the "I paid but nothing visibly changed" gap.

## 2. Grounding — what already exists (do not rebuild)
- **Identity**: Supabase Auth. Client `session.user` carries `email`, `user_metadata` (`name`, `avatar_url` from OAuth), `identities` / `app_metadata.providers` (which social providers are linked).
- **Profile columns on `users`** (already present, unused by any UI): `display_name`, `college`, `graduation_year`, `invite_code`, `created_at`, `referred_by`.
- **Plan/subscription**: `subscriptions` (`status`, `current_period_end`, `razorpay_sub_id`, `plan_id`) + `plans` (`key`, `features` jsonb, `price_paise`, `billing`). Gating flows through `core/gating.py::can()` / `get_features()` — the single seam.
- **Auth dependency**: `api/auth.py::get_current_user` verifies the Supabase token and JIT-creates the local `users` row (id + email).
- **Payments**: `api/payments.py` has checkout + webhook only. **No** "get my subscription", "cancel", or "account/me" endpoint exists yet.
- **Frontend authed-call pattern**: `fetch(url, { headers: { Authorization: \`Bearer ${accessToken}\` } })`; `useSession()` provides `session.access_token`. Theme via `next-themes`.

## 3. Information architecture (route `/account`)
A settings shell: **left sidebar nav on desktop, a select/tabs on mobile**. Deep-link each section via `?section=`. One `GET /account/me` hydrates all sections.

| Section | Contents |
|---|---|
| **Profile** | Avatar (OAuth `avatar_url`, else bronze initials) · Display name (edit) · Email (read-only) · College (edit) · Graduation year (edit) · Member since · Referral link (from `invite_code`, → /referral) |
| **Subscription & Billing** | Current-plan card: name · status badge (Active / Free / Cancels on…) · renews/expires (`current_period_end`) · included features. **Free** → "Upgrade" CTAs (→ /pricing). **Paid** → "Change plan" (→ /pricing) + "Cancel subscription" (confirm dialog). "Billing handled securely by Razorpay." |
| **Notifications** | Toggles: Weekly career report · Instant alerts (dream companies) · Daily digest — backed by `users.notification_prefs`. Plan-gated ones shown locked for free. |
| **Appearance** | Theme: Light / Dark / System (next-themes). |
| **Security** | Change password (email-provider users, `supabase.auth.updateUser`) · Connected accounts (from `identities`) · Sign out · **Danger zone**: Delete account (deferred — see §6). |

Header: replace the inline "email + Sign out" with an **avatar dropdown** (`dropdown-menu` primitive): email, → Account, → Bookmarks, Sign out.

## 4. Backend API (new — `api/account.py` + additions)
1. **`GET /account/me`** → `AccountMe`:
   `{ email, display_name, college, graduation_year, created_at, invite_code, notification_prefs, plan: { key, price_paise, billing, features, status, current_period_end } }`.
   `plan` = the user's active sub's plan + status via `get_features`; falls back to the **free** plan with `status:"free"`, `current_period_end:null`.
2. **`PATCH /account/me`** → partial update: `display_name` (≤80, trimmed→null if empty), `college` (≤120), `graduation_year` (2000–2100 or null), `notification_prefs` (dict[str,bool], merged). Returns the updated `AccountMe`.
3. **`POST /subscription/cancel`** → cancel the user's active Razorpay subscription with **`cancel_at_cycle_end=1`** (keep access until `current_period_end`). `404` if no active sub, `503` if Razorpay unconfigured. Do **not** hard-flip local status — the webhook (`subscription.cancelled`) is the source of truth; the UI reads "Cancels on {current_period_end}".
4. **Migration**: add `users.notification_prefs jsonb NULL` (null ⇒ all-on default).
5. **Workers respect prefs**: the weekly-report + daily-digest senders skip a user whose `notification_prefs[type]` is explicitly `false` (read the existing worker/sender; add a guard — do not resend to opted-out users).
6. **Tests** (pgvector container; no real email, no real Razorpay charge — monkeypatch the razorpay client): `GET/PATCH /account/me` happy + validation paths; cancel with a stubbed active sub; a free user sees `plan.status=="free"`.

## 5. Frontend (new)
- `app/account/page.tsx` (client; if no `session`, redirect home + open auth). Sidebar + section panels; hydrate from `GET /account/me`.
- `lib/api.ts`: `getAccount`, `updateAccount`, `cancelSubscription` (all Bearer-authed).
- New components: `AccountSidebar`, and per-section panels; reuse `Card`, `Select`, `Dialog`, `Button`, `Badge`, `Label`, `Input`.
- Header avatar menu via `dropdown-menu`.
- **Design**: the existing beige-cream + **bronze** token system, Fraunces headings, `ease-premium` motion. Fully responsive; AA contrast; keyboard-navigable.

## 6. Phasing & deferred
- **WO-1 (backend)**: §4 items 1–6 → verify on container → **prod migration (founder-authorized)** → deploy.
- **WO-2 (frontend)**: §5 → verify in preview (light+dark) → deploy.
- **Deferred (v2, flagged not built)**: account **deletion** endpoint (destructive: cancels billing + removes Supabase user — needs a typed confirm + careful cleanup); **payment history** (Razorpay invoices API); **avatar upload** (needs object storage). The Security "Delete account" shows a "contact support" affordance until then.

## 7. Decision log delta (for docs/README.md)
- **Binding**: subscription status remains **webhook-driven only**; `POST /subscription/cancel` requests a cancel-at-cycle-end on Razorpay but never locally sets `canceled` — the webhook does. Prevents the client from lying about billing state.
