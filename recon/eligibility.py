"""Reads the job description: years of experience + hard eligibility gates.

Gates are hard stops (a great match can't outweigh "US citizens only").
Every skip keeps its reason so nothing disappears silently.
"""
import re

MAX_YEARS = 4  # drop jobs whose minimum ask is above this

# "3+ years", "3-5 years", "3 to 5 years", "five years" ... followed by experience-ish words
NUM_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
             "seven": 7, "eight": 8, "nine": 9, "ten": 10}
YEARS = re.compile(
    r"\b(\d{1,2}|one|two|three|four|five|six|seven|eight|nine|ten)(?:\s*\(\d{1,2}\+?\))?\s*\+?\s*"   # "two (2) years"
    r"(?:(?:-|–|to)\s*(?:\d{1,2}|one|two|three|four|five|six|seven|eight|nine|ten)\s*\+?\s*)?(?:years?|yrs?)\b"   # "three to five years": 3
    r"(?=[^.]{0,80}\b(experience|industry|professional|engineering|software|building|developing|working)"
    r"|\s+in\s+an?\s+[^.]{0,40}?\b(role|position)\b)",   # F5: "8+ years in a Post-Sales technical role"
    re.I,
)

BLOCKERS = {
    "citizenship/clearance": re.compile(
        r"u\.?s\.?\s+citizen(ship)?\s+(is\s+)?required|must\s+be\s+(a\s+)?(u\.?s\.?|united\s+states)\s+citizen|"
        # Workday Federal: "mandates that all Workday personnel ... be United States citizens (naturalized or native)"
        r"mandates?\s+(that\s+)?all\b[^.]{0,120}?\bbe\s+(u\.?s\.?|united\s+states)\s+citizens?|"
        r"(u\.?s\.?|united\s+states)\s+citizens?\s*\(\s*naturalized\s+or\s+native|"
        r"(security\s+)?clearance\s+(is\s+)?required|"
        # "Active Top Secret required with ability to obtain SCI Preferred": keep "required" in
        # the match so the later "Preferred" can't make it look soft
        r"active\s+(secret|top\s+secret|ts/sci)(\s+(security\s+)?clearance)?(\s+(is\s+)?required)?|"
        # Microsoft: "must have an active U.S. Government Top Secret Security Clearance"
        r"active\s+(u\.?s\.?\s+)?(government\s+)?(secret|top\s+secret)\s+(security\s+)?clearance|"
        r"top\s+secret\s+(security\s+)?(clearance\s+)?(is\s+)?required|"
        # a few words allowed: "obtain and maintain a U.S. government issued security clearance";
        # with or without "security": EY's "Must be able to obtain and maintain a secret clearance or higher"
        r"(obtain|maintain|hold|possess|eligib\w*\s+(for|to\s+obtain))\b(?:[^.]|\.(?=\S)|(?<=[A-Z])\.){0,60}?\bclearance|"   # "U.S." isn't a sentence end
        r"\b(secret|top\s+secret|public\s+trust|dod|government|federal)\s+(security\s+)?clearance|"
        r"\bpublic\s+trust\b|"
        r"\bitar\b|export\s+control(led)?\s+.{0,40}u\.?s\.?\s+person|"
        r"\bu\.?s\.?\s+person\s+(status\s+)?required|requires\s+\bu\.?s\.?\s+person|"
        r"must\s+be\s+(a\s+)?\bu\.?s\.?\s+person",
        re.I,
    ),
    "no sponsorship": re.compile(
        r"(will\s+not|won't|unable\s+to|not\s+able\s+to|cannot|can\s*not|do(es)?\s+not)\s+"
        r"(provide\s+|offer\s+)?(visa\s+)?sponsor|"
        r"no\s+(visa\s+)?sponsorship|sponsorship\s+(is\s+)?not\s+(available|offered|provided)|"
        r"without\s+(the\s+need\s+for\s+)?(current\s+or\s+future\s+)?(visa\s+|employer\s+)?sponsorship|"
        r"not\s+(accept|eligible\s+for)\s+.{0,20}\b(opt|cpt)\b|"
        r"not\s+eligible\s+for\s+(employment\s+)?(visa\s+)?sponsorship|"          # Genworth
        r"not\s+offering\b[^.]{0,40}?\bsponsorship|"                             # Avride
        r"(does\s+not|doesn't|will\s+not)\s+(now\s+or\s+in\s+the\s+future\s+)?"   # Accenture Federal
        r"require\s+(visa\s+)?sponsorship",
        re.I,
    ),
}


