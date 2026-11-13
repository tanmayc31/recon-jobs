"""Role type from the title, for the dashboard's role filter. First match wins."""
import re

ROLES = [   # (key, title pattern); order matters: "Backend Software Engineer" is backend, not plain SWE
    ("fde", r"forward[\s-]deploy|\bfde\b"),
    ("ml", r"machine learning|\bml\b|\bai\b|\bllm|deep learning|computer vision|\bnlp\b|gen ?ai|generative"),
    ("fullstack", r"full[\s-]?stack"),
    ("backend", r"back[\s-]?end|server[\s-]side"),
    ("frontend", r"front[\s-]?end|\bui\b|\bweb (developer|engineer)"),
    ("cloud", r"cloud|devops|dev ops|site reliability|\bsre\b|reliability engineer|platform engineer|"
              r"infrastructure|systems? development engineer|\bsysde\b"),
    ("swe", r"software|\bswe\b|\bsde\b|developer|programmer|application engineer"),
]
ROLES = [(key, re.compile(rx, re.I)) for key, rx in ROLES]


def role_type(title: str) -> str:
    """swe / fullstack / backend / frontend / cloud / fde / ml / other."""
    return next((key for key, rx in ROLES if rx.search(title or "")), "other")


# Level, for ranking the roles you can actually get. The title decides first ("Software Engineer II,
# New Grad" doesn't happen); then the AI's seniority; then the years the posting requires.
ROLE_WORD = r"(engineer|developer|swe|sde|programmer)"
ENTRY = re.compile(
    r"new grad|new college grad|early[\s-]career|university|\bgraduate\b|\bassociate\b|\bjunior\b|\bjr\b\.?|"
    rf"entry[\s-]level|\b{ROLE_WORD}\s*,?\s*(i|1)\b(?![-.]\d)|\blevel\s*(i|1)\b|\b(l1|ic1)\b", re.I)
SECOND = re.compile(rf"\b{ROLE_WORD}\s*,?\s*(ii|2)\b|\blevel\s*(ii|2)\b|\bmid[\s-]level\b|\b(l2|ic2)\b", re.I)
MAX_ENTRY_YEARS = 2


def level(title: str, min_years: int | None = None, ai_seniority: str | None = None,
          ai_years: int | None = None) -> str:
    """'entry' (new grad, junior, SWE I, or 0-2 years required), 'ii' (SWE II / mid) or 'unknown'."""
    title = title or ""
    if ENTRY.search(title):
        return "entry"
    if SECOND.search(title):
        return "ii"
    if ai_seniority in ("new grad", "junior"):
        return "entry"
    years = min_years if min_years is not None else ai_years
    if years is not None and years <= MAX_ENTRY_YEARS:
        return "entry"
    return "ii" if ai_seniority == "mid" else "unknown"
