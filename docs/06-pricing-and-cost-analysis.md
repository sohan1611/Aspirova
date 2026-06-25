# 06 — Pricing & Cost Analysis

*Author: Chief Architect + CPO. Every number here is reproducible from the assumptions in §1. If you change an assumption, re-derive — don't trust a stale figure.*

> **Project context (2026-06-25).** Aspirova is currently being built as a **project**, not a live commercial product. The economics below are a *reference model* — they show the system would be financially sustainable **if** run live, and they exist so the implementation (plans, feature gating, annual billing) is built correctly from day one. Profit is not the immediate goal; a correct, sustainable build is.

---

## 1. Canonical pricing (binding — build to exactly these)

| Plan | Monthly | Annual | Annual saving vs 12× monthly | Effective monthly on annual |
|------|--------:|-------:|------------------------------|----------------------------:|
| **Free** | ₹0 | ₹0 | — | — |
| **Pro Lite** | **₹39** | **₹399** | ₹468 − ₹399 = **₹69 → ~15% off** | **₹33.25** |
| **Pro** | **₹49** | **₹499** | ₹588 − ₹499 = **₹89 → ~15% off** | **₹41.58** |

- **Annual saving math:** 12 × ₹39 = ₹468 → annual ₹399 saves ₹69 (**14.7% ≈ 15%**). 12 × ₹49 = ₹588 → annual ₹499 saves ₹89 (**15.1% ≈ 15%**). Both annual plans advertise **"~15% off — 2 months effectively free."**
- **Decoy logic intact:** Pro Lite ₹39 vs Pro ₹49 is a ₹10 (~25%) gap. For ₹10 more the student gets AI Copilot + Resume Match + Prediction — so Pro is the obvious choice. Pro Lite anchors; most payers pick Pro.
- **Display the annual plan as the default highlighted option** at checkout (it improves cash + retention — §5).

---

## 2. Anchored cost/revenue assumptions

| Assumption | Value | Why |
|------------|-------|-----|
| FX | **₹95 = $1** | Vendor costs are USD-priced; income is INR — a weaker rupee raises real cost |
| Plan mix among payers | ~85% Pro, ~15% Pro Lite | Decoy psychology pushes to Pro |
| **Blended ARPPU (monthly)** | **₹47.5/mo** | 0.85×49 + 0.15×39 |
| Conversion — realistic | **3%** of all users pay | Sober for a free-heavy student product |
| Conversion — optimistic | **5%** | Achievable with indispensable Pro features |
| Render (backend) | $7/mo | always-on API |
| Supabase | $0 ≤~1k users, then $25/mo | free ≤500MB, Pro from ~5k |
| Vercel + GitHub Actions | $0 | frontend + crawlers on free tiers |
| Upstash Redis | $0 → $5 → $10 | serverless, pay-per-use |
| Email (AWS SES) | $0.10 / 1,000 emails | daily digest ≈ 30 emails/active user/mo |
| AI (run lean) | $3 → $20/mo | **fixed-ish** — scales with opportunities, not users (Doc 05) |

> **The cost insight that still governs everything:** AI and infra are *fixed-ish* (they scale with opportunities/data, not users). **Email is the only cost that scales linearly with users.** As you grow, the fixed costs amortize toward zero-per-user and email becomes the thing to optimize. "Crawl once, serve many" in action.

---

## 3. Realistic scenario (3% conversion, lean operation, ₹95/$)

Revenue = payers × ₹47.5. Out-of-pocket = costs − revenue.

| Users | Payers | Costs ₹/mo | Subscription income ₹/mo | **Out of pocket ₹/mo** |
|------:|-------:|-----------:|-------------------------:|-----------------------:|
| 100    | 3   | ~1,074 | 143    | **−931** |
| 500    | 15  | ~1,283 | 713    | **−570** |
| 1,000  | 30  | ~1,520 | 1,425  | **−95** (≈ break-even) |
| 5,000  | 150 | ~6,175 | 7,125  | **+950** (profit) |
| 10,000 | 300 | ~8,835 | 14,250 | **+5,415** (profit) |

**What changed vs the old ₹25/₹30 model — and why it matters:** raising prices to ₹39/₹49 lifts ARPPU from ₹29.25 → ₹47.5 (**+62%**). That, combined with lean costs, **moves break-even from ~10,000 users down to ~1,100 users.** The pricing change is the single biggest improvement to viability.

- **You reach roughly break-even at ~1,000 users** (−₹95/mo, a rounding error).
- **You are clearly profitable from ~1,500 users onward**, reaching **+₹5,415/mo at 10,000 users.**
- **Out-of-pocket never exceeds ~₹931/mo** (at 100 users) and shrinks from there — **comfortably inside a ₹2,000/mo budget the entire way.**

**Cost breakdown (USD, ×95 → ₹):** 100u: Render 7 + domain 1 + email 0.3 + AI 3 = $11.3. 1k: 7+1+3+5 = $16. 5k: 7+1+Supabase 25+Upstash 5+email 15+AI 12 = $65. 10k: 7+1+25+10+30+20 = $93. *(If you run fuller AI rather than lean, add roughly $15–30/mo at scale — still profitable past ~2k users.)*

---

## 4. Optimistic scenario (5% conversion)

Same lean costs; only conversion changes.

