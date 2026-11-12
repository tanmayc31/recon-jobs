"""H-1B sponsors: who files the most software H-1Bs, and do we watch them?

Ranks employers by certified H-1B LCA filings for software roles (DOL OFLC disclosure data,
public), matches them to companies.csv, and finds which ATS the missing ones use.

  python -m recon.sponsors data/LCA_Disclosure_Data_FY2025_Q*.xlsx   # writes config/sponsors.csv
  python -m recon.sponsors --load     # copies config/sponsors.csv into the database (dashboard badge)

Download the quarterly xlsx files in a browser (dol.gov blocks scripts) from
https://www.dol.gov/agencies/eta/foreign-labor/performance into data/ (gitignored).
Reading them needs python-calamine (pip install python-calamine); nothing else in Recon does.
"""
import argparse
import asyncio
import csv
import difflib
import os
import re
from collections import Counter, defaultdict
from pathlib import Path

import httpx

from recon.detect import CHECKS
from recon.discover import JOBSEEK, READMES, parse_board
from recon.env import load_env
from recon.main import COMPANIES, HEADERS
from recon.store import Store

SPONSORS = Path(__file__).parent.parent / "config" / "sponsors.csv"
TOP = 500             # matches and ATS lookups checked by hand down to this rank
SUPPORTED = ["greenhouse", "lever", "ashby", "workday"]

# --- 1. Rank: certified H-1B software filings per employer ---

SOC = {"15-1252", "15-1253", "15-1299", "15-1211"}   # software devs, QA, computer occ. other, systems analysts
SWE_TITLE = re.compile(
    r"software|developer|\bswe\b|\bsde\b|full[\s-]?stack|back[\s-]?end|front[\s-]?end|"
    r"programmer|application(s)? engineer|devops|site reliability|\bsre\b|cloud engineer|"
    r"platform engineer|machine learning engineer|\bml engineer", re.I)
SUFFIX = re.compile(
    r"\b(l\.?l\.?c|inc|incorporated|corp|corporation|co|company|ltd|limited|l\.?p|llp|pllc|p\.?c|"
    r"plc|n\.?a|na|the|usa|us|u\.s\.a?|america|americas|north america|group|holdings?|"
    r"technologies|technology|services|solutions|systems|global|international|enterprises?)\b\.?",
    re.I)
