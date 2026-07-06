# PHASE 2.5 HANDOFF — Premium UI & Experience

*From: Chief Architect (Opus) · To: Lead Engineer (Sonnet) · Status: ISSUED. This is an inserted phase between Phase 2 (monetization infra, engineering-complete) and Phase 3 (AI). It exists because the product is functionally complete but visually a stock Next.js starter — and the roadmap's own law forbids monetizing or enhancing a weak-feeling product.*

---

## 0. Why this phase exists (the reorder)

Phase 2 shipped payments/plans/gating **infrastructure**, notifications, backups, rate-limiting — all verified live except Razorpay, which the founder is deferring by decision. The canonical roadmap (Doc 07) had Phase 3 = AI next.

**Architect ruling — roadmap reordered to: Premium UI (this phase) → AI (Phase 3) → Razorpay wiring (completes Phase 2's payment gate).** Rationale, straight from Doc 07's sequencing philosophy:

- *"Monetize only after the free product is genuinely good — a paywall on a weak product just advertises the weakness."* The current UI is not yet good enough to paywall.
- Deferring Razorpay until **after** AI means the eventual paywall gates **real Pro value** (AI features) on top of a **premium-feeling** product — the correct order, not a compromise.
- AI features (Phase 3) will themselves need UI surfaces (Resume Match, Copilot, Weekly Report). Building the design system **now** means Phase 3 ships those on a mature component layer instead of bolting more stock-template screens together.

This does **not** contradict any Binding row; it inserts a phase and re-sequences the payment gate's *completion*. Recorded in the Decision log (Doc README).

---

## 1. Scope discipline (read before touching anything)

**IN scope:** design-system foundation, component primitives, and a full visual/UX redesign of the **existing** surfaces — feed, opportunity detail, auth, plus a new pricing/"coming soon" page and an app shell (nav/footer/brand).

**OUT of scope (do not pull forward):**
- **No AI, no pgvector, no embeddings, no Copilot UI.** That is Phase 3. If a screen "wants" AI, stub it or leave it out.
- **No functional Razorpay checkout.** Payments remain fail-closed (Doc handoffs/PHASE-2 §11 / `core/config.py` blank-key behavior). The pricing page is an **honest waitlist**, never a checkout that 500s. See §3.7.
- **No new backend endpoints beyond what a waitlist capture needs** (and even that can be a simple email capture — see §3.7; prefer reusing Resend/existing tables over new schema unless trivially justified).
- **No regression of the SSR/SEO growth surface.** The feed and `/opportunity/{slug}` pages are Server Components today and are the organic-growth engine (Doc 01). They stay server-rendered. Interactivity is added via **leaf** client components only.

---

## 2. The design direction (founder's call — honor it, but execute it *premium*)

**Chosen personality: Professional / Trust (LinkedIn-adjacent).** Blue-led, credible, conservative, information-clear.

**Chosen theme model: system-adaptive default + a visible manual toggle** (light / dark / system).

**Architect's binding caveat — avoid the generic-corporate trap.** "Professional/trust" done lazily reads as a free template. The credibility must come *with* premium execution. Non-negotiable quality bars:

- **Restraint, not decoration.** One trustworthy blue as the primary accent; a disciplined neutral scale; semantic colors (success/warning/danger) used sparingly. No gradients-for-the-sake-of-it, no drop-shadow soup.
- **Typographic rhythm.** A real type scale (not `text-2xl`/`text-sm` ad hoc). Consistent line-heights, measured line-length on the detail page (~65–75ch), clear hierarchy. Geist Sans is acceptable and already wired; a refined scale matters more than a new font.
- **Spacing system.** An 4px-based spacing scale applied consistently; generous but not wasteful. The current cramped header/inline-auth is the anti-pattern.
- **Micro-interactions.** Hover/focus/active states on every interactive element; subtle card elevation on hover; skeletons on load; smooth (150–250ms) transitions. This is what separates "premium" from "corporate."
- **Trust signals.** Company favicons/logos on cards + detail, clear source attribution ("via Greenhouse/Lever"), honest deadline confidence labels (already in the data — surface them well), crisp empty/error states.

---

## 3. The build — 8 parts (each: implement → self-verify → commit on a branch; ruff/black/pytest not applicable, but `eslint` + `tsc --noEmit` + a real visual check per part are the green bar)

### 3.1 — Design-token foundation + theme system
Codify the whole visual language **before** any screen work. Tailwind v4 `@theme` in `app/globals.css` is the single source of truth: color scales (brand blue, neutrals, semantic), type scale, spacing, radii, shadows, motion durations/easings. Replace the current 6-line placeholder `:root`. Implement the light/dark/system theme with a class strategy (recommend `next-themes` — tiny, SSR-safe, no flash) and a toggle primitive. **Acceptance:** every subsequent part consumes tokens; grep shows no ad-hoc hex or raw `gray-500`-style colors creeping back in.

### 3.2 — Component primitives
A small, **owned** primitive layer. Hand-roll the simple ones (Button w/ variants, Badge/Chip, Card, Input, Select, Skeleton, Spinner). Use **shadcn/ui-style copy-in on Radix** for a11y-critical interactive primitives you'll need now or in Phase 3 (Dropdown/Select-menu, Dialog/Sheet, Toast). Rationale: accessibility for free, zero runtime lock-in, founder owns the source. **Acceptance:** primitives are keyboard-accessible, focus-visible, theme-aware; documented on a simple internal `/style` or story page (can be dev-only).

### 3.3 — App shell (nav, footer, brand identity)
A real global header (wordmark/logo + tagline, nav, theme toggle, auth entry) and footer (links, "how Aspirova sources", legal/attribution). Establish the brand mark (a clean wordmark is enough — no need for a costly logo). Move auth **out** of the header cram (see 3.6). Polish `app/layout.tsx` metadata/OG for share-ability. **Acceptance:** consistent shell on every route; responsive; the header is not where a login form lives anymore.

### 3.4 — Feed redesign (`app/page.tsx` + `OpportunityCard` + `SearchFilters`)
The flagship surface. Premium search bar, filters as **segmented controls / pills** (not raw `<select>`), a redesigned `OpportunityCard` (company favicon, clear title hierarchy, metadata chips, tasteful deadline treatment, hover elevation), **loading skeletons**, and a designed **empty state**. Pagination becomes real buttons, not underlined text. **Keep the page a Server Component**; `SearchFilters` stays the client leaf. **Acceptance:** feed looks like a product; Lighthouse perf ≥ prior, CLS ~0, no `"use client"` added to the page shell.

### 3.5 — Opportunity detail redesign (`app/opportunity/[slug]/page.tsx`)
Strong hierarchy: title, company (with favicon), metadata chips (location/remote/category/source), **sticky or prominent "Apply at source ↗" CTA**, refined bookmark control, well-set description (measured line-length, readable typography for the `whitespace-pre-wrap` body). Keep the outbound-link-not-mirror rule (Doc 01 §7 R1). **Acceptance:** the page reads like a premium listing; still SSR; `generateMetadata` preserved/enhanced.

### 3.6 — Auth experience (`AuthWidget` → proper surface)
Replace the cramped inline header form with a **Dialog/Sheet** (or a dedicated `/login` route) using the 3.2 primitives: clean sign-in/sign-up toggle, proper labels, inline validation, loading + error + "check your email" success states, password visibility toggle. Same Supabase client logic — this is a presentation refactor. **Acceptance:** auth feels trustworthy; keyboard + screen-reader accessible; no logic regressions.

### 3.7 — Pricing / "Coming soon" page (honest Razorpay dummy)
A real, premium pricing page presenting the canonical plans — **Pro Lite ₹39/mo · ₹399/yr, Pro ₹49/mo · ₹499/yr, annual as the highlighted default showing the ~15% saving** (Doc 06 §1) — but with a **"Join the waitlist"** CTA, **not** a checkout. Waitlist capture: prefer the simplest honest mechanism (e.g. a Resend notification to the founder and/or a lightweight `waitlist_signups` capture) — keep it minimal; do not build Razorpay. Make the plan/feature matrix data-driven off the seeded `plans.features` where practical so it's ready to go live later. **Acceptance:** nothing on this page can hit a failing payment endpoint; the value prop is clear and premium; flipping to real checkout later is a small, localized change.

### 3.8 — Polish pass (motion, a11y, perf, responsive, cross-browser)
Consistent motion with `prefers-reduced-motion` honored; full keyboard-nav + focus-order audit; WCAG **AA** contrast in **both** themes; Lighthouse (perf/a11y/best-practices/SEO) on feed + detail; responsive QA at mobile/tablet/desktop; the theme toggle has no flash-of-wrong-theme. **Acceptance:** AA in both themes, Lighthouse a11y ≥ 95, no CLS/flash, mobile-first holds.

---

## 4. Cross-cutting guardrails (apply in every part)

- **SSR/SEO is sacred.** Feed + detail stay Server Components. Client components are interactive leaves only. This is the growth surface (Doc 01) — a redesign that tanks SEO is a failed redesign.
- **Payments stay fail-closed and honest.** No functional checkout anywhere; no button that hits a payment route. (§3.7.)
- **Tokens, not hardcodes.** After 3.1, any raw color/spacing value in a component is a defect.
- **Accessibility is part of "premium,"** not a follow-up. AA contrast, focus-visible, keyboard nav, reduced-motion — every part.
- **No backend scope creep.** This is a frontend phase. The only permissible backend touch is a minimal waitlist capture (§3.7), and even that should reuse existing seams (Resend) over new schema where possible. Anything more → escalate to the architect.
- **Commit cadence unchanged:** branch per part, `eslint` + `tsc --noEmit` green, visual check, meaningful commit as `sohan1611` (no co-author trailer), then the next part. Phase Report at the end.

---

## 5. Gate to Phase 3 (AI)

Advance only when: the design system + primitives exist and are consumed everywhere (no stock-starter styling left); feed, detail, auth, shell, and pricing are redesigned to the professional-premium bar in **both** themes; SSR/SEO intact (Lighthouse SEO not regressed); AA accessibility met; and the pricing page is a working honest waitlist with **zero** functional-checkout risk. At that point the product *looks* worth paying for — and Phase 3 (AI) can add the Pro value that the eventual (deferred) Razorpay paywall will gate.

---

## HANDOFF TO ENGINEERING

1. **Build the system before the screens.** 3.1 → 3.2 first; do not start feed/detail reskinning until tokens + primitives exist, or you'll hardcode your way into an inconsistent result.
2. **Honor the founder's direction (Professional/Trust) but hit the premium bars in §2** — the whole risk of this direction is looking generic. Restraint + typographic rhythm + micro-interactions are how you avoid it.
3. **Do not touch AI or real payments.** Wrong phase. Pricing is a waitlist. If a task tempts you toward either, stop and flag it.
4. **Protect the SSR growth surface** — Server Components stay server-rendered; measure Lighthouse before/after.
5. **End with a Phase 2.5 Report** (like PHASE-2-REPORT.md): what shipped, before/after evidence, Lighthouse + a11y numbers in both themes, and any deviations flagged for the architect.