# Citizenship or permanent residency, in any wording: Robinhood's "Position Restriction: This
# position is restricted to US citizens or lawful permanent residents", "green card holders only",
# "US persons only", "must be a U.S. citizen or permanent resident", "requires U.S. citizenship"
_US = r"(?:u\.?\s?s\.?(?:\s?a\.?)?|united\s+states)"
CITIZEN = re.compile(
    rf"restricted\s+to\s+(?:{_US}\s+)?(?:citizens|persons|nationals)|"
    rf"\b(?:{_US}\s+)?citizens?(?:hip)?\s*(?:,|or|and/or|/)\s*(?:a\s+|an\s+)?(?:lawful\s+|legal\s+)?permanent\s+residen(?:ts?|cy)|"
    rf"green\s+card\s+holders?\s+only|only\s+[^.]{{0,40}}green\s+card\s+holders?|citizens?\s+(?:or|and)\s+green\s+card\s+holders?|"
    rf"\b{_US}\s+(?:citizens?|persons?|nationals?)\s+only\b|"
    rf"only\s+(?:open\s+to\s+|available\s+to\s+|consider\s+)?{_US}\s+(?:citizens|persons)|"
    rf"(?:requires?|requiring)\s+(?:{_US}\s+)?citizenship|"
    rf"must\s+(?:be|hold)\s+(?:a\s+)?{_US}\s+(?:citizen|national|person)|"
    rf"must\s+have\s+{_US}\s+citizenship|"
    rf"\b{_US}\s+citizenship\s+(?:is\s+)?(?:required|mandatory)",
    re.I)
# ...unless a visa is an alternative: ALS "must be a Citizen or Permanent Resident of the country you
# are applying for, or either hold or be able to obtain a valid work visa"
VISA_ALTERNATIVE = re.compile(r"[^.]{0,60}?\bor\b[^.]{0,80}\b(visa|work\s+(permit|authori[sz]ation))", re.I)


# ...or it's about another country: Databricks' sanctions question "Citizen or permanent resident of
# Cuba, Iran, North Korea, or Syria"
OTHER_COUNTRY = re.compile(r"\s+of\s+(?!the\s+united\s+states|the\s+u\.?s\b|u\.?s\b|united\s+states|america)", re.I)
_US_WORD = re.compile(_US, re.I)


def citizenship_required(text: str) -> bool:
    return any(not VISA_ALTERNATIVE.match(text, m.end())
               and not (OTHER_COUNTRY.match(text, m.end()) and not _US_WORD.search(m.group(0)))
               for m in CITIZEN.finditer(text))


# TS/SCI in any form ("TS/SCI", "TS-SCI", "Top Secret/SCI") blocks even when "preferred":
# it's only open to U.S. citizens
TS_SCI = re.compile(r"\bts\s*[/-]?\s*sci\b|top\s+secret\s*[/-]\s*sci\b", re.I)

CLEARANCE = re.compile(r"\bclearance\b", re.I)

# Cleared roles named in the title: Microsoft's "Software Engineer II - CTJ - Poly" (Cleared Talent
# Jobs, polygraph), "Site Reliability Engineer - CTJ - Secret", "Software Engineer - Cleared"
CLEARED_TITLE = re.compile(r"\b(ctj|cleared|poly|polygraph|ts\s*/\s*sci|top\s+secret)\b|[-–]\s*secret\b", re.I)

# Soft words: the sentence is a wish, not a requirement
SOFT_CLEARANCE = re.compile(r"beneficial|preferred|a\s+plus|nice\s+to\s+have|not\s+necessary", re.I)
SOFT_YEARS = re.compile(r"preferred|nice\s+to\s+have|bonus|a\s+plus", re.I)
# A list in parentheses is an aside: "3 years ... languages (Java, Python, ... Informatica preferred)"
# is still a minimum (Highmark). "5+ years (preferred)" stays soft.
ASIDE_LIST = re.compile(r"\([^()]*,[^()]*\)")
# "without sponsorship for an export license" is export law, not visas (Cloudflare boilerplate)
EXPORT_LICENSE = re.compile(r"\s*for\s+an?\s+export\s+licen[cs]e", re.I)