# brand variants the suffix rule can't merge (filers use several legal entities)
ALIASES = [(re.compile(p, re.I), brand) for p, brand in [
    (r"^amazon|^aws\b|^a2z development|^amazon web", "Amazon"),
    (r"^google|^alphabet", "Google"),
    (r"^meta platforms|^facebook", "Meta"),
    (r"^microsoft", "Microsoft"),
    (r"^apple\b(?! bank| hospitality)", "Apple"),
    (r"^ibm\b|^international business machines", "IBM"),
    (r"^intel\b|^intel corp", "Intel"),
    (r"^oracle\b", "Oracle"),
    (r"^salesforce", "Salesforce"),
    (r"^jpmorgan|^j\.?p\.? morgan|^jp morgan", "JPMorgan Chase"),
    (r"^goldman sachs", "Goldman Sachs"),
    (r"^morgan stanley", "Morgan Stanley"),
    (r"^bank of america|^bofa", "Bank of America"),
    (r"^wells fargo", "Wells Fargo"),
    (r"^citi(bank|group|corp)?\b", "Citi"),
    (r"^capital one", "Capital One"),
    (r"^walmart|^wal-mart", "Walmart"),
    (r"^tata consultancy|^tcs\b", "Tata Consultancy Services"),
    (r"^infosys", "Infosys"),
    (r"^cognizant", "Cognizant"),
    (r"^wipro", "Wipro"),
    (r"^hcl\b|^hcl america|^hcltech", "HCLTech"),
    (r"^tech mahindra", "Tech Mahindra"),
    (r"^accenture", "Accenture"),
    (r"^deloitte", "Deloitte"),
    (r"^ernst & young|^ernst and young|^ey\b", "EY"),
    (r"^pricewaterhouse|^pwc\b", "PwC"),
    (r"^kpmg", "KPMG"),
    (r"^capgemini", "Capgemini"),
    (r"^ltimindtree|^larsen & toubro infotech|^mindtree", "LTIMindtree"),
    (r"^nvidia", "Nvidia"),
    (r"^qualcomm", "Qualcomm"),
    (r"^cisco", "Cisco"),
    (r"^adobe", "Adobe"),
    (r"^uber\b", "Uber"),
    (r"^bytedance|^tiktok", "ByteDance/TikTok"),
    (r"^linkedin", "LinkedIn"),
    (r"^vmware|^broadcom", "Broadcom/VMware"),
    (r"^dell\b|^emc corp", "Dell"),
    (r"^hewlett packard enterprise|^hpe\b", "HPE"),
    (r"^hp inc|^hp\b", "HP"),
    (r"^paypal", "PayPal"),
    (r"^ebay", "eBay"),
    (r"^intuit", "Intuit"),
    (r"^servicenow", "ServiceNow"),
    (r"^workday", "Workday"),
    (r"^snowflake", "Snowflake"),
    (r"^databricks", "Databricks"),
    (r"^stripe", "Stripe"),
    (r"^netflix", "Netflix"),
    (r"^tesla", "Tesla"),
    (r"^samsung", "Samsung"),
    (r"^micron", "Micron"),
    (r"^american express", "American Express"),
    (r"^visa\b", "Visa"),
    (r"^mastercard", "Mastercard"),
    (r"^fidelity(?! national)|^fmr\b", "Fidelity"),   # not FIS (Fidelity National Information Services)
    (r"^bloomberg", "Bloomberg"),
    (r"^expedia", "Expedia"),
    (r"^ntt data", "NTT DATA"),
    (r"^mphasis", "Mphasis"),
    (r"^ust global|^ust\b", "UST"),
    (r"^virtusa", "Virtusa"),
    (r"^zensar", "Zensar"),
    (r"^persistent systems", "Persistent Systems"),
    (r"^epam", "EPAM"),
    (r"^genpact", "Genpact"),
    (r"^igate|^syntel", "Atos/Syntel"),
    (r"^larsen|^l&t\b", "L&T"),
    (r"^government employees? insurance|^geico", "GEICO"),
    (r"^cigna", "Cigna"),
    (r"^cvs\b", "CVS Health"),
    (r"^federal express|^fedex", "FedEx"),
    (r"^sap\b", "SAP"),
    (r"^lexisnexis risk", "LexisNexis Risk Solutions"),
    (r"^environmental systems research|^esri\b", "Esri"),
    (r"^dish (network|wireless)", "DISH"),
    (r"^moody", "Moody's"),
    (r"^db (global technology|usa core)|^deutsche bank", "Deutsche Bank"),
    (r"^intercontinental exchange|^ice mortgage", "ICE"),
    (r"^advanced micro devices|^amd\b|^xilinx", "AMD"),
    (r"^ascendion|^collabera", "Ascendion"),
    (r"^rivian", "Rivian"),
    (r"^astir\b", "Astir"),
]]
BRANDS = {brand.lower(): brand for _, brand in ALIASES}


def canon(name: str) -> str:
    """Grouping key: alias brand, else the name minus punctuation and legal suffixes."""
    n = " ".join(name.split()).strip(" .,")
    for rx, brand in ALIASES:
        if rx.search(n):
            return brand.lower()
    k = re.sub(r"[,.'\"()]", " ", n.lower()).replace("&", " and ")
    return " ".join(SUFFIX.sub(" ", k).split()) or n.lower()


def is_swe(row: dict) -> bool:
    """Certified H-1B with a software SOC code or job title."""
    return (str(row["CASE_STATUS"]).strip().lower() == "certified"
            and str(row["VISA_CLASS"]).strip() == "H-1B"
            and (str(row["SOC_CODE"]).strip()[:7] in SOC or bool(SWE_TITLE.search(str(row["JOB_TITLE"])))))


