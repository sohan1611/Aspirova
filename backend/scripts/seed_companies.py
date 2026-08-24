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
    # Lever A wave 2, probed live 2026-07-24.
    ("twilio", "Twilio", "twilio.com"),
    ("algolia", "Algolia", "algolia.com"),
    ("contentful", "Contentful", "contentful.com"),
    ("planetscale", "PlanetScale", "planetscale.com"),
    ("clickhouse", "ClickHouse", "clickhouse.com"),
    ("starburst", "Starburst", "starburst.io"),
    ("labelbox", "Labelbox", "labelbox.com"),
    ("tailscale", "Tailscale", "tailscale.com"),
    ("marqeta", "Marqeta", "marqeta.com"),
    ("mercury", "Mercury", "mercury.com"),
    ("stabilityai", "Stability AI", "stability.ai"),
    ("block", "Block", "block.xyz"),
    # GH/Ashby wave, probed live 2026-07-25 (HTTP 200 + non-empty jobs).
    # Counts at probe time noted.
    ("peloton", "Peloton", "onepeloton.com"),  # 64
    ("nuro", "Nuro", "nuro.ai"),  # 99
    ("coursera", "Coursera", "coursera.org"),  # 12
    ("turing", "Turing", "turing.com"),  # 31
    ("lattice", "Lattice", "lattice.com"),  # 7
    ("cultureamp", "Culture Amp", "cultureamp.com"),  # 23
    # Master-list wave, probed live 2026-07-31 (HTTP 200 + non-empty jobs).
    ("aqr", "AQR Capital Management", "aqr.com"),  # 48
    ("bugcrowd", "Bugcrowd", "bugcrowd.com"),  # 17
    ("cloudsek", "CloudSEK", "cloudsek.com"),  # 26
    ("dataiku", "Dataiku", "dataiku.com"),  # 20
    ("devrev", "DevRev", "devrev.ai"),  # 42
    ("fastly", "Fastly", "fastly.com"),  # 53
    ("flowtraders", "Flow Traders", "flowtraders.com"),  # 38
    ("hackerrank", "HackerRank", "hackerrank.com"),  # 33
    ("highradius", "HighRadius", "highradius.com"),  # 64
    ("imc", "IMC Trading", "imc.com"),  # 149
    ("inmobi", "InMobi", "inmobi.com"),  # 70
    ("janestreet", "Jane Street", "janestreet.com"),  # 219
    ("jetbrains", "JetBrains", "jetbrains.com"),  # 95
    ("jumptrading", "Jump Trading", "jumptrading.com"),  # 100
    ("netlify", "Netlify", "netlify.com"),  # 5
    ("netradyne", "Netradyne", "netradyne.com"),  # 27
    ("netskope", "Netskope", "netskope.com"),  # 131
    ("newrelic", "New Relic", "newrelic.com"),  # 51
    ("observeai", "Observe.AI", "observe.ai"),  # 18
    ("recordedfuture", "Recorded Future", "recordedfuture.com"),  # 39
    ("sigmoid", "Sigmoid", "sigmoid.com"),  # 44
    ("synack", "Synack", "synack.com"),  # 8
    ("thoughtworks", "Thoughtworks", "thoughtworks.com"),  # 55
    ("zenoti", "Zenoti", "zenoti.com"),  # 36
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
    # Lever expansion, probed live 2026-07-25 against api.lever.co (real JSON
    # postings list; bogus-token control returns an error object). Counts at
    # probe time: includedhealth 144, ro 51, anchorage 46, kavak 4, ledger 1.
    ("includedhealth", "Included Health", "includedhealth.com"),
    ("ro", "Ro", "ro.co"),
    ("anchorage", "Anchorage Digital", "anchoragedigital.com"),
    ("kavak", "Kavak", "kavak.com"),
    ("ledger", "Ledger", "ledger.com"),
    # Master-list wave, probed live 2026-07-31 (HTTP 200 + non-empty jobs).
    ("porter", "Porter", "porter.in"),  # 27
    ("sophos", "Sophos", "sophos.com"),  # 110
]