END = re.compile(r"[.!?\n]")
# Bullet lists often lose their periods, so cap the "sentence". Look back only a little
# ("Preferred: 5+ years") so a "(preferred)" in the previous bullet doesn't leak in.
BACK, AHEAD = 40, 150


def sentence(text: str, m: re.Match) -> str:
    """The sentence around a match (capped at BACK / AHEAD chars)."""
    lo = max(m.start() - BACK, 0)
    hi = min(m.end() + AHEAD, len(text))
    before = [e.end() for e in END.finditer(text, lo, m.start())]
    after = END.search(text, m.end(), hi)
    return text[before[-1] if before else lo: after.start() if after else hi]


def is_soft(reason: str, text: str, m: re.Match) -> bool:
    if reason == "no sponsorship":
        return bool(EXPORT_LICENSE.match(text, m.end()))
    if re.search(r"requir|must", m.group(0), re.I):
        return False   # "U.S. Person Required" is hard even if a later bullet says "preferred"
    return bool(SOFT_CLEARANCE.search(sentence(text, m)))


# --- Early-career windows: experience caps, start dates, graduation dates ---
YOU_GRADUATE = (2026, 12)   # (year, month)
EARLIEST_START = (2027, 1)
MIN_CAP_YEARS = 3           # flag caps below this ("no more than 18 months"); you decide

MONTH = (r"jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|"
         r"sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?")
SEASON = r"spring|summer|fall|autumn|winter"
# "December 1, 2026", "Dec 2026", "summer 2026", "January/February 2027"
DATE = rf"(?:{MONTH}|{SEASON})(?:\s*/\s*(?:{MONTH}|{SEASON}))?\.?\s+(?:\d{{1,2}},?\s+)?20\d\d"
SEASONS = {"spring": (3, 5), "summer": (6, 8), "fall": (9, 11), "autumn": (9, 11), "winter": (12, 2)}


def period(s: str) -> tuple[tuple[int, int], tuple[int, int]]:
    """'summer 2026' -> ((2026, 6), (2026, 8)); 'January/February 2027' -> ((2027, 1), (2027, 2))."""
    year = int(re.search(r"20\d\d", s).group(0))
    spans = []
    for w in re.findall(rf"{MONTH}|{SEASON}", s, re.I):
        w = w.lower()
        if w in SEASONS:
            a, b = SEASONS[w]
            spans.append(((year - 1, 12), (year, 2)) if w == "winter" else ((year, a), (year, b)))
        else:
            m = next(i for i, k in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug",
                                              "sep", "oct", "nov", "dec"], 1) if w.startswith(k))
            spans.append(((year, m), (year, m)))
    return spans[0][0], spans[-1][1]


NUM = r"\d{1,2}|" + "|".join(NUM_WORDS)
CAP = re.compile(
    rf"(no\s+more\s+than|not\s+more\s+than|less\s+than|fewer\s+than|at\s+most|up\s+to|maximum\s+of)\s+"
    rf"(?P<n>{NUM})\s+(?P<unit>months?|years?)\b(?P<rest>[^.\n]{{0,40}}?)\bexperience|"
    rf"\b0\s*(?:-|–|to)\s*(?P<n2>\d{{1,2}})\s*\+?\s*(?P<unit2>months?|years?|yrs?)(?:\(s\))?"
    rf"(?P<rest2>[^.\n]{{0,40}}?)\bexperience",
    re.I,
)
START = re.compile(
    rf"\b(start|begin)(s|ing)?\b[^.\n]{{0,40}}?\b(?P<op>before|by|no\s+later\s+than)\s+(?P<d>{DATE})", re.I)
IMMEDIATE = re.compile(r"\bimmediate(ly)?\s+start|start\s+immediately", re.I)
GRAD_BY = re.compile(
    rf"\b(graduat\w*|obtained)\s+(?P<op>before|by|no\s+later\s+than)\s+(?P<d>{DATE})", re.I)
GRAD_BETWEEN = re.compile(rf"\bgraduat\w*\s+between\s+(?P<a>{DATE})\s+and\s+(?P<b>{DATE})", re.I)


