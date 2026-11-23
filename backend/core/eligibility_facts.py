"""Evidence-only eligibility facts. A missing dimension means not stated.

Only the listing's title, description and source eligibility tags are read.
Company, category, location, country, AI and network signals never take part:
an internship is not assumed to want undergraduates, and a US location is not
read as a citizenship rule.
"""

import re
from html import unescape
from typing import Literal

ELIGIBILITY_FACTS_VERSION = 1
Stage = Literal["school", "undergraduate", "postgraduate", "doctoral", "recent_graduate"]
STAGES = frozenset({"school", "undergraduate", "postgraduate", "doctoral", "recent_graduate"})
SCAN_LIMIT = 60_000

_YEARS = r"20\d{2}(?:\s*(?:/|,|&|\band\b|\bor\b)\s*20\d{2})*"
_BATCH_PATTERNS = (
    re.compile(rf"\b(?P<years>{_YEARS})\s+(?:batches|batch|pass[ -]?outs?|graduates?)\b", re.I),
    re.compile(
        rf"\b(?:graduating\s+in|graduation\s+years?\s*:?|batch(?:es)?\s+of|class\s+of)"
        rf"\s+(?P<years>{_YEARS})\b",
        re.I,
    ),
)
_QUALIFIER = re.compile(
    r"\b(?:not|except|excluding|other than|ineligible|preferred|preferably|before|after|since)\b",
    re.I,
)


def graduation_batches(text: str) -> list[int]:
    """Only explicit full-year batch/graduate phrases; never event dates or ranges.

    Unsupported ranges and qualified/negative phrases stay unknown rather than
    silently becoming an exhaustive set or a positive eligibility claim.
    """
    text = unescape(re.sub(r"<[^>]*>", " ", text))
    years: set[int] = set()
    for pattern in _BATCH_PATTERNS:
        for match in pattern.finditer(text):
            before = text[max(0, match.start() - 45) : match.start()]
            after = text[match.end() : match.end() + 35]
            if (
                _QUALIFIER.search(before)
                or re.match(
                    r"\s*(?:are\s+)?(?:not|ineligible|excluded|preferred|onwards?|onward|or later|"
                    r"or earlier|and later|and earlier)\b",
                    after,
                    re.I,
                )
                or re.search(r"20\d{2}\s*[-–/]\s*$", before)
                or re.match(r"\s*[-–/]\s*\d", after)
            ):
                continue
            years.update(int(year) for year in re.findall(r"20\d{2}", match["years"]))
    return sorted(years)


# ---------------------------------------------------------------------------
# Listing facts. Each rule reads one clause (a line or sentence) at a time and
# only from the listing's own title, description and source eligibility tags.
# A dimension's value is the union of every requirement clause that states it;
# the evidence is the first such clause, quoted exactly.
# ---------------------------------------------------------------------------

# A clause that is only a preference, a negation or an alternative to
# experience is not a requirement. Parenthesised preferences are dropped first
# so "Bachelor's degree in X (advanced degree preferred)" still counts.
_PREFERENCE = re.compile(
    r"\b(?:preferred|preferably|a plus|nice[ -]to[ -]have|ideally|bonus|desirable|desired|"
    r"not required|is welcome but)\b",
    re.I,
)
_NEGATION = re.compile(r"\b(?:not|ineligible|except|excluding|other than|cannot apply)\b", re.I)
_OR_EXPERIENCE = re.compile(
    r"\bor\s+(?:[\w-]+\s+){0,2}?(?:an?\s+)?(?:equivalent|relevant|commensurate|comparable)\s+"
    r"(?:[\w-]+\s+){0,4}?(?:experience|background)\b|\bor\s+(?:real\s+)?hands-on\b|\(or equivalent\)",
    re.I,
)
_BARE_EQUIVALENT = re.compile(r"\bor\s+(?:an?\s+)?equivalent\s*(?:[.;)]|$)", re.I)
_PAREN_PREFERENCE = re.compile(
    r"\([^()]*\b(?:preferred|a plus|nice to have|desirable)\b[^()]*\)", re.I
)

