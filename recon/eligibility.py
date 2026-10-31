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
    r"\b(\d{1,2}|one|two|three|four|five|six|seven|eight|nine|ten)\s*\+?\s*"
    r"(?:(?:-|–|to)\s*\d{1,2}\s*\+?\s*)?(?:years?|yrs?)\b"
    r"(?=[^.]{0,80}\b(experience|industry|professional|engineering|software|building|developing|working))",
    re.I,
)

BLOCKERS = {
    "citizenship/clearance": re.compile(
        r"u\.?s\.?\s+citizen(ship)?\s+(is\s+)?required|must\s+be\s+(a\s+)?u\.?s\.?\s+citizen|"
        r"(security\s+)?clearance\s+(is\s+)?required|active\s+(secret|top\s+secret|ts/sci)|"
        r"(obtain|maintain|eligible\s+for)\s+(a\s+|an\s+)?(u\.?s\.?\s+)?(government\s+)?security\s+clearance|"
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
        r"not\s+(accept|eligible\s+for)\s+.{0,20}\b(opt|cpt)\b",
        re.I,
    ),
}


# Soft words: the sentence is a wish, not a requirement
SOFT_CLEARANCE = re.compile(r"beneficial|preferred|a\s+plus|nice\s+to\s+have|not\s+necessary", re.I)
SOFT_YEARS = re.compile(r"preferred|nice\s+to\s+have|bonus|a\s+plus", re.I)
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
MIN_CAP_YEARS = 3           # block caps below this ("no more than 18 months")

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


def min_years(text: str) -> int | None:
    """Headline years ask: largest number in each sentence, then smallest across sentences.

    "5+ years, including 3+ years in infra" -> 5. Separate sentences stay lenient.
    """
    text = text or ""
    groups, prev_end = [], None
    for m in YEARS.finditer(text):
        if SOFT_YEARS.search(sentence(text, m)):
            continue
        raw = m.group(1).lower()
        n = NUM_WORDS.get(raw) or int(raw)
        if not 0 < n <= 20:
            continue
        # new sentence if punctuation sits between this match and the last one
        if prev_end is None or END.search(text, prev_end, m.start()) or m.start() - prev_end > AHEAD:
            groups.append([])
        groups[-1].append(n)
        prev_end = m.end()
    return min(max(g) for g in groups) if groups else None


def check(text: str) -> tuple[bool, str | None, int | None, list[str]]:
    """Returns (ok, skip_reason, min_years, flags)."""
    text = text or ""
    flags = []
    for reason, rx in BLOCKERS.items():
        hard = [m for m in rx.finditer(text) if not is_soft(reason, text, m)]
        if reason == "citizenship/clearance" and hard and all(under_value(text, m) for m in hard):
            flags.append("clearance preferred")
            continue
        if hard:
            return False, reason, min_years(text), flags
    yrs = min_years(text)
    if SENIOR_ROLE.search(text):
        return False, "senior role", yrs, flags
    if experience_cap(text):
        return False, "experience cap", yrs, flags
    if early_start(text):
        return False, "start date", yrs, flags
    if grad_outside(text):
        return False, "graduation date", yrs, flags
    if yrs is not None and yrs > MAX_YEARS:
        return False, f"{yrs}+ years", yrs, flags
    if IMMEDIATE.search(text):
        flags.append("early start?")
    return True, None, yrs, flags