def experience_cap(text: str) -> re.Match | None:
    """'no more than 18 months of professional experience' -> match if the cap is under 3 years."""
    for m in CAP.finditer(text or ""):
        n, unit, rest = (m["n"], m["unit"], m["rest"]) if m["n"] else (m["n2"], m["unit2"], m["rest2"])
        if "intern" in rest.lower():
            continue   # caps on internship experience don't apply to full-time history
        n = NUM_WORDS.get(n.lower()) or int(n)
        if (n / 12 if unit.lower().startswith("month") else n) < MIN_CAP_YEARS:
            return m
    return None


def cap_flag(m: re.Match) -> str:
    """'no more than 18 months ...' -> 'exp cap: max 18 mo'; '0-2 years' -> 'exp cap: max 2 yrs'."""
    n, unit = (m["n"], m["unit"]) if m["n"] else (m["n2"], m["unit2"])
    n = NUM_WORDS.get(n.lower()) or int(n)
    return f"exp cap: max {n} {'mo' if unit.lower().startswith('month') else 'yr' if n == 1 else 'yrs'}"


def early_start(text: str) -> re.Match | None:
    """'must start before December 1, 2026' -> match if the deadline is before Jan 2027."""
    for m in START.finditer(text or ""):
        first, last = period(m["d"])
        deadline = first if m["op"].lower() == "before" else last
        if deadline < EARLIEST_START:
            return m
    return None


def grad_outside(text: str) -> re.Match | None:
    """Graduation window that excludes December 2026."""
    text = text or ""
    for m in GRAD_BY.finditer(text):
        first, last = period(m["d"])
        if (m["op"].lower() == "before" and first <= YOU_GRADUATE) or last < YOU_GRADUATE:
            return m
    for m in GRAD_BETWEEN.finditer(text):
        if not period(m["a"])[0] <= YOU_GRADUATE <= period(m["b"])[1]:
            return m
    return None


# Palantir splits "What We Value" (nice to have) from "What We Require"
VALUE = re.compile(r"what\s+we\s+value", re.I)
REQUIRE = re.compile(r"what\s+we\s+require", re.I)


def under_value(text: str, m: re.Match) -> bool:
    """True if the nearest heading above the match is "What We Value"."""
    v = [h.start() for h in VALUE.finditer(text, 0, m.start())]
    r = [h.start() for h in REQUIRE.finditer(text, 0, m.start())]
    return bool(v) and (not r or v[-1] > r[-1])


# The role itself is senior ("We're looking for a Senior Software Engineer"),
# not "working alongside senior engineers"
SENIOR_ROLE = re.compile(
    r"(looking\s+for|seeking|hiring)\s+(an?\s+)?(experienced\s+)?(senior|staff|principal|sr\.?)\s+"
    r"(\w+\s+){0,2}(engineer|developer)|"
    r"\bas\s+an?\s+(senior|staff|principal|sr\.?)\s+(\w+\s+){0,2}(engineer|developer)",
    re.I,
)


# Section headings inside a flat description ("... code. Minimum qualifications: Bachelor's ...").
# A heading counts only when capitalized or followed by a colon, so "translate defined requirements
# into" in a sentence isn't one.
HEADINGS = {
    "minimum": r"minimum qualifications|basic qualifications|required qualifications|minimum requirements|"
               r"requirements|qualifications|key qualifications|what you(?:'|’)ll need|what we(?:'|’)re looking for|"
               r"what you bring|you (?:will )?(?:have|bring)|who you are|required",
    "preferred": r"preferred qualifications|preferred skills|preferred experience|nice[- ]to[- ]haves?|bonus points?|"
                 r"additional qualifications|it(?:'|’)s a plus|preferred",
    "boilerplate": r"equal (?:employment )?opportunity|benefits|compensation|pay (?:range|transparency)|salary range|"
                   r"(?:the )?base pay range|about (?:us|the company)|accommodations?|e-verify|privacy notice|"
                   r"what we offer|perks",
}
HEADING = re.compile("|".join(f"(?P<{k}>(?:{v}))(?P<{k}_colon>\\s*:)?" for k, v in HEADINGS.items()), re.I)