def rank(rows) -> list[dict]:
    """LCA rows (dicts) -> employers by software filings. A case listed twice counts once."""
    filings, names, cases = Counter(), defaultdict(Counter), set()
    for r in rows:
        if r["CASE_NUMBER"] in cases or not is_swe(r):
            continue
        cases.add(r["CASE_NUMBER"])
        name = str(r["EMPLOYER_NAME"]).strip()
        k = canon(name)
        filings[k] += 1
        names[k][name] += 1
    return [{"key": k, "employer": BRANDS.get(k) or names[k].most_common(1)[0][0], "filings": n}
            for k, n in filings.most_common()]


def read_lca(paths) -> list[dict]:
    from python_calamine import CalamineWorkbook   # only needed here
    rows = []
    for path in paths:
        sheet = CalamineWorkbook.from_path(str(path)).get_sheet_by_index(0).to_python()
        head = [str(h).strip().upper() for h in sheet[0]]
        file_rows = [dict(zip(head, r)) for r in sheet[1:]]
        dates = [str(r["DECISION_DATE"])[:10] for r in file_rows]
        print(f"{Path(path).name}: {len(file_rows)} cases, decisions {min(dates)} to {max(dates)}")
        rows += file_rows
    return rows


# --- 2. Match: is this employer in companies.csv? ---

GENERIC = {"it", "soft", "global", "american", "united", "first", "general", "national", "data", "cloud"}
# legal name key -> companies.csv name (checked by hand)
SAME = {
    "maplebear": "instacart", "social finance": "sofi", "people center d/b/a rippling": "rippling",
    "block": "square", "bytedance/tiktok": "tiktok", "united automobile association": "usaa",
    "lowe s companies": "lowe's", "united parcel service general": "united parcel service",
    "verizon data": "verizon communications", "huntington national bank": "huntington bancshares",
    "aurora operations": "aurora innovation", "cloud software": "citrix", "at and t": "at&t",
    "cox automotive corporate": "cox", "rockwell collins": "rtx", "hca management": "hca healthcare",
    "kroger": "84.51 (kroger)",
    # subsidiaries hiring through the parent's board we already track
    "caremark": "cvs health", "aetna resources": "cvs health", "cybersource": "visa",
    "juniper networks": "hewlett packard enterprise",
}
# companies.csv rows a prefix or exact name match would wrongly pick (checked by hand)
NOT_SAME = {"Tech Holding", "Strategic Hr Client Job Openings", "System", "Elite Technology", "Orion Group",
            "Farmers Mutual Hail", "Genesis Molecular AI", "Genesis Ai", "Marriott Vacations Worldwide",
            "Archer", "Precision Aq", "Precision For Medicine", "Apple Bank", "Fidelity International"}


def keys(name: str) -> set[str]:
    out = {canon(name)}
    if m := re.search(r"\b(?:d/b/a|dba)\b\s*(.+)", name, re.I):
        out.add(canon(m.group(1)))
    return out


def prefix_match(a: str, b: str) -> bool:
    """'robinhood markets' ~ 'robinhood' (whole words, not too short or generic)."""
    short, long_ = sorted((a, b), key=len)
    return (len(short) >= 4 and short.split()[0] not in GENERIC
            and (long_ == short or long_.startswith(short + " ")))


def match(ranked: list[dict], companies: list[dict], top: int = TOP):
    """Sets e['covered'] to the companies.csv name. Prefix matches only within the top (checked by hand)."""
    companies = [c for c in companies if c["company"] not in NOT_SAME]
    tracked = {}
    for c in companies:
        for k in keys(c["company"]):
            tracked.setdefault(k, c["company"])
    by_name = {c["company"].lower(): c["company"] for c in companies}
    for i, e in enumerate(ranked):
        cands = keys(e["employer"]) | {e["key"]}
        cands |= {SAME[k] for k in cands if k in SAME}
        e["covered"] = next((tracked.get(k) or by_name.get(k) for k in cands if k in tracked or k in by_name), None)
        if not e["covered"] and i < top:
            e["covered"] = next((tracked[t] for k in cands for t in tracked if prefix_match(k, t)), None)
            if not e["covered"]:
                e["near"] = difflib.get_close_matches(e["key"], list(tracked), n=2, cutoff=0.8)


