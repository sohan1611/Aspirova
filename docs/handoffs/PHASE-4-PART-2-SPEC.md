# PHASE 4 · PART 2 SPEC — Referral / invite loop

*From: Chief Architect (Opus) · To: the engineer (Codex/Sonnet). Detailed spec for PHASE-4-HANDOFF §2. Implements Doc 06 lever #1 (viral loop). Key-free, payment-free: the reward is a **complimentary subscription row**, never a Razorpay charge.*

---

## 0. Why this is safe to build now
- No AI keys, no Razorpay. The reward flows through the **existing** `can()` seam as a plain `subscriptions` row.
- `users.referred_by` (UUID FK → users.id) **already exists** (core/models.py, Phase-1 schema). Only one additive column is new.
- Split into **2a (backend)** and **2b (frontend)**, same cadence as Phase-3 Part 3. This doc specs both; dispatch 2a first.

## 1. The two architect rulings baked into this spec (ratify or amend)

**Ruling A — the reward is a bounded 30-day `pro_lite_monthly` comp subscription, not full Pro.**
`pro_lite` unlocks the valuable non-AI Pro features (instant_alerts, weekly_report, hidden_opps, unlimited_bookmarks, dream_companies_limit=5) but leaves `copilot`/`resume_match`/`prediction` **false**. Those three are the *metered AI* features that cost real money once keys go live (Doc 06). Granting full Pro per referral would be a direct, stackable AI-cost/abuse vector at go-live. `pro_lite` gives the referrer a real, feel-able reward at **zero marginal cost**. Term: **30 days** per successful referral.

**Ruling B — gating gains comp-path expiry, and *only* the comp path (Binding-area amendment, Doc 08 §1 single gating seam).**
`core/gating.py::get_features` today matches `status IN ('active','trialing')` and ignores `current_period_end`. That's correct for Razorpay subs (the webhook keeps status fresh) but means a "bounded" comp sub would never actually expire. Fix, surgically:

```python
# in get_features, the subscription subquery WHERE clause becomes:
models.Subscription.user_id == user.id,
models.Subscription.status.in_(("active", "trialing")),
or_(
    models.Subscription.razorpay_sub_id.isnot(None),          # Razorpay subs: unchanged behavior
    models.Subscription.current_period_end.is_(None),          # comp sub with no term = permanent
    models.Subscription.current_period_end > func.now(),       # comp sub still within its term
),
```

This tightens **only** comp rows (`razorpay_sub_id IS NULL`); every Razorpay sub keeps its exact prior behavior (the first OR branch short-circuits it), so no paying user can be affected. Record this as an amendment row in `docs/README.md` decision log. Add a `test_gating.py` case proving: (i) a comp sub with `current_period_end` in the past does **not** grant features, (ii) one in the future does, (iii) a Razorpay sub with a past `current_period_end` **still** grants (unchanged).

## 2. Part 2a — backend (do first)

### 2a.1 Schema (one additive migration; down-reverts cleanly)
- `users.invite_code TEXT UNIQUE NULL` — short, url-safe, human-ish (e.g. 8 chars from an unambiguous base32 alphabet, no 0/O/1/I). Generated lazily on first read (§2a.3), never required at insert. Nullable + unique; add the unique index in the same migration.
- Nothing else. `referred_by` already exists. The reward uses the existing `subscriptions`/`plans` tables as-is.
- Mirror the column on `core/models.User`. Migration id + down_revision must chain off current head (`e8c4f1a6b2d9`); confirm with `alembic heads` before writing.

### 2a.2 Referral service (`core/referral.py` — new)
Pure functions, unit-testable, no HTTP:
- `get_or_create_invite_code(db, user) -> str` — return the user's code; if null, generate a unique one (retry on the tiny collision chance), persist, commit. Deterministic-length, collision-safe.
- `resolve_code(db, code) -> User | None` — case-insensitive lookup by invite_code.
- `record_referral(db, new_user, code) -> ReferralResult` — the core transaction, idempotent and abuse-guarded:
  - Resolve `code` → `referrer`. If it doesn't resolve, or `referrer.id == new_user.id` (self-referral), return a no-op result (never raise).
  - If `new_user.referred_by` is **already set**, return a no-op (set-once; prevents re-claiming and double-rewards).
  - Otherwise set `new_user.referred_by = referrer.id` **and** grant the referrer the reward (§2a.4) in the **same** commit, so a referral and its reward are atomic.
- `grant_comp_pro(db, referrer, days=30, plan_key="pro_lite_monthly")` — insert a `Subscription(user_id=referrer.id, plan_id=<pro_lite_monthly.id>, status="active", razorpay_sub_id=None, current_period_end=now+days)`. Look the plan up by key; if the plan row is missing raise a clear RuntimeError (seed must run first), same posture as gating's free-plan guard. **Never** set `razorpay_sub_id`.

