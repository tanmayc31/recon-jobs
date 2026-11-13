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

# 2. Drop students ("NVIDIA 2027 Internships: Software Engineering"; "Internal Tools" stays) ...
STUDENT = re.compile(r"\b(interns?|internships?|co-?ops?)\b", re.I)
# ...seniority and non-engineering titles
EXCLUDE = re.compile(
    r"\b(senior|sr\.?|staff|principal|lead|manager|director|head of|architect|distinguished|"
    r"iii|iv|phd|high school|apprentice|"
    r"sales|account executive|recruiter|marketing|analyst|consultant|strategist|"
    r"solutions engineer|partner|electrical|mechanical|hardware|support engineer|"
    r"quality assurance|\bqa\b|test engineer|contract|ftc|temporary|data center|"
    # specialty tracks (ML hardware, OS, devices) - not general SWE
    r"compilers?|accelerators?|kernel|silicon|firmware|embedded|robotics|consumer devices|"
    r"tpus?|gpus?|hpc|rdma)\b"
    r"|engineer\s*[-–—]?\s*(3|4|5)\b|\bl[5-9]\b",
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

# "Columbus, OH": any state code after a comma, uppercase only ("Remote in Canada" isn't Indiana).
# US above only knows 18 codes as bare words.
US_STATE = re.compile(
    r",\s*(AL|AK|AZ|AR|CA|CO|CT|DE|DC|FL|GA|HI|ID|IL|IN|IA|KS|KY|LA|ME|MD|MA|MI|MN|MS|MO|MT|NE|NV|NH|NJ|NM|NY|"
    r"NC|ND|OH|OK|OR|PA|RI|SC|SD|TN|TX|UT|VT|VA|WA|WV|WI|WY)\b")

# Workday's "ESP - MD - LAS ROZAS": a leading ISO country code, then region and city. Checked
# before the US words, or "MD" reads as Maryland. Listed codes only: "RTP - ..." and "NYC - ..."
# are US city codes in the same spot.
COUNTRY_CODE = re.compile(
    r"^\s*(ARE|ARG|AUS|AUT|BEL|BGR|BRA|CAN|CHE|CHL|CHN|COL|CRI|CZE|DEU|DNK|EGY|ESP|EST|FIN|FRA|GBR|GRC|"
    r"HKG|HRV|HUN|IDN|IND|IRL|ISR|ITA|JPN|KEN|KOR|LTU|LUX|LVA|MAR|MEX|MYS|NGA|NLD|NOR|NZL|PAK|PER|PHL|"
    r"POL|PRT|QAT|ROU|SAU|SGP|SRB|SVK|SVN|SWE|THA|TUR|TWN|UKR|URY|VNM|ZAF)\s*[-–,|/]")

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
    parts = loc.split(";")
    if parts and all(COUNTRY_CODE.match(p) for p in parts):
        return "no"
    loc = ";".join(p for p in parts if not COUNTRY_CODE.match(p))   # a US place elsewhere still wins
    if US.search(loc) or US_STATE.search(loc):
        return "us"              # any US place wins, even if Toronto is also listed
    if VAGUE.match(loc):
        return "vague"
    return "no"                  # allowlist: unknown cities are treated as non-US


def classify(job: Job) -> tuple[bool, list[str]]:
    """Returns (keep, flags). A dropped job's flags hold why: ["title: Sr"] (the word that dropped it),
    ["intern/co-op"], ["non-US location"], or ["title"] (not an engineering role)."""
    t = job.title
    if not (ROLE.search(t) and ENG.search(t)):
        return False, ["title"]
    if STUDENT.search(t):
        return False, ["intern/co-op"]
    if m := EXCLUDE.search(t):
        return False, [f"title: {m.group(0).strip()}"]
    if SECURITY_ONLY.search(t) and not re.search(r"software", t, re.I):
        return False, ["title"]
    loc = location_status(job.location)
    if loc == "vague":
        m = AVAILABLE.search(job.description or "")
        if m:
            loc = location_status(CONNECTOR.sub("; ", m.group(1)))
    if loc == "no":
        return False, ["non-US location"]
    flags = []
    if loc == "vague":
        flags.append("location?")
    if GOV.search(t):
        flags.append("gov/clearance?")
    return True, flags


def is_match(job: Job) -> bool:
    return classify(job)[0]