_SEASON = r"(?:(?:spring|summer|fall|autumn|winter|jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\s+)?"
_GRAD_RANGE = re.compile(
    rf"\b(?:graduat(?:e|es|ing|ion)(?:\s+date)?|degree)\b[^.;\n]{{0,40}}?\bbetween\s+{_SEASON}(20\d\d)\s+"
    rf"(?:and|to|-|–|through)\s+{_SEASON}(20\d\d)\b",
    re.I,
)
_GRAD_SINGLE = (
    re.compile(rf"\bgraduating\s+(?:in\s+)?{_SEASON}(20\d\d)\b", re.I),
    re.compile(
        rf"\b(?:expected\s+)?graduation(?:\s+date)?\s*(?:of|in|:|-)?\s*{_SEASON}(20\d\d)\b", re.I
    ),
    re.compile(rf"\b{_SEASON}(20\d\d)\s+graduation\b", re.I),
    re.compile(r"\bgraduated\s+(?:from\s+(?:college|university)\s+)?in\s+(20\d\d)\b", re.I),
)
_YEAR_RANGE_BATCH = re.compile(
    r"\b(20\d\d)\s*[-–]\s*(20\d\d)\s+(?:batches|batch|pass[ -]?outs?|graduates?)\b", re.I
)

_UG = (
    r"(?:bachelor(?:['’]s|s)?|undergraduate|baccalaureate|b\.?\s?tech|b\.?\s?sc|"
    r"(?-i:BS|B\.S\.|BA|B\.A\.|BE|B\.E\.|UG))"
)
_PG = (
    r"(?:master(?:['’]s|s)?|postgraduate|post[- ]graduate|graduate|m\.?\s?tech|m\.?\s?sc|mba|"
    r"(?-i:MS|M\.S\.|MA|M\.A\.|PG))"
)
_PHD = r"(?:ph\.?\s?d\.?|doctoral|doctorate|doctor\s+of\s+philosophy)"
_LEVEL = rf"(?:{_PHD}|{_UG}|{_PG}|advanced)"
_LEVEL_ITEM = rf"{_LEVEL}(?:['’]s)?(?:\s+(?:degree|program(?:me)?|studies))?"
_LEVEL_CHAIN = rf"{_LEVEL_ITEM}(?:\s*(?:,|/|&|\band\b|\bor\b)\s*(?:an?\s+)?{_LEVEL_ITEM})*"
_PURSUING = re.compile(
    rf"\b(?:currently\s+)?(?:pursuing|pursing|enrolled|enrollment|enrolment|studying|working\s+towards?)"
    rf"(?:\s+or\s+(?:recently|have)\s+(?:completed|completing|graduated)(?:\s+from)?)?"
    rf"(?:\s+(?:in|for|towards|at))?(?:\s+(?:an?|the))?(?:\s+(?:full[- ]time|accredited|4-year|four-year))*\s+"
    rf"(?P<levels>{_LEVEL_CHAIN})(?:['’]s)?\s*(?:degree|program(?:me)?|studies|course)?",
    re.I,
)
_LEVEL_STUDENTS = re.compile(
    rf"\b(?P<levels>{_LEVEL_CHAIN}|undergraduates|postgraduates|masters)"
    rf"(?:\s*(?:,|/|&|\band\b|\bor\b)\s*(?:{_LEVEL_CHAIN}|undergraduates|postgraduates|masters))*"
    rf"(?:\s+[a-z]+){{0,2}}?\s+(?:students?|candidates?)\b",
    re.I,
)
_YEAR_STANDING = re.compile(
    r"\brising\s+(?:junior|senior|sophomore)s?\b|"
    r"\b(?:juniors|seniors|sophomores)\s*(?:,|\bor\b|\band\b)\s*(?:rising\s+)?(?:juniors|seniors|sophomores|graduate)\b|"
    r"\b(?:junior|senior|sophomore)\s+(?:or\s+(?:junior|senior)\s+)?year\b",
    re.I,
)
_INDIAN_GRADUATION = (
    (
        re.compile(
            r"\bpost[- ]?graduat(?:e|ion)\s+pursuing\b|\bpursuing\s+post[- ]?graduat(?:e|ion)\b",
            re.I,
        ),
        "postgraduate",
    ),
    (
        re.compile(
            r"(?<!post )(?<!post-)\b(?:any\s+)?graduat(?:e|ion)\s+pursuing\b|\bpursuing\s+(?:the\s+final\s+year\s+of\s+)?graduation\b",
            re.I,
        ),
        "undergraduate",
    ),
)
_GERMAN = re.compile(
    r"\b(?:im\s+)?(?:fortgeschrittenen\s+)?Bachelor\s+oder\s+(?:im\s+)?Master\b|\bBachelor-\s*oder\s+Masterstudium\b"
)
_SCHOOL = re.compile(
    r"(?<!engineering )(?<!business )(?<!law )(?<!medical )(?<!graduate )(?<!grad )"
    r"\b(?:high[- ]school|secondary[- ]school|school)\s+students?\b|\bclass(?:es)?\s+(?:9|10|11|12)(?:\s*(?:-|–|to)\s*12)?\b",
    re.I,
)
_RECENT = (
    re.compile(
        r"\b(?:seeking|looking for|hiring|for|open to|designed for)\s+(?:an?\s+)?(?:new|recent|fresh)\s+grad(?:uate)?s?\b",
        re.I,
    ),
    re.compile(
        r"\bgraduated\s+within\s+the\s+(?:last|past)\b|\bcompleted\s+(?:their\s+|the\s+)?(?:studies|degree|post[- ]?graduation|graduation)\s+within\s+the\s+(?:last|past)\b",
        re.I,
    ),
    re.compile(r"\bwithin\s+(?:1|one|12 months|a year)\s+(?:year\s+)?of\s+graduation\b", re.I),
    re.compile(r"\bgraduated\s+(?:from\s+(?:college|university)\s+)?in\s+20\d\d\b", re.I),
)
_FRESHERS = re.compile(r"\bfreshers?\b", re.I)
_INCLUSIVE_AUDIENCE = re.compile(
    r"\b(?:students?|experience[ds]?|professionals?|anyone|everyone|individuals|career[- ]changers?|early[- ]career)\b",
    re.I,
)
_EXPERIENCE_WELCOME = re.compile(
    r"\bfreshers?\b[^.\n]{0,60}\b(?:experienced|candidates?\s+with\s+(?:up\s+to\s+)?(?:\d|relevant|prior|some)|"
    r"\d+\s*(?:-|–|to)\s*\d+\s+years?|experience\s+(?:in\s+[\w ,]+\s+)?is\s+preferred)|"
    r"\bexperienced\b[^.;\n]{0,40}\bfreshers?\b|\bfresher\s*/\s*0\s*(?:-|–|to)\s*\d|"
    r"\bexperienced\s+(?:graduates|candidates|applicants|professionals)\b",
    re.I,
)
_TITLE_NEW_GRAD = re.compile(r"\bnew[ -]grad(?:uate)?s?\b", re.I)
_TITLE_INTERN = re.compile(
    r"\b(?:intern(?:ship)?|co-?op|praktikum|werkstudent|working student)\b", re.I
)
_TITLE_PHD = re.compile(r"\bph\.?\s?d\b", re.I)
_FINAL_YEAR = re.compile(r"\bfinal[- ]year\b(?:\s+[\w'’.-]+){0,4}?\s+students?\b", re.I)
_MASTERS_LEVEL = re.compile(
    r"\bmaster(?:['’]s|s)?\s+level\b|\bfinal[- ]year\s+master(?:['’]s|s)?\b", re.I
)
_DEGREE_LEVELS = (
    (
        "bachelor",
        r"(?:bachelor(?:['’]s|s)?|b\.?\s?tech|b\.?\s?sc|(?-i:BS|B\.S\.|BA|B\.A\.|BE|B\.E\.))",
    ),
    ("master", r"(?:master(?:['’]s|s)?|m\.?\s?tech|m\.?\s?sc|mba|(?-i:MS|M\.S\.))"),
    ("doctorate", _PHD),
    ("diploma", r"diploma"),
)
_DEGREE_ANY = rf"(?:{_DEGREE_LEVELS[0][1]}|{_DEGREE_LEVELS[1][1]}|{_PHD}|diploma)"
_DEGREE_REQ = re.compile(
    rf"^(?:[-*•·]\s*)?(?:(?P<edu>education(?:al)?(?:\s+qualifications?)?\s*:\s*)|[\w ]{{2,30}}:\s*)?"
    rf"(?:completed\s+(?:an?\s+)?|(?:must\s+(?:have|hold)|requires?|required:?|minimum:?|hold)\s+(?:an?\s+)?)?"
    rf"(?P<degrees>{_DEGREE_ANY}(?:['’]s)?(?:\s*(?:,|/|&|\bor\b|\band\b)\s*{_DEGREE_ANY}(?:['’]s)?)*)"
    rf"(?P<tail>(?:\s*/\s*college)?\s*(?:degree|program(?:me)?)(?:\s+or\s+higher)?|\s+(?:in|from)\b|"
    rf"\s+(?:is\s+)?required\b)?",
    re.I,
)
_STUDYING_WORDS = re.compile(
    r"\b(?:pursuing|pursing|enrolled|enrollment|studying|working towards?|progress towards?|students?)\b",
    re.I,
)
_COUNTRIES = {
    "US": (
        "us",
        "u.s.",
        "u.s",
        "usa",
        "u.s.a.",
        "united states",
        "united states of america",
        "american",
    ),
    "IN": ("india", "indian"),
    "GB": ("uk", "u.k.", "united kingdom", "british"),
    "CA": ("canada", "canadian"),
    "AU": ("australia", "australian"),
    "DE": ("germany", "german"),
    "SG": ("singapore", "singaporean"),
    "FR": ("france", "french"),
    "NZ": ("new zealand", "new zealander"),
    "IE": ("ireland", "irish"),
    "JP": ("japan", "japanese"),
    "CN": ("china", "chinese"),
    "NL": ("netherlands", "dutch"),
    "PK": ("pakistan", "pakistani"),
    "BD": ("bangladesh", "bangladeshi"),
    "AE": ("uae", "united arab emirates", "emirati"),
    "ZA": ("south africa", "south african"),
    "PH": ("philippines", "filipino", "philippine"),
}
_CITIZEN = re.compile(
    r"\bmust\s+be\s+(?:an?\s+)?(?P<must>[a-z .]{2,40}?)\s+citizens?\b|"
    r"\b(?P<only>[a-z .]{2,40}?)\s+citizens?\s+only\b|"
    r"\bopen\s+(?:only\s+)?to\s+(?P<nationals>[a-z .]{2,40}?)\s+(?:citizens|nationals)\b|"
    r"\bcitizenship\s+(?:is\s+)?required\b",
    re.I,
)
_CITIZEN_ALTERNATIVES = re.compile(
    r"permanent\s+resident|green\s+card|protected\s+individual|asylee|refugee|u\.?s\.?\s+person|"
    r"eligible\s+to\s+obtain|conditional\s+resident|work\s+authori[sz]ation|authori[sz]ed\s+to\s+work",
    re.I,
)
_CLEARANCE_CITIZEN = re.compile(
    r"\bcitizen(?:ship)?\b[^.;\n]{0,60}\b(?:dod|ts/sci|top\s+secret|secret)\b[^.;\n]{0,20}\bclearance\b",
    re.I,
)
_COLLEGE = re.compile(
    r"\bonly\s+(?:open\s+to|for)\s+students\s+(?:of|from)\s+(?P<a>[^;\n]{2,100})|"
    r"\bexclusively\s+for\s+(?P<b>[^;\n]{2,100}?)\s+students\b|"
    r"\bstudents\s+of\s+(?P<c>[^;\n]{2,100}?)\s+only\b|"
    r"\bon-campus\s+drive\s+for\s+(?P<d>[^;\n]{2,100})|"
    r"\bstudents?\s+at\s+(?P<e>(?-i:[A-Z][A-Za-z.&'-]+)(?:\s+(?-i:[A-Z][A-Za-z.&'-]+)){0,5})",
    re.I,
)
_GENERIC_INSTITUTION = re.compile(
    r"\b(?:any|all|every|participating|eligible|selected|accredited|recognized|recognised|top|leading|"
    r"reputed|various|different|other)\b",
    re.I,
)
_TAG_STAGES = {
    "undergraduate": "undergraduate",
    "postgraduate": "postgraduate",
    "mba students": "postgraduate",
    "school students": "school",
    "fresher": "recent_graduate",
}


