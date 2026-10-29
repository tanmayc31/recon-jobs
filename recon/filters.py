"""Rule-based job filter (the "bouncer"). Fast, free, no AI."""
import re
from recon.models import Job

# 1. Role: title must name an engineering role...
ROLE = re.compile(
    r"software|\bswe\b|\bsde\b|full[\s-]?stack|backend|back[\s-]end|frontend|front[\s-]end|"
    r"\bcloud\b|platform|infrastructure|forward deployed|devops|site reliability|\bsre\b",
    re.I,
)
# ...and must actually be an engineer/developer (drops "FP&A Analyst, Cloud Finance")
ENG = re.compile(r"engineer|developer|\bswe\b|\bsde\b|\bsre\b", re.I)

# 2. Drop seniority, students, and non-engineering titles
EXCLUDE = re.compile(
    r"\b(senior|sr\.?|staff|principal|lead|manager|director|head of|architect|distinguished|"
    r"iii|iv|phd|intern|internship|co-?op|high school|apprentice|"
    r"sales|account executive|recruiter|marketing|analyst|consultant|strategist|"
    r"solutions engineer|partner|electrical|mechanical|hardware|support engineer|"
    r"quality assurance|\bqa\b|test engineer|contract|ftc|temporary|data center|"
    # specialty tracks (ML hardware, OS, devices) - not general SWE
    r"compilers?|accelerators?|kernel|silicon|firmware|embedded|robotics|consumer devices|"
    r"tpus?|gpus?|hpc|rdma)\b"
    r"|engineer\s*(3|4|5)\b|\bl[5-9]\b",
    re.I,
)

# 3. Location
US = re.compile(
    r"united states|\busa?\b|us[\s-]remote|remote[\s-]*(in\s+)?(us|usa|united states)|"
    r"new york|nyc|san francisco|\bsf\b|seattle|\bsea\b|boston|austin|chicago|denver|atlanta|"
    r"los angeles|bay area|mountain view|palo alto|menlo park|sunnyvale|san jose|bellevue|"
    r"washington|cambridge|san diego|norfolk|kitsap|fayetteville|"
    r"\b(ca|ny|wa|ma|tx|il|co|ga|nc|va|nj|or|az|ut|fl|pa|mi|md)\b",
    re.I,
)
NON_US = re.compile(
    r"india|bangalore|bengaluru|hyderabad|pune|brazil|canada|toronto|vancouver|montreal|"
    r"london|\buk\b|united kingdom|ireland|dublin|germany|berlin|munich|france|paris|"
    r"japan|tokyo|korea|seoul|singapore|australia|sydney|mexico|poland|spain|netherlands|"
    r"amsterdam|israel|tel aviv|china|emea|apac|latam",
    re.I,
)

# Vague locations: keep, but flag ("Hybrid; In-Office" counts too)
VAGUE_WORD = r"(n/?a|na|hybrid|in-office|distributed|remote|tbd|multiple locations)"
VAGUE = re.compile(rf"^\s*({VAGUE_WORD}(\s*[;,/|]\s*{VAGUE_WORD})*)?\s*$", re.I)
# Cloudflare puts the real city in the description: "Available Locations: London About ..."
AVAILABLE = re.compile(
    r"Available Locations?:\s*(.{1,100}?)(?=\s+(?:About|What|We|We're|Our|The|Role)\b|\n|$)")
CONNECTOR = re.compile(r"\s(?:or|and)\s")   # lowercase only, so "Portland, OR" survives
SECURITY_ONLY = re.compile(r"security engineer", re.I)

# 4. Flags: keep the job, but mark it for a closer look (seed of Lane C)
GOV = re.compile(r"us government|\busg\b|\bgov\b|federal|public sector|defense|\bintel\b", re.I)


def location_status(loc: str) -> str:
    """'us' = names a US place, 'vague' = no real place given, 'no' = somewhere else."""
    loc = loc or ""
    if US.search(loc):
        return "us"              # any US place wins, even if Toronto is also listed
    if VAGUE.match(loc):
        return "vague"
    return "no"                  # allowlist: unknown cities are treated as non-US


def classify(job: Job) -> tuple[bool, list[str]]:
    """Returns (keep, flags)."""
    t = job.title
    if not (ROLE.search(t) and ENG.search(t)):
        return False, []
    if EXCLUDE.search(t):
        return False, []
    if SECURITY_ONLY.search(t) and not re.search(r"software", t, re.I):
        return False, []
    loc = location_status(job.location)
    if loc == "vague":
        m = AVAILABLE.search(job.description or "")
        if m:
            loc = location_status(CONNECTOR.sub("; ", m.group(1)))
    if loc == "no":
        return False, []
    flags = []
    if loc == "vague":
        flags.append("location?")
    if GOV.search(t):
        flags.append("gov/clearance?")
    return True, flags


def is_match(job: Job) -> bool:
    return classify(job)[0]
