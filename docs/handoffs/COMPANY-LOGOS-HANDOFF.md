# Company logos: find once, save, reuse forever

*Architect handoff, 2026-11-06. Implementer: Codex (`gpt-6.1-sol`, effort high). Branch `feat/company-logos`.*

## 1. Why

Founder request: when listings arrive, find the company's logo on the internet, save it, and reuse the saved copy whenever the same company appears again. **Founder constraint (binding): never attach a logo the program is not sure of.** A small company with no clear match keeps its letter tile. A well-known company must not be left blank through carelessness.

Measured 2026-11-06 from the public `/companies` endpoint:

- 5,082 companies have live listings, and **0 have `logo_url`**: nothing in the backend writes it.
- 284 have a `domain`, which the frontend turns into a Google favicon. **4,798 (94%) show a letter tile.**
- 8,747 of 29,531 live listings (29.6%) render with a letter tile. The biggest gaps are WorldQuant (94), Physical Intelligence (40) and IIT Madras (36).
- Source payloads already carry logos we discard. Unstop's `organisation.logoUrl2` / `logoUrl` is the organiser's own upload. In a 20-job sample, Himalayas `companyLogo` was filled 17/20 and Jobicy `companyLogo` 20/20, one-to-one with companies. RemoteOK's `company_logo` / `logo` were 0/99 filled and Arbeitnow has no logo field: **skip those two**.

Real lookups show why no single signal can be trusted:

| Name | What a naive rule picks | Truth |
|---|---|---|
| WorldQuant | Clearbit's top result, WorldQuant University (`wqu.edu`); `scripts/backfill_domains.py` accepts it as a prefix match | `worldquant.com` |
| Indian Institute of Technology Madras | Clearbit exact-name result `cubeiitm.org` (a student club, title "Cube") | `iitm.ac.in` (Wikidata Q858662 P856; homepage title is the full name); an Unstop source logo is also available |
| Physical Intelligence | Clearbit exact-name result `physicalintelligence.com`, whose title is literally "Physical Intelligence" | `physicalintelligence.company`. Wikidata Q138658641 "Physical Intelligence Inc." exists but has **no P856**, so only the company's own listings can point there |

Recorded real responses for these cases live in `backend/tests/fixtures/logos/` (Clearbit, Wikidata search and entities trimmed to P31/P856/P154, homepage `<head>`s) and are the basis of the tests.

No AI or LLM, by the founder's AI-deferral ruling. Everything here is deterministic.

## 2. Flow

```
crawl → resolve_company (one row per name_normalized)
          ├─ row already has logo_url        → nothing to do (name cache hit, zero HTTP)
          └─ listing carries hints            → store logo_hint_url / fill a missing domain,
                                                reset logo_status to NULL so the worker re-checks
Logos worker (after every crawl; companies with ≥1 active listing, most active listings first):
  1. override in backend/data/company_logo_overrides.json → apply; status manual; never overwritten
  2. logo_hint_url (source payload)                      → validate → store; source "source_payload"
  3. companies.domain already set (trusted)              → icon from domain → validate → store
  4. else discover a domain (§3), accept a unique winner → icon from domain → validate → store
  5. nothing confident                                   → logo_status not_found / ambiguous
```

Retry rule (negative cache): a company is processed when `logo_url IS NULL` and `logo_status IS DISTINCT FROM 'manual'`, and either `logo_status IS NULL` or (`logo_status` is `not_found` / `ambiguous` / `rejected_generic` and `logo_checked_at` is older than `--recheck-days`, default 30).

## 3. Domain discovery and scoring

Normalize every name with `pipeline.normalize.normalize_company_name`, then strip trailing legal suffixes (the `_LEGAL_SUFFIXES` set in `scripts/backfill_domains.py`, moved to `core/domains.py`). Call the result the **key**. Collect candidate domains with their signals:

