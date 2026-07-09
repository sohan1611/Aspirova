# Premium UI v2 — Design Architecture ("The Almanac")

*Architect: Claude Opus. Engineer: Codex. Goal: make Aspirova read as a crafted, trusted institution — not a single-prompt SaaS template.*

## 0. The problem with "generic AI" design (what we're fixing)
Single-prompt sites cluster on the same tells: one flat accent, uniform `shadow-md` on `rounded-lg` cards, a single type size doing every job, even spacing with no rhythm, lucide icons everywhere, centered everything, and no point of view. We beat it with a **distinctive POV + a real system + signature moments + obsessive detail.**

## 1. The POV — "The Almanac of Opportunity"
Aspirova's logo is an **engraved figure + a year** in sage & plum — a heritage almanac / field guide. Lean all the way in: Aspirova is the *trusted almanac that indexes every opportunity from the source*. Editorial, curatorial, warm, precise. This is the story and the trust signal, and it is **ownable** (no other job site looks like a letterpress almanac).

## 2. Foundations (globals.css — the cascade layer)

### 2.1 Type — a real modular scale (the single biggest premium lever)
- **Display: Fraunces** (keep) — heritage serif, optical sizing. Use for h1/h2, prices, the wordmark, editorial pull-quotes. Weights 500–600, tracking `-0.02em`, `text-wrap: balance`.
- **Body/UI: Geist Sans** (keep) — clean grotesque, the workhorse.
- **Mono: Geist Mono** — data, codes, timestamps.
- Define a **fixed scale** as CSS custom properties (≈1.2 ratio) and use it everywhere — nothing off-scale:
  `--text-2xs:11px / --xs:12.5 / --sm:14 / --base:15.5 / --md:17 / --lg:20 / --xl:25 / --2xl:31 / --3xl:39 / --4xl:49 / --5xl:61`, each with a paired line-height + tracking.
- **Eyebrow/label utility** `.eyebrow`: 11px, `text-transform:uppercase`, `letter-spacing:0.16em`, muted, 600 — the editorial hallmark, used above section titles + on field labels.
- `font-variant-numeric: tabular-nums` on every number (deadlines, counts, prices, pages).

### 2.2 Color — refine the warm palette into a nuanced scale
Keep beige-cream + bronze; add depth + a heritage secondary. Bronze is used **sparingly** (primary actions, links, key marks only) — restraint reads premium.
- **Light**: paper `#faf7f0`, raised card `#fffdf8`, parchment/muted `#f1ebdd`, hairline border `#e6ddcb`, warm ink `#231c15`, muted ink `#6b5f4e`, **bronze** primary `#8a5e2f`, deep **plum** heritage-accent `#5e2b47` (logo ink — for the wordmark mark, "Most popular", selective badges only).
- **Dark**: warm charcoal `#1a1712`, raised `#241f18`, ink `#ece4d5`, muted `#a99a84`, bronze `#c99f63`, plum-rose `#cf92b4`.
- **Grain**: a very-low-opacity tiled noise/paper texture on `body` (≈2–3% opacity, `background-blend`) for printed-almanac materiality. This one detail alone kills the "flat AI" read. Ship as an inline SVG/data-URI, respect dark mode, disable under `prefers-reduced-motion`? no — it's static, keep it.

### 2.3 Depth — a custom layered shadow system (not `shadow-md`)
Define `--shadow-sm/md/lg` as **2–3 stacked, warm-tinted, low-alpha** shadows (ambient + key), e.g. `0 1px 2px rgba(35,28,21,.04), 0 8px 24px -12px rgba(35,28,21,.12)`. Cards get a hairline top highlight (`inset 0 1px 0 rgba(255,255,255,.5)` light) for a letterpress lift. Hover raises one step + shifts the border toward bronze, on `--ease-premium`.

### 2.4 Spacing, motion, details
- **8pt grid**; generous section rhythm. Card padding 20–24px; comfortable form spacing.
- **Motion**: `--ease-premium` on all hovers/elevation; a subtle staggered fade-rise on first content paint (respect `prefers-reduced-motion`).
- Bronze-tinted **::selection**; slim custom **scrollbar**; offset **link underlines**; refined `:focus-visible` (bronze ring, 2px, offset).

## 3. Components (refine each — same system, obsessive detail)
- **Header**: hairline bottom rule + subtle backdrop blur; wordmark mark (the logo) + Fraunces "Aspirova"; nav links with an animated underline-draw on hover; avatar menu polish.
- **Opportunity card** (the hero of the app): favicon in a bordered "stamp"; title Fraunces-adjacent weight/serifless but confident; company · location as a muted meta line; **category/remote/hidden** as small letter-spaced pills; deadline as a subtle amber chip with the clock; equal-height; hover = lift + bronze hairline + title→bronze. Optional hairline index rule for an editorial feel.
- **Feed toolbar**: larger bordered search with leading icon; the Any/Remote/On-site + All/Internships/Jobs as one refined segmented control; columns/per-page as quiet selects, right-aligned, labeled with `.eyebrow`.
- **Primitives**: Button (bronze primary w/ subtle depth, outline hairline, ghost), Badge/pill (small, tracked), Input/Select/Textarea (hairline, comfortable, bronze focus), Card, Dialog, Dropdown — all on the new tokens.

## 4. Signature "story + trust" moments (what makes it un-generic)
- **Signed-out feed hero** (new visitors): an editorial band — `.eyebrow` "EST. 2026 · THE OPPORTUNITY ALMANAC", a Fraunces headline ("Every opportunity. One place."), one-line mission, and the **trust line**: "We index roles straight from company career pages — Greenhouse, Lever, Ashby — and always link you to the original source. We never mirror an application." A restrained engraving-style motif (extend the logo aesthetic; inline SVG, not a stock illustration).
- **Footer as an editorial colophon**: mission, sourcing transparency, "Built by a student, for students," refined link columns, the mark. A printed-almanac sign-off.
- **Considered empty states** (no results / no bookmarks / no matches): warm, branded, a single-line invitation — never a bare "Nothing here."
- **Account /profile as a "member card"**: the profile header as an elegant card (avatar + name + member-since + plan chip), forms with `.eyebrow` labels + generous grouping, the subscription as a refined plan card, progressive-disclosure security. (Notion/Stripe settings quality.)

## 5. Phasing (Codex work orders — each verified + shipped before the next)
- **Phase 1 — Foundation + core surfaces**: §2 (type scale, color refinement, grain, shadow system, motion, selection/scrollbar/eyebrow utilities) + apply to Header, OpportunityCard, Feed toolbar, and the Button/Badge/Input/Select primitives. *Highest leverage; visibly transforms the main experience.*
- **Phase 2 — Story + trust**: §4 signed-out hero, footer colophon, empty states.
- **Phase 3 — Account/profile + detail + pricing polish**: the member-card account, opportunity-detail editorial layout, pricing plan cards.

## 6. Guardrails (so it stays premium, not busy)
Restraint > decoration. One accent (bronze), one heritage-accent (plum, rare). Motion subtle + purposeful. AA contrast preserved (the globals.css comments already track ratios). Keep it fast (no heavy libs; SVG/CSS only). Every value on the scale. If a choice looks like the generic default, change it and say why.

## 7. Decision-log delta (docs/README.md)
- **Binding**: the brand POV is **heritage editorial ("The Almanac")** — cream paper, bronze accent, plum heritage-mark, Fraunces display, subtle grain. All future UI honors this system; no per-page ad-hoc styling.
