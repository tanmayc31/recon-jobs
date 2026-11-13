from recon.discover import dedupe, from_jobseek, from_list, jobright_companies, parse_board


def test_parse_real_simplify_links():
    assert parse_board("https://job-boards.greenhouse.io/twitch/jobs/8931345002?utm_source=Simplify&ref=Simplify") \
        == ("greenhouse", "twitch")
    assert parse_board("https://jobs.lever.co/crosscountry-consulting/10ecb553-0393-4e7b-af5a-88a1947a0769/apply"
                       "?utm_source=Simplify&ref=Simplify") == ("lever", "crosscountry-consulting")
    assert parse_board("https://jobs.ashbyhq.com/sierra/d0e78ab0-92ac-4fec-a667-837fa371b1db/application"
                       "?embed=true&utm_source=Simplify&ref=Simplify") == ("ashby", "sierra")
    assert parse_board("https://caci.wd1.myworkdayjobs.com/external/job/Remote-Any-State/"
                       "Junior-Software-Developer_334685?utm_source=Simplify&ref=Simplify") \
        == ("workday", "caci|wd1|external")
    assert parse_board("https://nvidia.wd5.myworkdayjobs.com/en-US/NVIDIAExternalCareerSite/job/x") \
        == ("workday", "nvidia|wd5|NVIDIAExternalCareerSite")
    # myworkdaysite.com links (real Wells Fargo, Chewy, HCA): the API is served on myworkdayjobs.com
    assert parse_board("https://wd1.myworkdaysite.com/recruiting/wf/WellsFargoJobs") \
        == ("workday", "wf|wd1|WellsFargoJobs")
    assert parse_board("https://wd5.myworkdaysite.com/en-US/recruiting/chewy/External/job/Boston-MA/"
                       "Software-Engineer-I_R123") == ("workday", "chewy|wd5|External")


def test_skips_embed_eu_and_other_ats():
    assert parse_board("https://boards.greenhouse.io/embed/job_app?token=8847747002&utm_source=Simplify") is None
    assert parse_board("https://job-boards.eu.greenhouse.io/acme/jobs/1") is None
    assert parse_board("https://jobs.eu.lever.co/acme/1") is None
    assert parse_board("https://careers-peraton.icims.com/jobs/164003/job") is None


def test_job_list_links_become_boards():
    # real vanshb03/New-Grad-2027 rows, go links already resolved
    links = [{"company": "RLI", "url": "https://wd1.myworkdaysite.com/recruiting/rlicorp/RLI_Corp_Careers/job/"
                                       "Peoria-IL/Associate-Software-Engineer_R1864"},
             {"company": "Twitch", "url": "https://job-boards.greenhouse.io/twitch/jobs/8931345002"},
             {"company": "Google", "url": "https://www.google.com/about/careers/applications/jobs/results/1"}]
    assert from_list(links) == [{"company": "RLI", "ats": "workday", "slug": "rlicorp|wd1|RLI_Corp_Careers"},
                                {"company": "Twitch", "ats": "greenhouse", "slug": "twitch"}]


def test_jobright_company_column_only():
    # real rows: the company cell links the company's homepage; job links (jobright.ai) are never read
    md = """| Company | Job Title | Location | Work Model | Date Posted |
| ----- | --------- | --------- | ---- | ------- |
| **[Apple](https://www.apple.com)** | **[Software Engineer](https://jobright.ai/jobs/info/1?utm_source=1103)** | Cupertino, CA | On Site | Nov 12 |
| ↳ | **[Software Engineer II](https://jobright.ai/jobs/info/2)** | Austin, TX | On Site | Nov 12 |
| **[CLA (CliftonLarsonAllen)](http://www.claconnect.com)** | **[Associate Developer](https://jobright.ai/jobs/info/3)** | Remote | Remote | Nov 11 |"""
    assert jobright_companies(md) == {"Apple": "https://www.apple.com", "CLA (CliftonLarsonAllen)": "http://www.claconnect.com"}


def test_jobseek_rows_keep_supported_ats_only():
    text = '''company_slug,board_slug,board_url,monitor_type,monitor_config,scraper_type,scraper_config
0x,0x-ashby,https://jobs.ashbyhq.com/0x,ashby,"{""token"": ""0x""}",skip,
1-800-contacts,1-800-contacts-greenhouse,https://job-boards.greenhouse.io/1800contacts,greenhouse,"{""token"": ""1800contacts""}",skip,
2020-companies,2020-companies-workday,https://2020companies.wd1.myworkdayjobs.com/external_careers,workday,,skip,
acme,acme-icims,https://careers-acme.icims.com/jobs,icims,,skip,'''
    assert from_jobseek(text) == [
        {"company": "0x", "ats": "ashby", "slug": "0x"},
        {"company": "1 800 Contacts", "ats": "greenhouse", "slug": "1800contacts"},
        {"company": "2020 Companies", "ats": "workday", "slug": "2020companies|wd1|external_careers"},
    ]


def test_dedupe_against_companies_csv():
    existing = [{"company": "Nvidia", "ats": "workday", "slug": "nvidia|wd5|NVIDIAExternalCareerSite"},
                {"company": "Stripe", "ats": "greenhouse", "slug": "stripe"}]
    found = [{"company": "NVIDIA", "ats": "workday", "slug": "nvidia|wd1|nvidiaexternalcareersite"},  # same board
             {"company": "Stripe", "ats": "ashby", "slug": "stripe"},                                 # same name
             {"company": "Twitch", "ats": "greenhouse", "slug": "twitch"},
             {"company": "Twitch", "ats": "greenhouse", "slug": "Twitch"}]                            # repeat
    assert dedupe(found, existing) == [{"company": "Twitch", "ats": "greenhouse", "slug": "twitch"}]


def test_boards_named_wrongly_are_never_added():
    # Job Seek names Cambridge Consultants' board "Capgemini" and Home Chef's "Kroger"
    got = dedupe([{"company": "Capgemini", "ats": "greenhouse", "slug": "cambridgeconsultantslimited"},
                  {"company": "Kroger", "ats": "greenhouse", "slug": "homechef"},
                  {"company": "RLI", "ats": "workday", "slug": "rlicorp|wd1|RLI_Corp_Careers"}], [])
    assert [c["company"] for c in got] == ["RLI"]
