# Hiring Calendar programme expansion — 2026-11-13

Scope: official-organiser research for the 2027 calendar. No account access,
form submissions, production imports, schema changes, dependencies, or commits.

Every entry below has `source_checked_on: 2026-11-13` in the import data.
Application dates are distinguished from cohort/project dates. No newly added
application window was confirmed for 2027, so every new edition is `expected`.
An undated rolling entry means timing varies or is unavailable; it does not mean
applications are open. The existing importer creates the editions; no duplicate
authored entries are added to `programme_editions.json`.

## Research method

Read each origin's robots policy before fetching its public pages; requests used
the existing calendar fetcher's identifying User-Agent and at least one second
between requests to a host, including redirects. Robots redirects were followed
for this research, and destination policies were checked before page redirects.
An unavailable policy stopped direct page fetching. Raw working notes were kept
under ignored `_local/`; only these paraphrased findings are tracked.

Most relevant robots results: Google Developers, Hacktoberfest, GirlScript's
canonical `.org` host, Summer of Bitcoin, KDE Mentorship, Amazon Science/Jobs,
Technovation, Cisco and Uber returned policies permitting the requested paths.
Outreachy's and KDE Community Wiki's `/robots.txt` returned 404 (no policy).
Linux Foundation Docs redirected robots to its `/lfx/robots.txt` policy.
MLH Fellowship's policy returned HTTP 400; its programme facts below therefore
come from the indexed official page, not a direct live fetch. Samsung Newsroom's
robots retrieval was inconclusive, so no direct article request followed it.

## Added rows and supporting facts