# --- 3. ATS: where do the missing ones post jobs? ---

HOSTS = [  # board URL / page fingerprint -> ATS
    (r"myworkdayjobs\.com|myworkdaysite\.com", "workday"),
    (r"greenhouse\.io", "greenhouse"), (r"jobs\.lever\.co|api\.lever\.co", "lever"),
    (r"ashbyhq\.com", "ashby"), (r"icims\.com", "icims"), (r"oraclecloud\.com", "oracle"),
    (r"smartrecruiters\.com", "smartrecruiters"), (r"eightfold\.ai", "eightfold"),
    (r"successfactors\.|sapsf\.|jobs\.sap\.com", "successfactors"), (r"taleo\.net", "taleo"),
    (r"phenompeople\.com|phenom\.com", "phenom"), (r"jobvite\.com", "jobvite"),
    (r"workable\.com", "workable"), (r"avature\.net", "avature"), (r"ultipro\.com|ukg\.", "ukg"),
    (r"paylocity\.com", "paylocity"), (r"bamboohr\.com", "bamboohr"), (r"jazzhr\.com|applytojob\.com", "jazzhr"),
    (r"ceipal\.com", "ceipal"), (r"zohorecruit\.", "zoho recruit"), (r"brassring\.com", "brassring (kenexa)"),
    (r"adp\.com/|workforcenow\.adp", "adp"), (r"paycomonline|paycom\.com", "paycom"),
    (r"recruitee\.com", "recruitee"), (r"rippling\.com", "rippling"), (r"dayforcehcm\.com", "dayforce"),
]
# Job Seek monitor types that mean "scrapes the company's own site"
CUSTOM_MONITORS = {"dom", "sitemap", "api_sniffer", "nextdata", "rss", "inline", "talentbrew", "amazon",
                   "accenture", "linkedin", "join"}
# regional boards of global companies: not where US software jobs are posted
NON_US = re.compile(r"\.eu\.|jobs\.cz|jobconvo|mokahr|zhiye|empleos|\.ch/|\.ca/|\.co\.uk|\.de/|\.in/|linkedin\.com|"
                    r"fidelitycanada|deloittece|ibm\.recruitee|ey\.recruitee|cambridgeconsultants", re.I)