# Held out (verified live 2026-07-25 but excluded on purpose):
#  - gopuff (Gopuff, ~836 jobs): overwhelmingly hourly warehouse/driver/ops
#    roles, which would dilute a student/early-career feed - same quality bar
#    that removed wealthindia and held out Bosch/DeliveryHero.
#  - paytm (Paytm, ~230 jobs): a "Paytm" company already exists in prod
#    (slug paytm-2b1da9c8, no ATS, aggregator-created). Seeding a fresh
#    "paytm" slug here would DUPLICATE it, since this script keys idempotency
#    on Company.slug == board_token.lower(). ATTACHED 2026-07-25 via a targeted
#    UPDATE on the existing row instead (paytm-2b1da9c8 -> ats_type='lever',
#    ats_board_id='paytm', domain='paytm.com'), so the crawler ingests its 230
#    jobs onto that row. Kept OUT of this list on purpose so a full reseed
#    can't recreate the duplicate; the attachment lives only in prod data.
#  - justworks (Greenhouse, ~96 jobs): a "Justworks" company already exists in
#    prod (slug justworks-30b301fc, no ATS, aggregator-created). Seeding a fresh
#    "justworks" slug would DUPLICATE it, since this script keys idempotency on
#    Company.slug == board_token.lower(). The architect attaches its board to
#    the existing row via a targeted prod UPDATE instead
#    (ats_type='greenhouse', ats_board_id='justworks') - kept OUT of this list
#    so a reseed can't recreate the dup.
#  - worldquant (Greenhouse, 102 jobs): a "WorldQuant" company already exists
#    in prod (slug worldquant-d1dd59cb, no ATS, aggregator-created). Seeding a
#    fresh "worldquant" slug would DUPLICATE it because this script keys
#    idempotency on Company.slug == board_token.lower(). The architect attaches
#    its board to the existing row via a targeted prod UPDATE instead; kept OUT
#    of GREENHOUSE_COMPANIES so a reseed cannot recreate the duplicate.

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
    # Lever A wave 2, probed live 2026-07-24.
    ("cartesia", "Cartesia", "cartesia.ai"),
    ("krea", "Krea", "krea.ai"),
    ("ideogram", "Ideogram", "ideogram.ai"),
    ("tavus", "Tavus", "tavus.io"),
    ("synthesia", "Synthesia", "synthesia.io"),
    ("gamma", "Gamma", "gamma.app"),
    ("granola", "Granola", "granola.ai"),
    # GH/Ashby wave, probed live 2026-07-25 (real jobs array; bogus tokens
    # error out).
    ("cerebras", "Cerebras", "cerebras.ai"),  # 115
    ("wayve", "Wayve", "wayve.ai"),  # 116
    ("stytch", "Stytch", "stytch.com"),  # 5
    ("workos", "WorkOS", "workos.com"),  # 24
    ("e2b", "E2B", "e2b.dev"),  # 15
    ("hyperbolic", "Hyperbolic", "hyperbolic.xyz"),  # 12
    ("etched", "Etched", "etched.com"),  # 102
    ("physicalintelligence", "Physical Intelligence", None),  # 24
    ("1x", "1X", "1x.tech"),  # 65
    # Master-list wave, probed live 2026-07-31 (HTTP 200 + non-empty jobs).
    ("atlan", "Atlan", "atlan.com"),  # 5
    ("confluent", "Confluent", "confluent.io"),  # 33
    ("docker", "Docker", "docker.com"),  # 58
    ("hackerone", "HackerOne", "hackerone.com"),  # 25
    ("navi", "Navi", "navi.com"),  # 7
    ("redis", "Redis", "redis.io"),  # 27
    ("render", "Render", "render.com"),  # 34
    ("sarvam", "Sarvam AI", "sarvam.ai"),  # 63
    ("sentry", "Sentry", "sentry.io"),  # 47
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

# Held out to bound crawl duration (a single board over ~280 listings cannot
# finish inside the crawl's ATS step budget; the crawl ingests ~40 new
# listings/min, and veeva (831) caused the 2026-07-26 crawl failure):
# BoschGroup (4667), DeliveryHero (1110), veeva (Veeva Systems, 831),
# waymo (Waymo, 404), snowflake (Ashby, 411), crusoe (Crusoe, 359),
# okta (Greenhouse, 346), zscaler (Greenhouse, 310), canonical
# (Greenhouse, 303). Re-add once async/lazy detail fetch lands so a big board
# no longer blocks the single-run budget.

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
    "arbeitnow": ("arbeitnow", "Arbeitnow", "https://www.arbeitnow.com"),
    "devfolio": ("devfolio", "Devfolio", "https://devfolio.co"),
    "devpost": ("devpost", "Devpost", "https://devpost.com"),
    "hackerearth": ("hackerearth", "HackerEarth", "https://www.hackerearth.com"),
    "himalayas": ("himalayas", "Himalayas", "https://himalayas.app"),
    "jobicy": ("jobicy", "Jobicy", "https://jobicy.com"),
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