_PREF_HEADING = re.compile(
    r"^\W*(?:preferred|desired|desirable|nice[ -]to[ -]haves?|good[ -]to[ -]have|bonus(?:\s+points)?|"
    r"optional|pluses|extra\s+credit)\b[\w &/'’()-]{0,40}:?\W*$",
    re.I,
)
_HEADING = re.compile(
    r"^\W*[\w &/'’()-]{2,60}:\W*$|^\s*#{1,6}\s|"
    r"^\W*(?:(?:minimum|basic|required|essential|key|must[ -]have)\s+)?"
    r"(?:qualifications|requirements|eligibility(?:\s+criteria)?|education|who\s+can\s+apply|"
    r"about\s+(?:you|the\s+role|us)|benefits|responsibilities|what\s+you(?:'ll|’ll|\s+will)\s+do)\W*$",
    re.I,
)


def _preference_sections(text: str) -> list[tuple[int, int]]:
    ranges, start = [], None
    for line in re.finditer(r"[^\n]+", text):
        if _PREF_HEADING.match(line.group()):
            if start is None:
                start = line.start()
        elif start is not None and _HEADING.match(line.group()):
            ranges.append((start, line.start()))
            start = None
    if start is not None:
        ranges.append((start, len(text)))
    return ranges


def _plain(text: str | None) -> str:
    raw = (text or "")[:SCAN_LIMIT]
    raw = re.sub(r"<(script|style)\b[^>]*>.*?</\1\s*>", " ", raw, flags=re.I | re.S)
    raw = re.sub(r"</?(?:p|div|li|br|h[1-6]|tr|ul|ol)\b[^>]*>", "\n", raw, flags=re.I)
    return unescape(re.sub(r"<[^>]*>", " ", raw))[:SCAN_LIMIT]


