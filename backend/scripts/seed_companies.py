"""Seed verified companies across all registered ATS adapters (Doc 04 sec
11: onboarding playbook; Doc handoffs/PHASE-2-HANDOFF.md sec 5, Part 2.5
adds Lever + Ashby to the original Greenhouse-only seed).

Board tokens are DATA, never hardcoded in adapter code - this script is the
one place new ATS-covered companies get added. Every token below was checked
live (HTTP 200 + non-empty jobs array) before being added; do not add a token
without verifying it first, and remove any that start 404ing.

Idempotent - safe to re-run. Usage: uv run python -m scripts.seed_companies
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.db import make_engine
from core.models import Company, Source

# (board_token, company_name, domain) - verified live against
# https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true
GREENHOUSE_COMPANIES = [
    ("stripe", "Stripe", "stripe.com"),
    ("airbnb", "Airbnb", "airbnb.com"),
    ("discord", "Discord", "discord.com"),
    ("robinhood", "Robinhood", "robinhood.com"),
    ("figma", "Figma", "figma.com"),
    ("coinbase", "Coinbase", "coinbase.com"),
    ("asana", "Asana", "asana.com"),
    ("brex", "Brex", "brex.com"),
    ("pinterest", "Pinterest", "pinterest.com"),
    ("reddit", "Reddit", "reddit.com"),
    ("cloudflare", "Cloudflare", "cloudflare.com"),
    ("gitlab", "GitLab", "gitlab.com"),
    ("affirm", "Affirm", "affirm.com"),
    ("airtable", "Airtable", "airtable.com"),
    ("anthropic", "Anthropic", "anthropic.com"),
    ("chime", "Chime", "chime.com"),
    ("cockroachlabs", "Cockroach Labs", "cockroachlabs.com"),
    ("databricks", "Databricks", "databricks.com"),
    ("dropbox", "Dropbox", "dropbox.com"),
    ("faire", "Faire", "faire.com"),
    ("flexport", "Flexport", "flexport.com"),
    ("gemini", "Gemini", "gemini.com"),
    ("instacart", "Instacart", "instacart.com"),
    ("lyft", "Lyft", "lyft.com"),
    ("mongodb", "MongoDB", "mongodb.com"),
    ("samsara", "Samsara", "samsara.com"),
    ("scaleai", "Scale AI", "scale.com"),
    ("sofi", "SoFi", "sofi.com"),
    ("twitch", "Twitch", "twitch.tv"),
    ("postman", "Postman", "postman.com"),
    ("phonepe", "PhonePe", "phonepe.com"),
    ("druva", "Druva", "druva.com"),
    ("razorpaysoftwareprivatelimited", "Razorpay", "razorpay.com"),
    ("datadog", "Datadog", "datadoghq.com"),
    ("verkada", "Verkada", "verkada.com"),
    ("roblox", "Roblox", "roblox.com"),
    ("gusto", "Gusto", "gusto.com"),
    ("duolingo", "Duolingo", "duolingo.com"),
    ("temporaltechnologies", "Temporal", "temporal.io"),
    ("squarespace", "Squarespace", "squarespace.com"),
    # India fintech, probed live 2026-07-22 (12 and 63 open roles).
    ("groww", "Groww", "groww.in"),
    ("slice", "Slice", "sliceit.com"),
    # Lever A batch, probed live 2026-07-24 (HTTP 200 + non-empty jobs).
    ("checkr", "Checkr", "checkr.com"),
    ("webflow", "Webflow", "webflow.com"),
    ("calendly", "Calendly", "calendly.com"),
    ("amplitude", "Amplitude", "amplitude.com"),
    ("mixpanel", "Mixpanel", "mixpanel.com"),
    ("launchdarkly", "LaunchDarkly", "launchdarkly.com"),
    ("pagerduty", "PagerDuty", "pagerduty.com"),
    ("elastic", "Elastic", "elastic.co"),
    ("circleci", "CircleCI", "circleci.com"),
    ("vercel", "Vercel", "vercel.com"),
    ("fivetran", "Fivetran", "fivetran.com"),
    ("monzo", "Monzo", "monzo.com"),
    ("gocardless", "GoCardless", "gocardless.com"),
    ("remotecom", "Remote", "remote.com"),
]

# (board_token, company_name, domain) - verified live against
# https://api.lever.co/v0/postings/{token}?mode=json
LEVER_COMPANIES = [
    ("weride", "WeRide", "weride.ai"),
    ("angellist", "AngelList", "angellist.com"),
    ("wealthfront", "Wealthfront", "wealthfront.com"),
    ("spotify", "Spotify", "spotify.com"),
    ("cred", "CRED", "cred.club"),
    ("zeta", "Zeta", "zeta.tech"),
    ("palantir", "Palantir", "palantir.com"),
    # India supply. Probed live 2026-07-22 against a BOGUS-token control first:
    # api.lever.co returns an error OBJECT (not a list) for unknown tokens, so a
    # naive len() reads it as "2 jobs" and every guess looks like a real board.
    # Only tokens returning an actual JSON list were kept.
    ("meesho", "Meesho", "meesho.com"),
    ("mindtickle", "Mindtickle", "mindtickle.com"),
]

# (board_token, company_name, domain) - verified live against
# https://api.ashbyhq.com/posting-api/job-board/{token}
ASHBY_COMPANIES = [
    ("linear", "Linear", "linear.app"),
    ("notion", "Notion", "notion.so"),
    ("ashby", "Ashby", "ashbyhq.com"),
    ("browserbase", "Browserbase", "browserbase.com"),
    ("cohere", "Cohere", "cohere.com"),
    ("elevenlabs", "ElevenLabs", "elevenlabs.io"),
    ("mercor", "Mercor", "mercor.com"),
    ("modal", "Modal", "modal.com"),
    ("openai", "OpenAI", "openai.com"),
    ("perplexity", "Perplexity", "perplexity.ai"),
    ("ramp", "Ramp", "ramp.com"),
    ("replit", "Replit", "replit.com"),
    ("sardine", "Sardine", "sardine.ai"),
    ("vanta", "Vanta", "vanta.com"),
    ("watershed", "Watershed", "watershed.com"),
    ("harvey", "Harvey", "harvey.ai"),
    ("sierra", "Sierra", "sierra.ai"),
    ("decagon", "Decagon", "decagon.ai"),
    ("supabase", "Supabase", "supabase.com"),
    ("abridge", "Abridge", "abridge.com"),
    ("character", "Character.AI", "character.ai"),
    ("resend", "Resend", "resend.com"),
    # AI/dev-infra boards students target. Probed live 2026-07-22; the
    # bogus-token control returns "Not Found", so these counts are real.
    ("cursor", "Cursor", "cursor.com"),
    ("langchain", "LangChain", "langchain.com"),
    ("baseten", "Baseten", "baseten.co"),
    ("deepgram", "Deepgram", "deepgram.com"),
    ("fireworksai", "Fireworks AI", "fireworks.ai"),
    ("railway", "Railway", "railway.app"),
    ("neon", "Neon", "neon.tech"),
    ("runway", "Runway", "runwayml.com"),
    # Lever A batch, probed live 2026-07-24 (bogus-token control = "Not Found").
    ("prefect", "Prefect", "prefect.io"),
    ("writer", "Writer", "writer.com"),
    ("pika", "Pika", "pika.art"),
    ("suno", "Suno", "suno.com"),
    ("poolside", "Poolside", "poolside.ai"),
    ("lovable", "Lovable", "lovable.dev"),
    ("cognition", "Cognition AI", "cognition.ai"),
    ("zed", "Zed", "zed.dev"),
    ("warp", "Warp", "warp.dev"),
    ("mintlify", "Mintlify", "mintlify.com"),
]

# (board_token, company_name, domain) - verified live against
# https://api.smartrecruiters.com/v1/companies/{identifier}/postings
SMARTRECRUITERS_COMPANIES = [
    ("Wise", "Wise", "wise.com"),
    ("WesternDigital", "Western Digital", "westerndigital.com"),
    ("UniversalMusicGroup", "Universal Music Group", "universalmusic.com"),
]

# Domains are NOT guessed: each is the `companyWebsite` the company itself
# declares in its own Keka careers portal config
# (/careers/api/organization/default/careerportalinfo), reduced to a bare
# domain and verified to resolve 200. The four left None declare no website
# there - a wrong domain would attach the wrong logo AND could collide with
# the partial unique index on companies.domain, so None is the honest value.
KEKA_COMPANIES = [
    ("clickpost", "ClickPost", None),
    ("sjinnovation", "SJ Innovation", "sjinnovation.com"),
    ("zluri", "Zluri", None),
    ("qualminds", "QualMinds", "qualminds.com"),
    ("talentformula", "Talent Formula", None),
    ("arisinfra", "ArisInfra", "aris.in"),
    ("lumel", "Lumel", "lumel.com"),
    ("auracloud", "Aura Cloud", "auracloud.com"),
    # wealthindia REMOVED (founder-authorized): its only listing was literally
    # titled "Test HR Intern" - the company's own test posting - so the board
    # contributed nothing but noise to a student feed. Removing it from this
    # list is not sufficient on its own: the companies row must also be gone,
    # because the crawl selects boards by companies.ats_type, not by this list.
    # Second wave, same verification: probed live for a resolvable tenant UUID,
    # a non-empty active-jobs array, and no test/dummy listings before being
    # written here. +123 jobs / 109 India roles / 6 internships.
    # adda247 declares its own Keka careers URL as its "website", which is not a
    # company domain, so it stays None rather than becoming a wrong logo.
    ("cloudthat", "CloudThat", "cloudthat.com"),
    ("satsure", "SatSure Analytics India", None),
    ("adda247", "Adda247", None),
    ("softprodigy", "SoftProdigy System Solutions", "softprodigy.com"),
]

# BoschGroup (4667) and DeliveryHero (1110) are verified-available but held out
# for now to bound crawl duration until async/lazy detail fetch is added.

# Amazon uses one employer-wide search API. The board token is only a stable
# marker for the shared adapter interface and is not sent to the endpoint.
AMAZON_COMPANIES = [("amazon", "Amazon", "amazon.com")]

# adapter_key -> (source slug/name/base_url, company list)
_ADAPTER_SOURCES: dict[str, tuple[str, str, str, list[tuple[str, str, str | None]]]] = {
    "greenhouse": (
        "greenhouse",
        "Greenhouse",
        "https://boards-api.greenhouse.io",
        GREENHOUSE_COMPANIES,
    ),
    "lever": ("lever", "Lever", "https://api.lever.co", LEVER_COMPANIES),
    "ashby": ("ashby", "Ashby", "https://api.ashbyhq.com", ASHBY_COMPANIES),
    "smartrecruiters": (
        "smartrecruiters",
        "SmartRecruiters",
        "https://api.smartrecruiters.com",
        SMARTRECRUITERS_COMPANIES,
    ),
    "keka": ("keka", "Keka", "https://www.keka.com", KEKA_COMPANIES),
    "amazon": ("amazon", "Amazon", "https://www.amazon.jobs", AMAZON_COMPANIES),
}

# Aggregator sources (Doc 04 sec 1: best-effort tier) have no fixed
# per-company list - crawl_aggregator resolves/creates each listing's
# Company row dynamically (pipeline/company_resolution.py) - so they're
# seeded as a bare Source row only, separately from _ADAPTER_SOURCES.
_AGGREGATOR_SOURCES: dict[str, tuple[str, str, str]] = {
    "devpost": ("devpost", "Devpost", "https://devpost.com"),
    "remoteok": ("remoteok", "RemoteOK", "https://remoteok.com"),
    "unstop": ("unstop", "Unstop", "https://unstop.com"),
}


def seed() -> None:
    engine = make_engine()
    with Session(engine) as session:
        total_created, total_updated = 0, 0

        for adapter_key, (slug, name, base_url, companies) in _ADAPTER_SOURCES.items():
            source = session.scalar(select(Source).where(Source.slug == slug))
            if source is None:
                source = Source(
                    slug=slug,
                    name=name,
                    type="ats",
                    base_url=base_url,
                    crawl_tier=1,
                    adapter_key=adapter_key,
                )
                session.add(source)
                print(f"created source: {slug}")
            else:
                print(f"source already exists: {slug}")

            for board_token, company_name, domain in companies:
                # Bare board_token, matching the already-seeded Greenhouse
                # companies exactly (Doc 08: never change an existing
                # identifier scheme without a real migration) - a
                # namespaced slug would silently duplicate every company
                # already seeded in production instead of updating it,
                # since this script's own idempotency depends on the slug
                # it looks up matching what's already there.
                # Public slug is lowercased for a consistent URL/slug scheme;
                # ats_board_id below keeps the exact provider identifier.
                company_slug = board_token.lower()
                company = session.scalar(select(Company).where(Company.slug == company_slug))
                if company is None:
                    session.add(
                        Company(
                            slug=company_slug,
                            name=company_name,
                            name_normalized=company_name.lower(),
                            domain=domain,
                            ats_type=adapter_key,
                            ats_board_id=board_token,
                        )
                    )
                    total_created += 1
                else:
                    company.ats_type = adapter_key
                    company.ats_board_id = board_token
                    company.domain = domain
                    total_updated += 1

        for adapter_key, (slug, name, base_url) in _AGGREGATOR_SOURCES.items():
            source = session.scalar(select(Source).where(Source.slug == slug))
            if source is None:
                session.add(
                    Source(
                        slug=slug,
                        name=name,
                        type="aggregator",
                        base_url=base_url,
                        crawl_tier=1,
                        adapter_key=adapter_key,
                    )
                )
                print(f"created source: {slug}")
            else:
                print(f"source already exists: {slug}")

        session.commit()
        print(f"companies: {total_created} created, {total_updated} updated")


if __name__ == "__main__":
    seed()