| Signal | Weight | Rule |
|---|---|---|
| `wikidata` | 2 | `wbsearchentities` (en, type=item, limit 7) then `wbgetentities` (labels, aliases, claims). The entity's en label or any en alias must have a key **equal** to the company key. It must not be P31=Q5 (human). Every P856 (official website) host is a candidate, except values with a P582 end-time qualifier. |
| `listing` | 2 | The host of an `apply_url`, or a URL / bare domain in `description_raw`, from up to 5 of the company's most recent active listings. Hosts in `JOB_BOARD_HOSTS` or `SHARED_HOSTS` are excluded (§6). At most 5 candidates come from text, chosen by frequency. |
| `clearbit` | 1 | `autocomplete.clearbit.com/v1/companies/suggest?query=<name>`. **Every** suggestion whose name key equals the company key counts, in any position. Prefix or "starts with" matches never count. |
| `title` | 1 | Fetch the homepage (respecting robots.txt, §5). `<title>`, `og:site_name`, `og:title` or `application-name` must contain the key as a whole-word token sequence. The final URL after redirects must still be on the candidate domain. |

- **Parked or for-sale pages disqualify the candidate entirely.** That means a score of 0, whatever else it has. Markers, case-insensitive, in the title or the first 5 KB of visible text: "domain is for sale", "buy this domain", "this domain may be for sale", "domain for sale", "parked", "sedo", "afternic", "hugedomains", "dan.com", "godaddy", "coming soon".
- Domains compare after lowercasing and stripping `www.`. Two hosts are the same site when one equals the other or ends with `"." + other`. Do **not** add a public-suffix list.
- **Merge** a candidate that is a subdomain of another candidate into the parent (for example, `respark.iitm.ac.in` folds into `iitm.ac.in`). **Each signal type counts at most once per candidate**, so two Wikidata entities pointing at the same site still score 2, not 4.
- **Accept** a candidate with score ≥ 3 **only if it is the only candidate at ≥ 3**. Two or more at ≥ 3 → `ambiguous`. None → `not_found`. The signals and per-candidate scores always go into `logo_evidence`.

Expected outcomes, which are also tests on the recorded fixtures:

- WorldQuant → `worldquant.com` scores 4 (wikidata + clearbit + title), accept. "WorldQuant University" and "WorldQuant Foundation" have different keys, so they never contribute.
- IIT Madras → `iitm.ac.in` scores 3 (wikidata, merged with the Research Park subdomain, + title), accept. `cubeiitm.org` scores 1 (clearbit; title "Cube").
- Physical Intelligence with no listing text → `physicalintelligence.com` scores 2 (clearbit + title) → **not_found**. The same company with a listing description mentioning `physicalintelligence.company` → that domain scores 3 (listing + title), accept, and the `.com` stays at 2.
- A tiny company with clearbit + title = 2 → not_found.

When a domain is accepted:

- if `companies.domain` is NULL and no other row holds that domain, set it;
- if another row holds it **and has `logo_url`**, copy that `logo_url`: source `domain_cache`, no download;
- otherwise fetch the icon and leave `companies.domain` alone, because the unique index forbids a duplicate.

## 4. Icon selection and image checks

Candidates for an accepted or trusted domain, in order:

1. Homepage `<link rel>` in {apple-touch-icon, apple-touch-icon-precomposed, icon, shortcut icon}, raster only (skip SVG), resolved against the final URL. Larger declared `sizes` first.
2. `https://<domain>/apple-touch-icon.png`.
3. `https://icons.duckduckgo.com/ip3/<domain>.ico`. Accept only HTTP 200, because it returns 404 plus a placeholder for unknown domains.
4. `https://www.google.com/s2/favicons?domain=<domain>&sz=128`. Accept only HTTP 200, because unknown domains get 404 plus a globe.
5. The Wikidata P154 logo via `https://commons.wikimedia.org/wiki/Special:FilePath/<file>?width=256`, **only if** its aspect ratio is ≤ 1.6.