def _clauses(text: str):
    """Yield (start, clause): each line, split at semicolons and sentence ends."""
    for line in re.finditer(r"[^\n;]+", text):
        for sentence in re.finditer(r".+?(?:(?<=[a-z0-9)])[.!?](?=\s+[A-Z0-9])|$)", line.group()):
            clause = sentence.group()
            if clause.strip():
                yield line.start() + sentence.start(), clause


def _levels(chain: str) -> set[str]:
    found = set()
    for token in re.findall(
        rf"{_PHD}|{_UG}|{_PG}|advanced|undergraduates|postgraduates|masters", chain, re.I
    ):
        low = token.casefold().replace(".", "").replace(" ", "")
        if re.fullmatch(r"phd|doctoral|doctorate|doctorofphilosophy", low):
            found.add("doctoral")
        elif low == "advanced":
            found.update({"postgraduate", "doctoral"})
        elif re.fullmatch(
            r"bachelor('s|’s|s)?|undergraduates?|baccalaureate|btech|bsc|bs|ba|be|ug", low
        ):
            found.add("undergraduate")
        else:
            found.add("postgraduate")
    return found


def _country_codes(phrase: str) -> list[str]:
    """ISO codes for every named country, or [] when any part is unmapped."""
    codes = []
    for part in re.split(r"\s*(?:,|/|&|\band\b|\bor\b)\s*", phrase.casefold().strip()):
        part = re.sub(r"^(?:an?|the)\s+", "", part.strip())
        code = next((code for code, names in _COUNTRIES.items() if part in names), None)
        if code is None:
            return []
        codes.append(code)
    return sorted(set(codes))