def sections(text: str) -> dict[str, str]:
    """The description split by its headings: minimum, preferred, boilerplate and other text."""
    text = text or ""
    out = {"minimum": [], "preferred": [], "boilerplate": [], "other": []}
    kind, start = "other", 0
    for m in HEADING.finditer(text):
        k = m.lastgroup.removesuffix("_colon")
        word = m.group(k)
        if not (m.group(f"{k}_colon") or word[0].isupper()):
            continue   # a word in a sentence, not a heading
        out[kind].append(text[start:m.start()])
        kind, start = k, m.end()
    out[kind].append(text[start:])
    return {k: " ".join(v).strip() for k, v in out.items()}


# Degree ladders ("Bachelor's + 5 years OR Master's + 3 years OR PhD + 0"): the line for your
# degree is your requirement. A years mention belongs to the nearest degree before it in the same
# clause (no other years mention in between); one with no degree is a requirement of its own.
YOUR_DEGREE = "master"   # bachelor / master / phd: the ladder line that applies to you
DEGREE = re.compile(r"\b(?:(?P<bachelor>bachelor|b\.?\s?s\.?\b|b\.?\s?a\.?\b|undergraduate)|"
                    r"(?P<master>master|m\.?\s?s\.?\b)|(?P<phd>ph\.?\s?d|doctora))", re.I)
LADDER_BACK = 200
# a degree substitute isn't an ask for someone with the degree: "In lieu of a degree, a combined
# minimum of 5 years' education and/or experience"; "Bachelor's degree ... or 5+ years equivalent experience"
IN_LIEU = re.compile(r"lieu\s+of\s+(a\s+)?(bachelor'?s?\s+)?degree[^.]{0,120}$", re.I)   # same clause, before it
EQUIVALENT = re.compile(r"\s*(of\s+)?equivalent\b", re.I)
# The degree's length, not experience: Abbott "Bachelors Degree (± 16 years) in an Engineering ... Field"
DEGREE_LENGTH = re.compile(r"degree\s*\(\s*[±~]?\s*$", re.I)
# The no-degree rung after a degree ladder: Cox "Bachelor's degree and 2 years' experience ... or a
# master's degree and up to 2 years' experience; or 6 years' experience in a related field"
NO_DEGREE_RUNG = re.compile(r"[;,]?\s*\bor\s+(an?\s+)?$", re.I)   # "5+ years equivalent", not "years of experience or equivalent"


def ladder_degree(text: str, m: re.Match, years: list[re.Match]) -> str | None:
    """The degree a years mention is tied to, or None (a requirement on its own)."""
    lo = max(m.start() - LADDER_BACK, 0)
    degrees = list(DEGREE.finditer(text, lo, m.start()))
    if not degrees:
        return None
    d = degrees[-1]
    if any(d.end() <= y.start() < m.start() for y in years):
        return None   # another years mention sits in between: its own requirement
    return d.lastgroup


def min_years(text: str) -> int | None:
    """Headline years ask: the largest real requirement. Minimum-qualification lines decide when the
    posting has them; preferred lines, company boilerplate and degree substitutes never count, and in
    a degree ladder only your degree's line does.

    "2 years of software development. 1 year with recommendation systems" -> 2 (both are minimums).
    "Bachelor's + 5 years OR Master's + 3 years" -> 3 (YOUR_DEGREE master).
    """
    text = text or ""
    parts = sections(text)
    text = parts["minimum"] or f"{parts['other']} {parts['minimum']}"
    found = list(YEARS.finditer(text))
    asks = []   # (years, degree or None)
    for m in found:
        s = sentence(text, m)
        if SOFT_YEARS.search(ASIDE_LIST.sub("", s)) or IN_LIEU.search(text, max(m.start() - 150, 0), m.start()) or EQUIVALENT.match(text, m.end()):
            continue
        if DEGREE_LENGTH.search(text, max(m.start() - 15, 0), m.start()):
            continue
        degree = ladder_degree(text, m, found)
        if degree is None and NO_DEGREE_RUNG.search(text, max(m.start() - 8, 0), m.start()) and any(
                d for n, d in asks):
            continue   # "...; or 6 years' experience": what you need without the degrees above
        raw = m.group(1).lower()
        n = NUM_WORDS.get(raw) or int(raw)
        if 0 < n <= 20:
            asks.append((n, degree))
    if not asks:
        return None
    ladder = {d for _, d in asks if d}
    # your line if the posting has one; else the lowest degree line it gives (a bachelor's ask still applies)
    mine = YOUR_DEGREE if YOUR_DEGREE in ladder else next((d for d in ("bachelor", "master", "phd") if d in ladder), None)
    return max(n for n, d in asks if d is None or d == mine)