# checked by hand (careers pages, Job Seek / Simplify rows): employer key -> (ats, evidence)
OVERRIDES = {
    "apple": ("custom site", "https://jobs.apple.com"),
    "capgemini": ("custom site", "https://careers.capgemini.com"),
    "deloitte": ("avature", "https://apply.deloitte.com/en_US/careers/SearchJobs"),
    "ibm": ("custom site", "https://www.ibm.com/careers"),
    "ey": ("successfactors", "https://careers.ey.com/ey/search/"),
    "tata consultancy services": ("custom site", "https://ibegin.tcs.com"),
    "intuit": ("custom site", "https://jobs.intuit.com (Radancy)"),
    "credit karma": ("custom site", "part of Intuit: https://jobs.intuit.com"),
    "linkedin": ("custom site", "https://careers.linkedin.com (Lever 'linkedin' is a test board)"),
    "charles schwab and": ("icims", "https://career-schwab.icims.com"),
    "metlife": ("unknown", "Lever 'metlife' is MetLife Colombia sales"),
    "infinite computer": ("custom site", "https://www.infinite.com/careers"),
    "htc": ("custom site", "https://www.htcinc.com/careers (htc.com is HTC Vive)"),
    "dfs corporate": ("unknown", "Discover Financial; jobs.discover.com unreachable"),
    "docusign": ("unknown", "careers page links only an iCIMS privacy notice"),
    "dell": ("unknown", "Workday tenant 'dell' rejects every site (422); jobs.dell.com blocks scripts"),
    "confluent": ("custom site", "acquired by IBM: careers.confluent.io redirects to ibm.com/careers"),
    "fis management": ("phenom", "https://careers.fisglobal.com"),
    "u s bank national association": ("phenom", "https://careers.usbank.com"),
    "delta air lines": ("avature", "https://delta.avature.net/careers"),
    "depository trust and clearing": ("oracle", "https://ebxr.fa.us2.oraclecloud.com (DTCC)"),
    "united wholesale mortgage": ("icims", "https://careers-uwmcareers.icims.com"),
    "optum": ("taleo", "https://uhg.taleo.net"),
    "starbucks coffee": ("eightfold", "https://starbucks.eightfold.ai/careers"),
    "ford motor": ("oracle", "https://efds.fa.em5.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1"),
    "nokia of": ("oracle", "https://jobs.nokia.com/en/sites/CX_1"),
    "siemens industry software": ("avature", "https://jobs.siemens.com/en_US/externaljobs"),
    "ubs business": ("brassring (kenexa)", "https://jobs.ubs.com/TGnewUI"),
    "cgi and": ("njoyn", "https://cgi.njoyn.com"),
    "netflix": ("eightfold", "https://explore.jobs.netflix.net/careers"),
    "paycom payroll": ("paycom", "https://www.paycom.com/careers"),
    "charter communications": ("custom site", "https://jobs.spectrum.com"),
    "mathworks": ("custom site", "https://www.mathworks.com/company/jobs"),
    "ust": ("custom site", "https://www.ust.com/en/careers"),
    "compunnel software": ("custom site", "https://www.compunnel.com/jobs"),
    "innova": ("custom site", "https://innovasolutions.com/careers"),
    "zoom communications": ("custom site", "https://www.careers.zoom.us"),
    "experis": ("custom site", "https://www.experis.com (ManpowerGroup)"),
    # slug guesses that hit test boards or other companies
    "people tech": ("unknown", "Greenhouse 'peopletech' is a test board"),
    "insight": ("unknown", "Greenhouse 'insight' is Insight UK"),
    "avani": ("unknown", "Greenhouse 'avani' is Avani Media"),
    "western union": ("unknown", "Greenhouse 'westernunion' only has TEST postings"),
    "genesis": ("unknown", "Ashby 'genesis' is a robotics startup"),
    "softworld": ("unknown", "Lever 'softworld' lists EMEA recruiters"),
}


def ats_of(url: str, monitor: str = "") -> str:
    for rx, ats in HOSTS:
        if re.search(rx, url, re.I):
            return ats
    if monitor == "oracle_hcm":
        return "oracle"
    if monitor and monitor not in CUSTOM_MONITORS:
        return monitor
    return "custom site"


def jobseek_index(text: str) -> dict[str, list]:
    """Job Seek boards.csv -> canon key -> [(ats, board url)]."""
    idx = {}
    for r in csv.DictReader(text.splitlines()):
        if not NON_US.search(r["board_url"]):
            idx.setdefault(canon(r["company_slug"].replace("-", " ")), []).append(
                (ats_of(r["board_url"], r["monitor_type"]), r["board_url"]))
    return idx


def simplify_index(readmes: list[str]) -> dict[str, list]:
    """Simplify README rows: company cell, then the first link in the Application cell ("↳" = same company)."""
    idx, company = {}, None
    for md in readmes:
        for row in re.findall(r"<tr>(.*?)</tr>", md, re.S):
            cells = re.findall(r"<td>(.*?)</td>", row, re.S)
            if len(cells) < 4:
                continue
            name = re.sub(r"<[^>]+>", "", cells[0]).strip()
            company = company if name.startswith("↳") else name
            link = re.search(r'href="([^"]+)"', cells[3])
            if company and link and "simplify.jobs" not in link.group(1) and not NON_US.search(link.group(1)):
                idx.setdefault(canon(company), []).append((ats_of(link.group(1)), link.group(1).split("?")[0][:150]))
    return idx


def board_slug(ats: str, evidence: str) -> str | None:
    """Evidence -> companies.csv slug ('stripe', 'tenant|wdN|site')."""
    if m := re.match(r"\w+ slug ([\w.-]+)", evidence):
        return m.group(1)
    if m := re.match(r"[\w-]+\|wd\d+\|[\w-]+", evidence):
        return m.group(0)
    hit = parse_board(evidence)
    return hit[1] if hit and hit[0] == ats else None


