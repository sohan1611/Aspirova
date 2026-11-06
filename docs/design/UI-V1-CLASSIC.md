# UI v1 "Classic": the design before the 2026-11 redesign

*Written 2026-11-06, just before UI v2 (the blue-and-serif redesign) replaced it. The founder asked
to keep it so the site can go back. Everything needed to restore it is here or in git.*

## How to go back

The exact v1 code is tagged in git:

| Ref | What it is |
|-----|------------|
| tag `ui-v1-classic` | `master` at `44eb1c1`, the last commit with the v1 UI |
| `docs/design/ui-v1-classic/globals.css` | copy of v1 `frontend/app/globals.css` (every colour, radius, shadow, the paper texture) |
| `docs/design/ui-v1-classic/*.png` | screenshots of production on 2026-11-06 (desktop 1440 px, plus home at 390 px) |

**Full restore** (the cleanest route): revert the redesign's merge commit on a branch and open a PR.

```bash
git log --merges --oneline --grep "ui-v2" master
```

```bash
git revert -m 1 <merge-sha>
```

**Partial restore** (bring back only some v1 files after other work has landed on top):

```bash
git checkout ui-v1-classic -- frontend/app/globals.css frontend/app/layout.tsx
```

Do the same for any component in the "Files the redesign changed" list in the v2 PR description. Then
run `pnpm lint`, `pnpm exec tsc --noEmit` and `pnpm build` in `frontend/`.

## What v1 looked like

**Mood:** a warm, printed almanac. Cream paper, bronze ink, plum accents, a faint paper-grain
texture over the whole page.

### Type

| Role | Font | Notes |
|------|------|-------|
| Headings (`h1`, `h2`, `.font-serif`) | **Fraunces** (Google, `--font-fraunces`) | letter-spacing −0.02em, balanced wrap |
| Body and UI | **Geist Sans** (`--font-geist-sans`) | |
| Numbers, code | **Geist Mono** (`--font-geist-mono`) | `.tnum` for tabular figures |

Custom type scale on `:root`: `--text-2xs` 0.6875rem up to `--text-4xl` 3.05rem. `.eyebrow` is
0.6875rem, weight 600, tracking 0.16em, uppercase, muted.

### Colour (light theme; the site forces light)

| Token | v1 value | Used for |
|-------|----------|----------|
| `--background` | `#faf7f0` | cream page |
| `--foreground` | `#231c15` | warm near-black text |
| `--card` | `#fffdf8` | cards, popovers |
| `--primary` | `#8a5e2f` | bronze buttons, links, focus ring |
| `--secondary` / `--muted` / `--accent` | `#efe8d9` / `#f0e9db` / `#ece4d3` | chips, hover fills |
| `--muted-foreground` | `#6b5f4e` | secondary text |
| `--border` | `#e6ddcb` | hairlines |
| `--heritage` | `#5e2b47` | plum accent: "New", internship badge, urgent deadlines, "Hidden gem" |
| `--destructive` | `#b23b2e` | errors |
| brand scale | `--color-brand-50…950`, plum from `#f8eef4` to `#281021` | logo ink |

Semantic: success `#16a34a`, warning `#f59e0b` on `#451a03`, info `#0284c7`. The dark tokens exist
in the CSS copy but the site never showed them (`forcedTheme="light"`).

### Shape and depth

- `--radius` 0.625rem; cards `rounded-xl`, buttons `rounded-md`.
- Warm brown shadows (`rgba(35,28,21,…)`), `shadow-soft` / `shadow-soft-md`; cards lift 4 px on hover.
- `body::before` lays an SVG fractal-noise texture at 2.5% opacity: the paper grain.
- Easing `--ease-premium: cubic-bezier(0.16, 1, 0.3, 1)`, `animate-rise` entrance.

### Layout and navigation

- **Header:** sticky, translucent cream, 64 px. Round logo plus "Aspirova" in Fraunces, then a flat
  text nav: Jobs, Internships, Remote, Competitions, Scholarships, Research, Programmes, Companies,
  Pricing. Hover draws a 1 px bronze underline. Right side: notification bell and "Sign in" as a
  ghost link. Below `md` the nav moves into a left sheet (`MobileNav`), which also lists Saved,
  Resume check and Invite. There was no bottom tab bar.
- **Opportunity card:** favicon top-left, bookmark top-right, sans title, two-line summary, company
  plus "via Source" pill plus age, location line, "Pay"/"Prize pool" rows with a plum eyebrow, then a
  footer of badges (category, mode, part-time) and the deadline chip with "View →".
- **Opportunity page:** one centred column (max 5xl, text max 3xl). Back link, favicon and company,
  big Fraunces title, uppercase chips, a bordered action row (Apply, Save, Share, WhatsApp, Report),
  deadline chip with calendar links, "Skills for this role" chips, an "At a glance" card, the full
  brief, then "Related opportunities" as a three-card grid.
- **Competitions:** same card grid as the feed, with the location chips and sort control above it.
- **Programmes:** "The almanac" eyebrow, title, category buttons, then a grid of programme cards
  (category and country chips, Fraunces name, organiser, status box, description).
- **Resume check:** a single centred column of cards (saved resume, input, ATS estimate, skills,
  Pro shortlist).