# --- Is it actually a software job? ---
# Titles like "Performance Engineer" or "Platform Engineer" can be building/HVAC roles
# (Johnson Controls). Unless the title says software, the description must show it.
# Cloud / SRE / DevOps / ML titles count too: a first pass without them skipped real SRE,
# ML-infra and "Cloud Engineer (AWS)" jobs (Mistral, Navan, DRW, Contact Government Services).
SOFTWARE_TITLE = re.compile(
    r"software|developer|\bswe\b|\bsde\b|full[\s-]?stack|back[\s-]?end|front[\s-]?end|forward\s+deployed|"
    r"machine\s+learning|\bml\b|\bai\b|\bllms?\b|site\s+reliability|\bsre\b|devops|\bcloud\b", re.I)
# Infra/ML terms separate real platform jobs from construction/HVAC ones (which had none).
# Not "automation": HVAC postings say "building automation systems".
SIGNALS = re.compile(
    r"\b(software|programming|code|python|java|javascript|typescript|golang|apis?|aws|gcp|azure|kubernetes|"
    r"docker|sql|linux|terraform|ci/cd|pytorch|tensorflow|machine\s+learning|distributed\s+systems|scripting|"
    r"bash|rust|ruby|scala|kafka|spark|gpus?|cuda|infrastructure[\s-]as[\s-]code|ansible|helm|observability|"
    r"microservices|back[\s-]?end|devops|llms?|inference|data\s+pipelines?|git|github|ec2|s3|cloudformation)\b"
    r"|(?<![\w+])c\+\+(?![\w+])", re.I)
GO = re.compile(r"\bGo\b")
URL = re.compile(r"https?://\S+")   # case-sensitive: the language, not "go above and beyond"
MIN_SIGNALS = 2


def software_signals(text: str) -> set[str]:
    """Distinct software terms ("APIs" and "API" count once). URLs are ignored: a privacy-notice
    link like "...assets-public.s3.us-east-2.amazonaws.com" is not an S3 job (Saronic)."""
    text = URL.sub(" ", text)
    found = {re.sub(r"\s+", " ", m.group(0).lower()) for m in SIGNALS.finditer(text)}
    found = {f[:-1] if f in ("apis", "gpus", "llms") else f for f in found}
    return found | ({"go"} if GO.search(text) else set())


def check(text: str, title: str = "") -> tuple[bool, str | None, int | None, list[str]]:
    """Returns (ok, skip_reason, min_years, flags)."""
    text = text or ""
    flags = []
    if TS_SCI.search(text) or (title and CLEARED_TITLE.search(title)) or citizenship_required(text):
        return False, "citizenship/clearance", min_years(text), flags
    for reason, rx in BLOCKERS.items():
        found = list(rx.finditer(text))
        hard = [m for m in found if not is_soft(reason, text, m)]
        if reason == "citizenship/clearance" and found and all(under_value(text, m) for m in hard):
            flags.append("clearance preferred")   # only wished for ("a plus") or under "What We Value"
            continue
        if hard:
            return False, reason, min_years(text), flags
    if "clearance preferred" not in flags and any(
            SOFT_CLEARANCE.search(sentence(text, m)) for m in CLEARANCE.finditer(text)):
        flags.append("clearance preferred")   # "Security clearance preferred", "... is a plus"
    if title and not SOFTWARE_TITLE.search(title) and len(software_signals(text)) < MIN_SIGNALS:
        return False, "not software", min_years(text), flags
    yrs = min_years(text)
    if SENIOR_ROLE.search(text):
        return False, "senior role", yrs, flags
    if cap := experience_cap(text):
        flags.append(cap_flag(cap))   # a match you decide on, not a skip
    if early_start(text):
        return False, "start date", yrs, flags
    if grad_outside(text):
        return False, "graduation date", yrs, flags
    if yrs is not None and yrs > MAX_YEARS:
        return False, f"{yrs}+ years", yrs, flags
    if IMMEDIATE.search(text):
        flags.append("early start?")
    return True, None, yrs, flags