async def detect(client, slug: str):
    """recon.detect's checks: (ats, slug, jobs) for the first board with jobs."""
    for ats, url in CHECKS.items():
        try:
            r = await client.get(url.format(s=slug))
            if r.status_code == 200:
                data = r.json()
                n = len(data) if isinstance(data, list) else len(data.get("jobs", []))
                if n:
                    return ats, slug, n
        except Exception:
            pass
    return None


async def careers_page(client, key: str):
    """Guessed homepage / careers page -> (ats, evidence). Least reliable source: the domain is a guess."""
    base = "".join(re.sub(r"[^a-z0-9 ]", " ", key).split())
    for url in [f"https://www.{base}.com/careers", f"https://www.{base}.com/", f"https://careers.{base}.com/"]:
        try:
            r = await client.get(url, follow_redirects=True)
        except Exception:
            continue
        if r.status_code != 200:
            continue
        text = str(r.url) + " " + r.text[:400_000]
        for rx, ats in HOSTS:
            if m := re.search(rf"https?://[^\s\"'<>]*(?:{rx})[^\s\"'<>]*", text, re.I):
                return ats, m.group(0)[:150]
        if "careers" in url:
            return "custom site", str(r.url)
    return None


async def live(client, ats: str, slug: str) -> bool:
    """Does the board answer with jobs right now?"""
    try:
        if ats == "workday":
            tenant, wd, site = slug.split("|")
            r = await client.post(f"https://{tenant}.{wd}.myworkdayjobs.com/wday/cxs/{tenant}/{site}/jobs",
                                  json={"limit": 1, "offset": 0, "searchText": "", "appliedFacets": {}})
            return r.status_code == 200 and r.json().get("total", 0) > 0
        r = await client.get(CHECKS[ats].format(s=slug))
        data = r.json() if r.status_code == 200 else []
        return bool(data if isinstance(data, list) else data.get("jobs"))
    except Exception:
        return False


async def find_ats(missing: list[dict]):
    """Sets ats / evidence / how (and slug / verified for boards we can poll) on each missing sponsor."""
    async with httpx.AsyncClient(timeout=30, headers=HEADERS) as client:
        boards = (await client.get(JOBSEEK)).text
        readmes = [(await client.get(u)).text for u in READMES.values()]
    sources = {"jobseek": jobseek_index(boards), "simplify": simplify_index(readmes)}
    for e in missing:
        if e["key"] in OVERRIDES:
            e["ats"], e["evidence"] = OVERRIDES[e["key"]]
            e["how"] = "checked by hand"
            continue
        hits = [(*b, how) for how, idx in sources.items() for k in keys(e["employer"]) | {e["key"]}
                for b in idx.get(k, [])]
        if hits:   # prefer a board we can poll today
            e["ats"], e["evidence"], e["how"] = sorted(
                hits, key=lambda b: (b[0] not in SUPPORTED, b[0] == "custom site"))[0]

    sem = asyncio.Semaphore(10)
    async with httpx.AsyncClient(timeout=15, headers=HEADERS) as client:
        async def resolve(e):
            async with sem:
                if e.get("ats") not in SUPPORTED and e.get("how") != "checked by hand":
                    words = re.sub(r"[^a-z0-9 ]", " ", e["key"]).split()
                    # whole-name slugs only: first-word guesses ("charles", "insight") hit other companies
                    for slug in dict.fromkeys(["".join(words), "-".join(words)]):
                        if len(slug) >= 3 and (hit := await detect(client, slug)):
                            e["ats"], e["evidence"], e["how"] = hit[0], f"{hit[0]} slug {hit[1]} ({hit[2]} jobs)", "detect"
                            break
                    if not e.get("ats"):
                        hit = await careers_page(client, e["key"])
                        e["ats"], e["evidence"], e["how"] = (*hit, "careers page") if hit else ("unknown", "", "none")
                if e["ats"] in SUPPORTED:
                    e["slug"] = board_slug(e["ats"], e["evidence"])
                    e["verified"] = bool(e["slug"]) and await live(client, e["ats"], e["slug"])
        await asyncio.gather(*(resolve(e) for e in missing))


