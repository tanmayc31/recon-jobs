from recon.sponsors import NON_US, ats_of, board_slug, canon, match, rank, list_index, sponsor_rows


def lca(case, employer, soc="15-1252.00", title="Software Engineer", status="Certified", visa="H-1B"):
    return {"CASE_NUMBER": case, "EMPLOYER_NAME": employer, "SOC_CODE": soc, "JOB_TITLE": title,
            "CASE_STATUS": status, "VISA_CLASS": visa}


def test_name_variants_merge():
    # real FY2025 filer names
    assert canon("Amazon.com Services LLC") == canon("Amazon Web Services, Inc.") == canon("Amazon Development Center U.S., Inc.")
    assert canon("Government Employee Insurance Company (GEICO)") == canon("Government Employees Insurance Company (GEICO)")
    assert canon("Palo Alto Networks, Inc.") == "palo alto networks"
    assert canon("EMC Corporation") == canon("Dell USA L.P.")
    # look-alikes stay apart
    assert canon("Fidelity National Information Services, Inc.") != canon("FMR LLC d/b/a Fidelity Investments")
    assert canon("Apple Bank for Savings") != canon("Apple Inc.")


def test_rank_counts_certified_h1b_software_cases_once():
    rows = [
        lca("I-200-1", "Amazon.com Services LLC"),
        lca("I-200-2", "Amazon Web Services, Inc.", soc="15-1299.08", title="Systems Development Engineer"),
        lca("I-200-2", "Amazon Web Services, Inc."),                          # same case in a later quarter
        lca("I-200-3", "Stripe, Inc.", soc="13-2011.00", title="Software Engineer, Payments"),   # title counts
        lca("I-200-4", "Stripe, Inc.", soc="13-2011.00", title="Accountant"),
        lca("I-200-5", "Stripe, Inc.", status="Certified - Withdrawn"),
        lca("I-200-6", "Stripe, Inc.", status="Denied"),
        lca("I-200-7", "Canva US, Inc.", visa="E-3 Australian"),
    ]
    assert [(e["employer"], e["filings"]) for e in rank(rows)] == [("Amazon", 2), ("Stripe", 1)]


def test_match_to_companies_csv():
    companies = [{"company": c, "ats": "workday", "slug": "x"} for c in
                 ["AT&T", "Robinhood", "Apple Bank", "Instacart", "Cox", "Rubrik Job Board"]]
    ranked = [{"key": canon(n), "employer": n, "filings": 1} for n in
              ["AT&T SERVICES, INC.", "Robinhood Markets, Inc.", "Apple Inc.", "Maplebear Inc.",
               "Cox Automotive Corporate Services, LLC", "Rubrik, Inc."]]
    match(ranked, companies, top=5)
    assert [e["covered"] for e in ranked] == ["AT&T", "Robinhood", None, "Instacart", "Cox", None]   # Rubrik: below top


def test_ats_from_board_urls():
    assert ats_of("https://wd1.myworkdaysite.com/recruiting/wf/WellsFargoJobs") == "workday"
    assert ats_of("https://jpmc.fa.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1001") == "oracle"
    assert ats_of("https://www.amazon.jobs/en/search", "amazon") == "custom site"
    assert ats_of("https://apply.careers.microsoft.com/careers", "eightfold") == "eightfold"
    assert NON_US.search("https://job-boards.eu.greenhouse.io/cambridgeconsultantslimited")
    assert NON_US.search("https://ey.jobs.cz/")
    assert not NON_US.search("https://fmr.wd1.myworkdayjobs.com/fidelitycareers")


def test_board_slug():
    assert board_slug("workday", "https://wd5.myworkdaysite.com/recruiting/chewy/External/job/Boston-MA/x") \
        == "chewy|wd5|External"
    assert board_slug("workday", "comcast|wd115|Comcast_Careers") == "comcast|wd115|Comcast_Careers"
    assert board_slug("ashby", "ashby slug inovalon (42 jobs)") == "inovalon"
    assert board_slug("ashby", "https://jobs.ashbyhq.com/rivianvw.tech/e1647212/application") == "rivianvw.tech"


def test_job_list_index():
    links = [{"company": "Chewy", "url": "https://wd5.myworkdaysite.com/recruiting/chewy/External/job/1?src=list"},
             {"company": "Chewy", "url": "https://www.linkedin.com/jobs/view/1"}]          # non-US/aggregator: dropped
    assert list_index(links) == {"chewy": [("workday", "https://wd5.myworkdaysite.com/recruiting/chewy/External/job/1")]}


def test_sponsor_rows_add_up_employers_per_company(tmp_path):
    path = tmp_path / "sponsors.csv"
    path.write_text("employer,swe_filings,ats,recon_company\n"
                    "CVS Health,591,workday,CVS Health\nCaremark LLC,295,workday,CVS Health\n"
                    "Aetna Resources LLC,226,workday,CVS Health\nFidelity,2069,workday,Fidelity Investments\n"
                    "Cognizant,10317,custom site,\n")
    assert sponsor_rows(path) == [("Fidelity Investments", 2069, "Fidelity"),
                                  ("CVS Health", 1112, "CVS Health; Caremark LLC; Aetna Resources LLC")]