| ID / canonical slug | Programme / category | Calendar window | Official evidence and interpretation |
|---|---|---|---|
| OPP-101 / `gsoc` | Google Summer of Code / `open_source` | Mar–Apr 2027, tentative | [Google timeline](https://developers.google.com/open-source/gsoc/timeline): the 2026 contributor call was Mar 16–31; the general schedule describes applications in March and closing in April. Organisation applications are a different stage. |
| OPP-102 / `hacktoberfest` | Hacktoberfest / `open_source` | Oct 2027 participation month, tentative; registration cutoff unknown | [Official event](https://hacktoberfest.com/): the October 2026 event finished Oct 31. Its format changed, and MLH/DEV powered it with DigitalOcean as presenting partner. No old PR-count/reward rules or 2027 registration dates are carried forward. |
| OPP-103 / `mlh-fellowship` | MLH Fellowship / `open_source` | Undated, rolling by batch | [Official Software Engineering track](https://fellowship.mlh.com/programs/software-engineering): indexed page lists Spring 2027, Jan 25–Apr 16, and says applications are rolling until a few weeks before each batch. Those cohort dates cannot supply application boundaries. Summer/Fall 2027 dates remain unverified. |
| OPP-104 / `outreachy` | Outreachy / `open_source` | Feb and Aug 2027, two separate tentative initial-application windows | [Official home page](https://www.outreachy.org/): May 2026 initial applications were in February; December 2026 initial applications in August. Later contributions/final proposals in Mar–Apr and Sep–Oct are separate stages. A December 2026 internship ending in March 2027 is not a new 2027 application round. |
| OPP-105 / `lfx-mentorship` | LFX Mentorship / `open_source` | Jan–Feb, Apr–May, Jul–Aug 2027, three separate tentative windows | [Official schedule](https://docs.linuxfoundation.org/lfx/mentorship/mentorship-program-timelines): projects become available around mid-January, mid-April and mid-July, with applications lasting roughly four weeks. Project dates can vary; the March, June and September term starts are not application openings. |
| OPP-106 / `girlscript-summer-of-code` | GirlScript Summer of Code / `open_source` | Mar 2027 tentative opening month; cutoff unknown | [Canonical organiser site](https://gssoc.girlscript.org/): 2026 applications opened Mar 24, followed by late March/early April selection. Selection dates are not invented cutoffs. The checked open-source track is closed; other-track application banners do not confirm a 2027 call. |
| OPP-107 / `summer-of-bitcoin` | Summer of Bitcoin / `open_source` | Feb 2027, tentative | [Official timeline](https://www.summerofbitcoin.org/how-it-works/): indexed official page gives Feb 1–15, 2026 for initial applications. [Directly retrieved organiser guide](https://guide.summerofbitcoin.org/about/how-it-works) corroborates February's deadline. Later challenge/proposal dates are not initial application dates. |
| OPP-108 / `season-of-kde` | Season of KDE / `open_source` | Dec 2026–Jan 2027, tentative | [Official SoK page](https://mentorship.kde.org/sok/): the 2026 edition opened Dec 15, 2025 and closed contributor applications Jan 14, 2026. [2027 ideas](https://community.kde.org/SoK/Ideas/2027) exist without confirming application dates. |
| OPP-109 / `women-techmakers-ambassadors` | Women Techmakers Ambassadors / `early_career` | May 2027 tentative opening month; cutoff unknown | [Current organiser](https://www.technovation.org/women-techmakers): Google's ambassador URL redirects here. The page expects the next ambassador opening in May, without a year or closing date. Record Technovation as organiser; this is community leadership, not a Google internship. |
| OPP-110 / `amazon-ml-summer-school` | Amazon ML Summer School — India / `early_career` | Aug–Sep 2027, tentative historical watch | [Amazon Science announcement](https://www.amazon.science/news-and-features/third-annual-2023-ml-summer-school-amazon-india): Aug 24, 2023 announcement and Sep 6 cutoff. The article links a 2025 edition without dates. Earlier editions used other months; this older, variable pattern is explicitly disclosed, not claimed as a fixed annual schedule. Training does not guarantee hiring. |
| OPP-111 / `amazon-wow` | Amazon Women of the World / `early_career` | Undated, session-dependent | [Amazon Jobs](https://www.amazon.jobs/content/en/career-programs/university/women-of-the-world): university community, career resources and events; no dated 2027 application cycle. Check each session's regional eligibility. |
| OPP-112 / `uber-she-plus-plus` | Uber She++ / `early_career` | Undated, location/event-dependent | [Uber programme](https://jobs.uber.com/en/teams/emerging-talent/sheplusplus/): includes India among locations and describes a professional-development summit. No India 2027 application window is published. |
| OPP-113 / `cisco-thingqbator` | Cisco thingQbator / `early_career` | Undated, cohort/institution-dependent | [Cisco India CSR](https://www.cisco.com/c/en_in/about/csr/india-cash-grants.html): confirms the nasscom foundation partnership and engineering-student innovation support. No 2027 call was found. Entrepreneurship support is not Cisco recruitment. |
| OPP-114 / `cisco-student-internships` | Cisco Internships and Co-ops / `early_career` | Undated, vacancy-dependent | [Cisco entry-level careers](https://careers.cisco.com/global/en/entry-level-careers): internships/co-ops last 3–12 months, varying by region/group. Global programme evidence does not confirm a current India vacancy or an India-wide deadline. |

The five existing open-source registry slugs above are reused. Outreachy and LFX
use the existing month-precision recurrence mechanism, not separate programme
records. New data uses existing category keys. The importer now accepts
`open_source` and `early_career` directly while retaining the original source's
legacy category translations. Known opening months with unknown deadlines use
the existing `deadline_rolling` presentation rule.
Hacktoberfest's existing registry description, organiser and eligibility wording
are also updated to match the current event rather than obsolete contribution
rules.

## Not dated or duplicated

The metadata's separate `watchlist` records the exact label
`unverified/legacy watchlist`, a checked source, and a reason. It is deliberately
outside `programmes` and has no import row or dates.

| Candidate | Result |
|---|---|
| FOSSASIA Codeheat | Official site still advertises Dec 2023–Mar 2024. No current cycle verified. |
| Google STEP India | General student/careers pages do not establish a current India STEP call or named successor. |
| Microsoft Engage | Checked programme route reaches a not-found screen. Explore already exists as OPP-034 and its current official overview still confirms the programme; no duplicate successor is invented. |
| Walmart CodeHers | Official-site search found no organiser-hosted call; candidate programme paths returned 404. Sparkathon remains separate. |
| Goldman Sachs Women in Tech / Engineering Campus Hiring | No current named India call or dated campus cycle verified. Checked engineering-campus paths returned 404. Existing analyst programmes and hackathon remain separate. |
| Intel India | Student and India links redirected to a Workday shell without readable programme facts. Historic employee accounts do not establish a current cycle. |
| Samsung R&D India | Official centre/career links verified, but no 2027 application cycle. The indexed PrePARe article describes a 2025 PhD programme; newsroom robots could not be verified, so no dated addition is made. |
| Directi / Media.net | Directi careers path returned 404; Media.net's current careers content has no student application-month cycle. |
| Sprinklr | The official internship/early-careers page confirms programmes and recruiting steps, but no India application months. Spring/Summer/Winter '26 labels refer to releases. |
| ZS | Interview FAQ mentions a campus season without months. Its response-time estimate is not a calendar window. |
| Deloitte | Official US-India campus page directs applicants to their placement teams for dates. |
| PwC | Official India campus page has programmes and contacts but no usable application months. |
| EY | India student page gives pathways but no national cycle. The separate scholarship page describes 2025; foreign recruitment calendars are not evidence for India. |
| KPMG | Student page links an FY-25 campus campaign, without a dated 2027 cycle. |
| Google Student Researcher, Flipkart GRiD, JPMorgan Code for Good, Adobe, Atlassian | Already represented by OPP-001, OPP-028, OPP-026, OPP-037 and OPP-031. No new rows. |

## Verification

Tests use local JSON, in-memory API fixtures, mocked fetches and the specified
local test database. No live research is part of a test. Coverage includes all
64 rows' visibility, provenance and tentative status of new rows, independent
Outreachy/LFX windows, the prior-year KDE opening, category filtering, watchlist
exclusion, and repeated import preserving the five seeded programme identities.

Results on the specified local database and stub service configuration:

- Calendar and programme tests: **259 passed**.
- Full backend suite on the final data: **4,256 passed** (one existing
  Starlette/httpx deprecation warning).
- `uv run python -m ruff check .`: clean.
- `uv run python -m black --check .`: clean, 345 files unchanged.
- `git diff --check`: clean.

The default Windows pytest temporary directory was inaccessible. Runs using
`--basetemp ../_local/pytest-calendar-research` and
`--basetemp ../_local/pytest-backend-calendar-research` resolved that environment
issue. `UV_CACHE_DIR` also pointed inside this worktree and `uv run --no-sync`
used the existing environment. No dependencies were installed. The 64 import
rows comprise 53 distinct dated rows and 11 undated rolling rows; new rows
contribute nine dated rows and five rolling rows. Production import/refresh was
not run, and no commit was made.