# --- 4. Output ---

def write(ranked: list[dict], companies: list[dict], path: Path = SPONSORS):
    ats_of_company = {c["company"]: c["ats"] for c in companies}
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["employer", "swe_filings", "ats", "recon_company"])
        for e in ranked:
            ats = ats_of_company[e["covered"]] if e["covered"] else e.get("ats", "")
            w.writerow([e["employer"], e["filings"], ats, e["covered"] or ""])


def sponsor_rows(path: Path = SPONSORS) -> list[tuple[str, int, str]]:
    """(companies.csv name, filings, employers) for the sponsors table. Several DOL employers can
    map to one company (CVS Health also files as Aetna and Caremark): their filings add up."""
    filings, employers = Counter(), defaultdict(list)
    with open(path) as f:
        for r in csv.DictReader(f):
            if r["recon_company"]:
                filings[r["recon_company"]] += int(r["swe_filings"])
                employers[r["recon_company"]].append(r["employer"])
    return [(c, n, "; ".join(employers[c])) for c, n in filings.most_common()]


def load(path: Path = SPONSORS):
    rows = sponsor_rows(path)
    store = Store(url=os.environ.get("DATABASE_URL"))
    store.replace_sponsors(rows)
    store.commit()
    store.close()
    print(f"loaded {len(rows)} sponsors into the database")


def report(ranked: list[dict], top: int = TOP):
    for n in (100, 250, 500):
        print(f"top {n}: {sum(1 for e in ranked[:n] if e['covered'])} covered")
    groups = defaultdict(list)
    for i, e in enumerate(ranked[:top], 1):
        if not e["covered"]:
            groups[e["ats"]].append((i, e))
    rest = sorted((g for g in groups if g not in SUPPORTED + ["custom site", "unknown"]), key=lambda g: -len(groups[g]))
    for g in [g for g in SUPPORTED + rest + ["custom site", "unknown"] if g in groups]:
        print(f"\n== {g} ({len(groups[g])}, {sum(e['filings'] for _, e in groups[g])} filings)")
        for i, e in groups[g]:
            board = ""
            if g in SUPPORTED:
                board = f" {e.get('slug')}" + ("" if e.get("verified") else " (NOT VERIFIED)")
            print(f"  #{i} {e['employer']} ({e['filings']}){board} | {e['how']} | {e['evidence'][:90]}")
    near = [(i, e) for i, e in enumerate(ranked[:top], 1) if e.get("near")]
    if near:
        print("\nnot matched, similar names in companies.csv (check by hand):")
        for i, e in near:
            print(f"  #{i} {e['employer']} ~ {e['near']}")


def main(paths: list[str], top: int = TOP):
    ranked = rank(read_lca(paths))
    print(f"{sum(e['filings'] for e in ranked)} certified H-1B software filings, {len(ranked)} employers")
    with open(COMPANIES) as f:
        companies = list(csv.DictReader(f))
    match(ranked, companies, top)
    asyncio.run(find_ats([e for e in ranked[:top] if not e["covered"]]))
    write(ranked, companies)
    print(f"wrote {SPONSORS}: {len(ranked)} employers, {sum(1 for e in ranked if e['covered'])} in companies.csv")
    load()
    print()
    report(ranked, top)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("lca", nargs="*", help="DOL LCA disclosure xlsx files (one fiscal year: Q1-Q4)")
    parser.add_argument("--top", type=int, default=TOP, help=f"sponsors to check by hand (default {TOP})")
    parser.add_argument("--load", action="store_true", help="only copy config/sponsors.csv into the database")
    args = parser.parse_args()
    load_env()
    if args.load:
        load()
    elif args.lca:
        main(args.lca, args.top)
    else:
        parser.error("give the LCA xlsx files, or --load")