Fetch up to the first 4 that exist, validate each, and keep the one with the largest smallest-side (ties go to the earlier one).

Validation (`core/logo_store.py`). A failure of any check means "no logo from this candidate":

- HTTP 200, `Content-Type` starting `image/` (or `application/octet-stream` with a body Pillow can decode; Unstop's CloudFront serves that), 100 B ≤ size ≤ 1 MB.
- Pillow decodes it. For ICO, take the largest frame. Convert to RGBA.
- Smallest side ≥ 32 px, aspect ≤ 4.
- Not fully transparent (every alpha below 16). Not near-uniform (opaque pixels' per-channel range below 12).
- Normalize: fit inside 128×128 preserving aspect (LANCZOS), centre on a transparent 128×128 canvas, PNG-encode. `sha256` of those bytes goes into the evidence.

**Generic-icon guard.** This is a post-pass at the end of every non-dry run, plus a check before each accept. If the same `sha256` is on found logos of ≥ 3 groups, where a group is `coalesce(evidence domain, company id)`, it is a platform default (Wix, WordPress, GoDaddy, globe). Clear `logo_url` on every non-manual row with that hash and set `logo_status = 'rejected_generic'`. Rows sharing one domain (domain-cache siblings) are one group and never trip it.

## 5. Network manners

- One shared `httpx.Client`, UA `AspirovaBot/1.0 (+https://www.aspirova.org)`, no email address, timeout 10 s, at most 5 redirects.
- At most 1 request per second per host (a small per-host limiter). A failed external call never raises out of the worker: it counts as "no signal".
- Before fetching a company homepage, read `https://<domain>/robots.txt` (`urllib.robotparser`, cached per domain for the run). If `/` is disallowed for `AspirovaBot`, skip the homepage: no title signal, no `<link>` icons. DuckDuckGo, Google s2 and Wikimedia are third-party services and are still allowed.
- Clearbit autocomplete is a legacy free endpoint. If it errors, carry on without it.

## 6. Host lists (`core/domains.py`)

- `JOB_BOARD_HOSTS`, which can never be a company's domain: lever.co, greenhouse.io, ashbyhq.com, workable.com, smartrecruiters.com, recruitee.com, keka.com, myworkdayjobs.com, workday.com, icims.com, bamboohr.com, breezy.hr, jobvite.com, teamtailor.com, personio.de, personio.com, unstop.com, devfolio.co, devpost.com, hackerearth.com, himalayas.app, jobicy.com, remoteok.com, arbeitnow.com, linkedin.com, indeed.com, glassdoor.com, wellfound.com, angel.co, naukri.com, internshala.com, instahyre.com, cutshort.io.
- `SHARED_HOSTS`, multi-tenant or generic, never a company's identity: google.com, goo.gl, forms.gle, bit.ly, tinyurl.com, linktr.ee, notion.site, notion.so, github.io, github.com, gitlab.io, medium.com, substack.com, wordpress.com, blogspot.com, wixsite.com, webflow.io, framer.website, carrd.co, vercel.app, netlify.app, herokuapp.com, typeform.com, calendly.com, youtube.com, youtu.be, twitter.com, x.com, facebook.com, instagram.com, t.me, wa.me, whatsapp.com, wikipedia.org, amazonaws.com, cloudfront.net, zoom.us, microsoft.com, office.com, sharepoint.com.
- `clean_domain(value) -> str | None` moves from `scripts/backfill_domains.py::_clean_domain`. It also strips `www.` and returns None for anything in the two lists, IP addresses, or hosts without a dot.

## 7. Storage

- R2 bucket `aspirova-logos` (founder creates it, with a public r2.dev URL). Key `logos/{company.slug}-{sha256[:8]}.png`, `ContentType=image/png`, `CacheControl="public, max-age=31536000, immutable"`. `companies.logo_url = LOGO_PUBLIC_BASE_URL.rstrip('/') + '/' + key`.
- Settings (`core/config.py`): `logo_s3_endpoint_url`, `logo_s3_access_key_id`, `logo_s3_secret_access_key`, `logo_s3_bucket`, `logo_public_base_url`. The boto3 client follows `scripts/backup_db.py::s3_client`.
- A non-dry run with storage not fully configured **aborts before touching any row**, with a clear message and a non-zero exit.
- No frontend change: `frontend/components/CompanyFavicon.tsx` and `pipeline/company_alert_email.py` already prefer `logo_url`.

## 8. Schema

New nullable columns on `companies`, in one Alembic revision (down_revision = current head) mirrored in `core/models.py`:

| Column | Type | Values |
|---|---|---|
| `logo_status` | text | NULL (never checked), `found`, `not_found`, `ambiguous`, `rejected_generic`, `manual` |
| `logo_source` | text | `override`, `source_payload`, `domain_icon`, `wikidata_logo`, `domain_cache` |
| `logo_checked_at` | timestamptz | |
| `logo_hint_url` | text | |
| `logo_evidence` | jsonb | domain, per-candidate signals and scores, chosen image URL, width/height, sha256 |

No index is needed: about 5.6k rows. The downgrade drops the five columns.

## 9. Parts

**Part 1: schema, hints, resolution.**

- Migration + model columns (§8).
- `core/domains.py` (§6), with `scripts/backfill_domains.py` importing `clean_domain` and `LEGAL_SUFFIXES` from it until Part 3 deletes the script.
- `NormalizedListing.company_logo_url: str | None = None` in `core/adapters.py`.
- Adapters fill it:
  - Unstop: `organisation.logoUrl2`, else `logoUrl`.
  - Himalayas: `companyLogo`.
  - Jobicy: `companyLogo`.
  - Only http(s) URLs, and never when `company_name` fell back to the source's own name ("Unstop", "Himalayas", "Jobicy").
- `pipeline/company_resolution.py::resolve_company(session, company_name, domain=None, *, logo_hint_url=None)`:
  - New rows get the domain via `clean_domain` and `logo_hint_url`.
  - For an existing row, (a) fill a NULL `domain` with the cleaned domain when no other row holds it; (b) when `logo_url` is NULL and `logo_status` is not `manual`, set `logo_hint_url` if it changed. If (a) or (b) changed anything and status is not `manual`, set `logo_status = NULL` so the worker re-checks.
  - Never touch a row whose `logo_url` is set.
- `crawlers/runner.py` passes `logo_hint_url=normalized.company_logo_url`.
- Update the monkeypatched `resolve_company` lambdas in `tests/test_crawler_reliability.py` and `tests/test_ingest.py` to accept the keyword.
- Tests: adapter extraction (Unstop fixture already has `logoUrl2`, and its empty-logo record), resolution hint/domain/reset behaviour, `clean_domain`.

**Part 2: discovery, scoring, image store.**

- `pipeline/company_logos.py`: pure functions taking an injected fetcher. Name key; Wikidata and Clearbit candidate extraction; listing-text candidates; homepage parse (title, og tags, icon links, parked markers); robots check; scoring and the unique-winner decision; icon candidate list.
- `core/logo_store.py`: download-validate-normalize (§4) and `upload_logo(settings, slug, png_bytes) -> url`.
- `pillow` dependency (Claude adds it to `pyproject.toml` / `uv.lock`, since the sandbox has no network).
- Settings fields.
- `tests/test_company_logos.py` with **recorded fixtures only, no network**. It covers every §3 expected outcome (WorldQuant, IIT Madras with the subdomain merge, cubeiitm, Physical Intelligence with and without listing text), parked rejection, tie → ambiguous, a 16 px icon rejected, a transparent or uniform image rejected, an ICO largest frame, DuckDuckGo/Google 404 ignored, and the P154 aspect gate.

**Part 3: worker, workflow, overrides.**

- `scripts/logo_worker.py`:
  - flags `--limit` (default 1500), `--time-budget-min` (45, stopping cleanly), `--dry-run`, `--recheck-days` (30), `--from-api-json PATH --report DIR`;
  - commits every 10 companies;
  - runs the generic post-pass;
  - calls `pipeline.revalidate.notify_changed` with the active-opportunity slugs of companies whose logo changed;
  - prints counts (`cache_hit`, `searched`, `found` by source, `not_found`, `ambiguous`, `rejected_generic`, `errors`);
  - prints the 25 companies with the most active listings still without a logo, with the reason.
- `--from-api-json` is the **offline review mode**:
  - reads the public `/companies` JSON (slug, name, domain, logo_url, active_count), most active first;
  - opens **no database connection at all**;
  - uploads nothing;
  - writes `decisions.csv` and `contact-sheet.html` into DIR. The sheet shows each accepted normalized PNG inline as a data URI, beside the name, active count, domain, source, score and signals, then a section of misses with reasons.
- `backend/data/company_logo_overrides.json` (starts as `{}`), keyed by company slug: `{"domain": "x.com"}` (treated as trusted), `{"logo_url": "https://…"}` (downloaded, validated, stored), or `{"block": true}` (clears `logo_url`). All three set status `manual`.
- `.github/workflows/logos.yml`:
  - `workflow_run` on "Crawl Tier 1" `completed`, plus `workflow_dispatch` with inputs `limit`, `time_budget_min`, `dry_run`;
  - concurrency group `logos`, `timeout-minutes: 60`, the same setup steps as `crawl-tier1.yml`;
  - env `DATABASE_URL`, `LOGO_S3_*`, `LOGO_PUBLIC_BASE_URL`, `REVALIDATE_URL`, `REVALIDATE_SECRET`, `PYTHONUNBUFFERED`.
- Delete `scripts/backfill_domains.py` and `tests/test_backfill_domains.py`.
- `.env.example` gains the `LOGO_*` vars.
- DB tests for the worker:
  - a row with `logo_url` makes zero fetches;
  - `not_found` is not retried inside 30 days, but a new hint resets it;
  - override wins, and `block` suppresses;
  - a domain-cache sibling gets a copy without a download;
  - the generic post-pass clears 3 groups sharing a hash but not 2 siblings sharing a domain;
  - a non-dry run without storage config aborts with no row changed.

## 10. Rules for the implementer

- Do **not** run pytest and do not touch any database. Claude runs the suite on a throwaway container. Do run `uv run ruff check .` and `uv run black --check .`.
- Do not change frontend files. Do not add a public-suffix list, an LLM call, or any paid API.
- Keep `scripts/backup_db.py` and its settings untouched. The logo bucket has its own credentials.

## 11. Rollout (founder)

1. Create the R2 bucket `aspirova-logos` and enable its public r2.dev URL. aspirova.org DNS is on Vercel, so a custom R2 domain would need a DNS move; switching later is one env var plus one UPDATE.
2. Create an R2 API token with Object Read & Write, scoped to that bucket only.
3. Add GitHub secrets: `LOGO_S3_ENDPOINT_URL` (same value as `BACKUP_S3_ENDPOINT_URL`), `LOGO_S3_ACCESS_KEY_ID`, `LOGO_S3_SECRET_ACCESS_KEY`, `LOGO_S3_BUCKET`, `LOGO_PUBLIC_BASE_URL`.
4. **Run `uv run alembic upgrade head` against prod before merging.** The new model columns are selected by `select(models.Company)`, so deploying the code before the columns exist would break company pages and the crawler. The migration only adds nullable columns, so it is safe under the old code.
5. Merge, then dispatch the Logos workflow once. It works through the backlog, most active companies first, over a few runs, and then runs after every crawl.