def _snippet(text: str, start: int, end: int) -> tuple[int, int]:
    """Trim a clause to at most 160 characters."""
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    return start, min(end, start + 160)


def _stage_rules(clause: str) -> set[str]:
    stages: set[str] = set()
    for match in _PURSUING.finditer(clause):
        stages |= _levels(match.group("levels"))
        if re.search(
            r"\bor\s+(?:recently|have)\s+(?:completed|completing|graduated)", match.group(), re.I
        ):
            stages.add("recent_graduate")
    for match in _LEVEL_STUDENTS.finditer(clause):
        stages |= _levels(match.group())
    if _YEAR_STANDING.search(clause):
        stages.add("undergraduate")
    if _MASTERS_LEVEL.search(clause):
        stages.add("postgraduate")
    for pattern, stage in _INDIAN_GRADUATION:
        if pattern.search(clause):
            stages.add(stage)
    if _GERMAN.search(clause):
        stages |= {"undergraduate", "postgraduate"}
    if _SCHOOL.search(clause):
        stages.add("school")
    if not _INCLUSIVE_AUDIENCE.search(clause):
        short = len(clause.split()) <= 5
        if (
            any(p.search(clause) for p in _RECENT)
            or _FRESHERS.search(clause)
            or (short and re.search(r"\brecent\s+grad(?:uate)?s?\b", clause, re.I))
        ):
            stages.add("recent_graduate")
    elif any(p.search(clause) for p in _RECENT[1:]) and not re.search(
        r"\bstudents?\b", clause, re.I
    ):
        stages.add("recent_graduate")
    if (
        "doctoral" in stages
        and "postgraduate" in stages
        and not re.search(
            r"\b(?:advanced|master(?:['’]s|s)?|postgraduate|post[- ]graduate|m\.?\s?tech|m\.?\s?sc|mba|(?-i:MS|M\.S\.|MA|PG))\b",
            clause,
            re.I,
        )
    ):
        stages.discard("postgraduate")
    return stages


