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
        r"\bitar\b|export\s+control(led)?\s+.{0,40}u\.?s\.?\s+person",
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
    return bool(SOFT_CLEARANCE.search(sentence(text, m)))


def min_years(text: str) -> int | None:
    """Smallest years-of-experience number mentioned (lenient: keeps borderline jobs)."""
    found = []
    for m in YEARS.finditer(text or ""):
        if SOFT_YEARS.search(sentence(text, m)):
            continue
        raw = m.group(1).lower()
        n = NUM_WORDS.get(raw) or int(raw)
        if 0 < n <= 20:
            found.append(n)
    return min(found) if found else None


def check(text: str) -> tuple[bool, str | None, int | None]:
    """Returns (ok, skip_reason, min_years)."""
    text = text or ""
    for reason, rx in BLOCKERS.items():
        if any(not is_soft(reason, text, m) for m in rx.finditer(text)):
            return False, reason, min_years(text)
    yrs = min_years(text)
    if yrs is not None and yrs > MAX_YEARS:
        return False, f"{yrs}+ years", yrs
    return True, None, yrs