### 2a.3 Endpoints (`api/referral.py` — new, router mounted in main.py)
- `GET /referral/me` (auth) → `{ invite_code, invite_url, referral_count, reward_active_until }`.
  - `invite_url` = `f"{settings.public_web_url}/?ref={code}"` (see §4 config note); lazily creates the code.
  - `referral_count` = count of users where `referred_by == user.id`.
  - `reward_active_until` = max `current_period_end` among the caller's active comp subs, or null.
- `POST /referral/claim` (auth) body `{ code: str }` → calls `record_referral(db, current_user, code)`; returns `{ referred: bool, reason: str }` (e.g. `already_referred`, `self_referral`, `unknown_code`, `ok`). Always 200 for the valid-shape cases (a failed/duplicate claim is not an error the client should crash on); 422 only on a malformed body.
- Both routes must be cheap; `/referral/me` should be safe to poll from the invite page. No new caching required, but do not add N+1s.

### 2a.4 Tests (`tests/test_referral.py`)
- Code generation is unique + stable (second call returns the same code).
- A first-time claim with a valid code sets `referred_by` and creates exactly **one** `pro_lite_monthly` comp sub (status active, `razorpay_sub_id` NULL, `current_period_end ≈ now+30d`); `can(referrer, "instant_alerts")` is now True and `can(referrer, "copilot")` stays **False** (proves the cost-safe reward).
- Idempotency: a second claim (same or different code) is a no-op — still exactly one comp sub, `referred_by` unchanged.
- Self-referral and unknown-code are no-ops (no sub created, no exception).
- Plus the three gating-expiry cases from Ruling B (can live in test_gating.py).
- All under the rollback fixture; assert **zero** leaked rows past the test (the service commits, like resume_match — prove savepoint containment, per prior parts).

## 3. Part 2b — frontend (after 2a lands)
- **Capture** `?ref=CODE` on any page load (a small client effect / middleware): stash the code in `localStorage` under a single key; do it once, don't overwrite an existing stash.
- **Claim** after auth: when a signed-in session first appears and a stashed code exists, `POST /referral/claim` once, then clear the stash regardless of outcome (so it never re-fires). Silent — no user-facing error on a no-op reason.
- **/referral page** (auth-gated, on the 2.5 design system): shows the user's invite link (from `GET /referral/me`) with a copy button, the referral count, and reward status ("Pro Lite active until …" when `reward_active_until` is set). Signed-out → the same upsell/sign-in pattern the /resume page uses.
- **Header/nav**: an "Invite" link (mirror how the "Matches" link was added in Part 3.3/3-frontend).
- **Share affordance (optional, keep if clean):** on the opportunity detail, a "Share" / copy-link control that appends `?ref=<the user's code>` when signed in (plain link when signed out). The rich OG preview from Part 1c already makes these shares look good — this closes the loop. Defer if it complicates the build.
- Guardrails: no new SSR regressions; the /referral page can be `○` client-static (fetch client-side, like /resume — do **not** fetch at build time, avoid the /pricing prerender trap).

## 4. Config note
`invite_url` needs the public web origin. If `settings` already exposes the frontend base URL (check config.py — the OG/sitemap work uses `https://aspirova.vercel.app` via `metadataBase`), reuse it; otherwise the frontend can construct the URL itself from `window.location.origin` and the backend can return just `invite_code` (+ let 2b build the URL). Prefer the latter if there's no existing server-side web-origin setting — keeps the backend from hardcoding a frontend URL.

## 5. Landing checklist (the founder-authorization checkpoints)
1. **Prod migration** — the additive `users.invite_code` column must be applied to production Supabase before master CI (which runs backend tests against prod DATABASE_URL) can go green. **Founder-authorized, same as the Phase-3 migrations.** Additive + nullable → zero-risk, instant.
2. Build + verify on a throwaway `pgvector/pgvector:pg17` container first (migration up/down, all tests, zero row-leak) — no prod write during build.
3. `sohan1611`-only commits; ruff + black + pytest (backend), eslint + tsc + build (frontend). Merge → CI green, per cadence.

## 6. Explicitly out of scope (later parts / the gate)
- Referral **leaderboard** + campus ambassadors = Part 3 (needs real Pro-to-earn, post-payments).
- Fraud/Sybil hardening beyond self-referral + set-once (e.g. per-referrer reward caps, velocity limits, verified-email requirement) — instrument first, harden when `k` and abuse are observable. Note as a follow-up, don't gold-plate the MVP.
- Any Razorpay / real-billing coupling — stays out until the founder wires live billing.