def _grad_years(clause: str) -> set[int]:
    years: set[int] = set(graduation_batches(clause))
    for pattern in (_GRAD_RANGE, _YEAR_RANGE_BATCH):
        for match in pattern.finditer(clause):
            lo, hi = int(match.group(1)), int(match.group(2))
            if 2015 <= lo <= hi <= 2035 and hi - lo <= 4:
                years.update(range(lo, hi + 1))
    for pattern in _GRAD_SINGLE:
        years.update(int(m.group(1)) for m in pattern.finditer(clause))
    return {y for y in years if 2015 <= y <= 2035}


def _experience_welcome(text: str) -> bool:
    """True when freshers AND experienced applicants are both invited."""
    for line in re.finditer(r"[^\n]+", text):
        if _EXPERIENCE_WELCOME.search(line.group()) and not re.search(
            r"\bno\s+(?:prior\s+|previous\s+)?experience\b", line.group(), re.I
        ):
            return True
    return False


def extract_eligibility_facts(
    title: str | None, description_raw: str | None, meta: dict | None
) -> dict:
    """Listing requirements with an exact quote; a missing key means not stated."""
    tags = meta.get("eligibility") if isinstance(meta, dict) else None
    tag_list = [t[:160] for t in tags[:200] if isinstance(t, str)] if isinstance(tags, list) else []
    sources = {
        "title": _plain(title),
        "description": _plain(description_raw),
        "tags": "\n".join(tag_list),
    }
    found: dict[str, dict[str, list]] = {}
    experience_welcome = _experience_welcome(sources["description"])

    def add(key: str, values, source: str, start: int, end: int) -> None:
        start, end = _snippet(sources[source], start, end)
        found.setdefault(key, {}).setdefault(source, []).append((values, start, end))

    title_stages: list[tuple[set[str], int, int]] = []
    for source in ("description", "title"):
        text = sources[source]
        preference_sections = _preference_sections(text) if source == "description" else []
        # "Bachelor's in X; or relevant experience" spans a semicolon: judge the whole line.
        or_experience_lines = [
            (m.start(), m.end())
            for m in re.finditer(r"[^\n]+", text)
            if _OR_EXPERIENCE.search(m.group())
        ]
        for offset, raw_clause in _clauses(text):
            if any(lo <= offset < hi for lo, hi in preference_sections):
                continue
            end = offset + len(raw_clause)
            clause = _PAREN_PREFERENCE.sub(lambda m: " " * len(m.group()), raw_clause)
            if _PREFERENCE.search(clause) or _NEGATION.search(clause):
                continue
            or_experience = bool(_OR_EXPERIENCE.search(clause)) or any(
                lo <= offset < hi for lo, hi in or_experience_lines
            )

            years = _grad_years(clause)
            if years:
                add("grad_years", sorted(years), source, offset, end)

            if not or_experience:
                stages = _stage_rules(clause)
                if stages and source == "description":
                    add("stages", sorted(stages), source, offset, end)
                elif stages:
                    title_stages.append((stages, offset, end))

            if _FINAL_YEAR.search(clause) and not re.search(
                r"\b(?:graduates?|experience|or\s+recent)\b", clause, re.I
            ):
                add("final_year_only", True, source, offset, end)

            bare = re.sub(r"\([^()]*\)", " ", clause).strip()
            if not or_experience and not _STUDYING_WORDS.search(bare):
                match = None if _BARE_EQUIVALENT.search(clause) else _DEGREE_REQ.search(bare)
                if match and not (match.group("tail") or match.group("edu")):
                    match = None
                if match:
                    levels = {
                        level
                        for level, pattern in _DEGREE_LEVELS
                        if re.search(rf"(?<![\w.]){pattern}(?![\w])", match.group("degrees"), re.I)
                    }
                    if levels:
                        add("degree_levels", sorted(levels), source, offset, end)

            for match in _COLLEGE.finditer(clause):
                institution = next(v for v in match.groups() if v)
                if not _GENERIC_INSTITUTION.search(institution) and re.search(
                    r"\b[A-Z][\w.&-]+", institution
                ):
                    add("college_restriction", True, source, offset, end)

            if not _CITIZEN_ALTERNATIVES.search(clause):
                for match in _CITIZEN.finditer(clause):
                    phrase = next((v for v in match.groups() if v), "")
                    add(
                        "citizenship", _country_codes(phrase) if phrase else [], source, offset, end
                    )
                if _CLEARANCE_CITIZEN.search(clause):
                    add("citizenship", ["US"], source, offset, end)

    # The title is a fallback for stages only: a description that states the
    # stage is more specific than a title tag such as "(New Grad)".
    if "stages" not in found:
        title_text = sources["title"]
        stages = set().union(*(s for s, _, _ in title_stages)) if title_stages else set()
        if _TITLE_NEW_GRAD.search(title_text) and not _TITLE_INTERN.search(title_text):
            stages.add("recent_graduate")
        if _TITLE_PHD.search(title_text) and _TITLE_INTERN.search(title_text):
            stages.add("doctoral")
        if _TITLE_INTERN.search(title_text):
            stages.discard("recent_graduate")
        if stages:
            add("stages", sorted(stages), "title", 0, len(title_text))

    # Source tags are the weakest stage evidence: used only when the text says
    # nothing, and never when experienced applicants are also invited.
    if "stages" not in found and tag_list:
        tag_set = {t.strip().casefold() for t in tag_list}
        stages = {_TAG_STAGES[t] for t in tag_set if t in _TAG_STAGES}
        if "experienced professionals" in tag_set or experience_welcome:
            stages = set()
        position = 0
        for tag in tag_list:
            if stages and _TAG_STAGES.get(tag.strip().casefold()) in stages:
                add("stages", sorted(stages), "tags", position, position + len(tag))
                break
            position += len(tag) + 1
    elif experience_welcome and "stages" in found:
        # "Freshers and candidates with experience" removes only the fresher claim.
        for source, rows in list(found["stages"].items()):
            kept = [(sorted(set(v) - {"recent_graduate"}), s, e) for v, s, e in rows]
            kept = [row for row in kept if row[0]]
            if kept:
                found["stages"][source] = kept
            else:
                del found["stages"][source]
        if not found["stages"]:
            del found["stages"]

    position = 0
    for tag in tag_list:
        if re.fullmatch(r"\s*(?:[a-z]{2} )?citizens only\s*", tag, re.I):
            phrase = tag.strip()[: -len("citizens only")].strip()
            add(
                "citizenship",
                _country_codes(phrase) if phrase else [],
                "tags",
                position,
                position + len(tag),
            )
        position += len(tag) + 1

    result: dict = {"v": ELIGIBILITY_FACTS_VERSION}
    for key, by_source in found.items():
        rows = [
            (source, row)
            for source in ("description", "title", "tags")
            for row in by_source.get(source, [])
        ]
        if not rows:
            continue
        source, (_, start, end) = rows[0]
        if key in ("final_year_only", "college_restriction"):
            merged = True
        else:
            merged = sorted({item for _, (items, _, _) in rows for item in items})
        result[key] = {"value": merged, "evidence": sources[source][start:end], "source": source}
    return result