| Users | Payers | Income ₹/mo | Costs ₹/mo | **Out of pocket ₹/mo** |
|------:|-------:|------------:|-----------:|-----------------------:|
| 1,000  | 50  | 2,375  | 1,520 | **+855 (profit)** |
| 5,000  | 250 | 11,875 | 6,175 | **+5,700 (profit)** |
| 10,000 | 500 | 23,750 | 8,835 | **+14,915 (profit)** |

At 5% conversion you're **profitable below 1,000 users.** Conversion remains the highest-leverage variable: every paywall decision is a bet on this number.

---

## 5. Profit accelerators (ranked) — to reach/grow profit faster

Even though the new pricing makes B2C viable on its own, these stack on top:

1. **Conversion (3%→5%)** — at 1,000 users this is the difference between −₹95 and +₹855/mo. Fully in your control via Match/Copilot/instant alerts.
2. **B2B campus licenses** — one license at ₹30,000/yr = ₹2,500/mo = the revenue of **~53 Pro subscribers**, from one relationship at ~zero incremental cost. A single deal makes you solidly profitable at **1,000 users**; a few deals dwarf B2C.
3. **Annual plans (₹399/₹499)** — ~15% discount the student happily takes; you get cash upfront, ~12× fewer transactions, and far less involuntary churn (failed monthly auto-renewals — the silent killer of micro-subscriptions). Highlight annual as the default.
4. **Ethical, clearly-labeled sponsored listings** — never pollute the organic feed.
5. **Affiliate referrals** (resume tools, courses) — small, near-free, contextual.

---

## 6. Cost reductions (already designed into the architecture)

- **Change detection (Doc 04 §6):** unchanged pages skip parse + dedup + AI — keeps the AI line flat as crawl frequency rises.
- **Lean AI (Doc 05):** cheapest model, short outputs, extractive fallback, enrich once per *canonical* opp after dedup. Embeddings are ~free; LLM summaries are the cost.
- **Email discipline:** one daily digest (not per-opportunity), instant alerts bounded to Pro + dream companies, suppress inactive recipients, Resend → SES at scale. Halving the active-recipient rate halves the email line.
- **Free tiers everywhere:** Vercel, GitHub Actions, Supabase-free (≤1k), Upstash-free early.
- **Render stays light:** never run crawlers/Playwright on the paid dyno.

---

## 7. When you actually spend more (measured triggers, not guesses)

| Trigger (measured) | Spend |
|--------------------|-------|
| Supabase free tier exhausted (~1k+ users of data) | → Supabase Pro $25 |
| Email becomes the top cost line | → Resend → SES; tighter batching; suppress inactives |
| GitHub Actions minutes near cap | → stagger schedules / one cheap crawl box |
| Render API saturated | → vertical bump; edge-cache SSR |
| pgvector / FTS latency misses SLO | → tune HNSW; only then Meilisearch |

**Principle (binding, Doc 02):** scale by trigger, never by anticipation.

---

## 8. Bottom line

With **Pro Lite ₹39 / Pro ₹49** (annual ₹399 / ₹499, ~15% off) at **₹95/$**:
- Running lean, **out-of-pocket stays under ~₹950/mo at every stage** — well inside a ₹2,000/mo budget.
- **Break-even at ~1,000 users; profitable from ~1,500 users** on subscriptions alone at a sober 3% conversion.
- A **single campus B2B deal** brings profit forward to ~1,000 users; higher conversion or annual uptake accelerates it further.
- As a *project*, the takeaway is simpler: it costs little to run, and the economics are sound enough to go live later without re-architecting.

---

## Footnote — arithmetic, so figures are auditable

- Payers = round(users × conversion). Income₹ = payers × 47.5. Costs₹ = Σ(USD line items) × 95.
- Out-of-pocket₹ = Costs₹ − Income₹ (negative = loss, positive = profit).
- Annual saving% = (12×monthly − annual) ÷ (12×monthly). Pro Lite 69/468 = 14.7%; Pro 89/588 = 15.1%.
- All rupee figures rounded for display; recompute from raw for decisions.

---

## HANDOFF TO ENGINEERING

1. **Seed `plans` (Doc 03) with exactly these rows** — prices are data, never hardcoded:
   - `free` — ₹0
   - `pro_lite_monthly` — ₹39/mo · `pro_lite_annual` — ₹399/yr
   - `pro_monthly` — ₹49/mo · `pro_annual` — ₹499/yr
   - Store prices in **paise** (3900, 39900, 4900, 49900) to avoid float errors.
2. **Razorpay:** support both monthly and annual billing cycles; **default the checkout to the annual plan** and show the "~15% off / 2 months free" saving on Pro Lite (₹69) and Pro (₹89).
3. **Feature gating via `plans.features` jsonb** (Doc 02/08) — Pro Lite vs Pro differences (Copilot, Resume Match, Prediction, dream-company limits) live in data, gated by `can(user, feature)`.
4. **Instrument the model:** track signups, active (digest-eligible) users, conversion by plan + cycle, churn (voluntary vs involuntary), AI tokens/cost, email volume. Reality is measured against §3.
5. **AI spend alarm + graceful degradation** (Doc 05) — protects the flat AI line this model depends on.
6. **Schema hooks for later** (even if unused now): nullable `org_id`/license for B2B; a `sponsored` flag on opportunities (rendered clearly as "Sponsored").

**Definition of done for the cost layer:** the four paid plan rows (monthly + annual) are seeded as data with prices in paise; Razorpay bills both cycles with annual defaulted and the ~15% saving shown; gating is data-driven; AI/email costs are tracked and capped; the live numbers reconcile to §3.
