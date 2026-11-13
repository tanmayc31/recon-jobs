import asyncio

import httpx

from recon.eligibility import check
from recon.sources import listings

CO = {"company": "New-Grad-2027 list", "ats": "listings", "slug": "vanshb03/New-Grad-2027", "tier": "2"}
RLI = ("https://wd1.myworkdaysite.com/recruiting/rlicorp/RLI_Corp_Careers/job/Peoria-IL/"
       "Associate-Software-Engineer--Net----Peoria--IL-or-Tempe--AZ_R1864")


def row(n, company, title, locations=("Peoria, IL",), sponsorship="Other", active=True):
    # shape of a real vanshb03/New-Grad-2027 listings.json row
    return {"id": f"id-{n}", "company_name": company, "title": title, "locations": list(locations),
            "url": f"https://go.vansh.nyc/{n}", "sponsorship": sponsorship, "active": active, "is_visible": True,
            "date_posted": 1794441600, "date_updated": 1794530616, "source": "vanshb03", "company_url": ""}


ROWS = [
    row(1, "RLI", "Associate Software Engineer", ("Peoria, IL", "Tempe, AZ")),   # -> Workday
    row(2, "Stripe", "Software Engineer, New Grad", ("Seattle, WA",)),           # -> Greenhouse
    row(3, "Google", "Software Engineer, Early Career", ("Mountain View, CA",)),  # -> google.com page
    row(4, "Lockheed Martin", "Software Engineer Associate", ("Fort Worth, TX",),
        sponsorship="U.S. Citizenship is Required"),                             # -> unreadable page
    row(5, "Amazon", "Software Development Engineer I", ("Seattle, WA",)),       # -> amazon.jobs: skipped
    row(6, "Shopify", "Software Engineer", ("Toronto, ON",)),                    # not US: never resolved
    row(7, "Old Co", "Software Engineer", active=False),                         # inactive
    row(8, "Done Co", "Software Engineer"),                                      # already saved
]
TARGETS = {
    "1": RLI,
    "2": "https://job-boards.greenhouse.io/stripe/jobs/7012345",
    "3": "https://www.google.com/about/careers/applications/jobs/results/1234-software-engineer-early-career",
    "4": "https://www.lockheedmartinjobs.com/job/fort-worth/software-engineer-associate/694/123",
    "5": "https://www.amazon.jobs/en/jobs/10599912/software-engineer-i-commerce",
}


def run(monkeypatch, company=None):
    monkeypatch.setattr(listings, "DELAY", 0)
    asked = []

    def handler(req):
        url = str(req.url)
        asked.append(url)
        if url == listings.LISTS["vanshb03/New-Grad-2027"]:
            return httpx.Response(200, json=ROWS)
        if url.startswith("https://go.vansh.nyc/"):
            return httpx.Response(302, headers={"location": TARGETS[url.rsplit("/", 1)[1]]})
        if "/wday/cxs/rlicorp/RLI_Corp_Careers/job/" in url:
            return httpx.Response(200, json={"jobPostingInfo": {
                "jobReqId": "R1864", "externalUrl": RLI, "jobDescription": "<p>Build .NET services. 0-2 years.</p>"}})
        if url == "https://boards-api.greenhouse.io/v1/boards/stripe/jobs/7012345":
            return httpx.Response(200, json={"content": "&lt;p&gt;Build payments APIs in Ruby and Go.&lt;/p&gt;"})
        if "google.com" in url:
            body = "<html><body><h1>Software Engineer, Early Career</h1>" + "<p>Write code at scale.</p>" * 60
            return httpx.Response(200, text=body, headers={"content-type": "text/html"})
        if "lockheedmartinjobs" in url:
            return httpx.Response(200, text="<html><div id=app></div></html>", headers={"content-type": "text/html"})
        return httpx.Response(404)
    co = {**CO, "list_ids": {"id-8"}, "known": set(), "covered": set(), **(company or {})}
    jobs = asyncio.run(listings.fetch(httpx.AsyncClient(transport=httpx.MockTransport(handler)), co))
    return {j.company: j for j in jobs}, asked, co


def test_resolves_list_rows_to_real_postings(monkeypatch):
    jobs, asked, co = run(monkeypatch)
    assert set(jobs) == {"RLI", "Stripe", "Google", "Lockheed Martin"}       # Amazon, Toronto, inactive, saved: no
    assert not any("/6" in u or "/7" in u or "/8" in u for u in asked if "go.vansh" in u)   # never resolved
    assert co["partial"] is True                                             # a list never auto-closes jobs
    rli = jobs["RLI"]                                                        # same ID as our Workday adapter's
    assert (rli.job_id, rli.source, rli.url, rli.via) == ("workday:rlicorp:R1864", "workday", RLI, "list")
    assert "Build .NET services" in rli.description and rli.location == "Peoria, IL; Tempe, AZ"
    assert jobs["Stripe"].job_id == "greenhouse:stripe:7012345" and "payments APIs" in jobs["Stripe"].description
    google = jobs["Google"]                                                  # a company site: its page text
    assert (google.job_id, google.source, google.source_ids) == ("list:id-3", "list", "id-3")
    assert "Write code at scale" in google.description and google.posted_at == "2026-11-12"


def test_unreadable_page_uses_the_list_and_keeps_its_gates(monkeypatch):
    lm = run(monkeypatch)[0]["Lockheed Martin"]
    assert lm.description.startswith("Software Engineer Associate at Lockheed Martin, Fort Worth, TX.")
    assert check(lm.description, lm.title)[1] == "citizenship/clearance"    # the list's column still gates


def test_skips_jobs_our_adapters_have(monkeypatch):
    jobs, asked, _ = run(monkeypatch, {"known": {"greenhouse:stripe:7012345"},
                                       "covered": {("google", "software engineer, early career", "mountain view, ca")}})
    assert "Stripe" not in jobs and "Google" not in jobs                     # same job ID / same company+title+place
    assert not any(u.endswith("go.vansh.nyc/3") for u in asked)              # covered: not even resolved
