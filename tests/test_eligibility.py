from recon.eligibility import sections, check, early_start, experience_cap, grad_outside, min_years


def test_years():
    assert min_years("5+ years of professional software engineering experience") == 5
    assert min_years("We want 2-4 years of experience building backend systems") == 2
    assert min_years("Three years of industry experience") == 3
    assert min_years("Founded 10 years ago. Great team.") is None   # no experience word nearby
    assert min_years("No years mentioned here") is None


def test_years_gate():
    assert check("Requires 7+ years of software engineering experience")[:2] == (False, "7+ years")
    assert check("1+ years of experience with Python")[0]
    assert check("A great new grad role")[0]


def test_blockers():
    for text in ["Must be a U.S. citizen.", "U.S. citizenship is required for this role",
                 "Active TS/SCI clearance", "ability to obtain a security clearance",
                 "This role is subject to ITAR"]:
        assert check(text)[1] == "citizenship/clearance", text
    for text in ["We will not sponsor visas for this role", "No visa sponsorship available",
                 "Must be authorized to work in the US without the need for current or future sponsorship",
                 "Sponsorship is not available"]:
        assert check(text)[1] == "no sponsorship", text


def test_not_blocked():
    # OPT holders ARE authorized to work, so this alone is not a blocker
    assert check("Must be authorized to work in the United States")[0]
    assert check("We sponsor visas and welcome international applicants")[0]
    assert check("We build software for military customers")[0]   # "itar" inside "military"


def test_export_license_not_visa():
    # Real Cloudflare boilerplate: export law, not visa sponsorship
    cf = ("Cloudflare may not be able to release software or technology controlled under these "
          "U.S. export laws without sponsorship for an export license. Cloudflare is proud to be "
          "an equal opportunity employer.")
    assert check(cf)[0]
    assert check("Must be able to work without sponsorship.")[1] == "no sponsorship"


def test_soft_clearance():
    # Real Palantir phrase: clearance is a nice-to-have here
    pl = ("Active US Security clearance, or eligibility and willingness to obtain a US Security "
          "clearance is beneficial, but not necessary What We Require 3+ years of experience")
    assert check(pl)[0]
    assert check("Clearance is a plus. Must be a U.S. citizen.")[1] == "citizenship/clearance"
    # Real Palantir phrase, no soft word: still blocked
    assert check("Eligibility and willingness to obtain a US Security clearance Salary")[1] == \
        "citizenship/clearance"
    # Real Palantir bullets (no periods): "(preferred)" belongs to the previous bullet
    prev = ("Proficiency in a language such as Go (preferred), Python, or TypeScript Experience with "
            "infrastructure-as-code (Terraform, Helm, CloudFormation, or similar) An active TS/SCI "
            "security clearance, or eligibility and willingness to obtain one Salary")
    assert check(prev)[1] == "citizenship/clearance"


def test_clearance_under_what_we_value():
    # Real Palantir "Software Engineer, New Grad": clearance is a value, not a requirement
    value = ("What We Value Ability to communicate and collaborate with a variety of individuals, including "
             "engineers, users and non-technical team members. Willingness to learn and make decisions "
             "independently, and the ability to ask questions effectively. Active US Security clearance, or "
             "eligibility and willingness to obtain a US Security clearance. What We Require Engineering "
             "background in fields such as Computer Science, Mathematics, Software Engineering, and Physics.")
    ok, reason, _, flags = check(value)
    assert ok and flags == ["clearance preferred"]
    # Real Palantir "FDSE, New Grad - US Government": under What We Require, still blocked
    require = ("What We Value Willingness and interest to travel as needed to client sites. What We Require "
               "Active US Security clearance or eligibility and willingness to obtain a US Security clearance. "
               "Engineering background, preferred in fields such as Computer Science, Mathematics.")
    assert check(require)[1] == "citizenship/clearance"


def test_senior_role_in_description():
    # Real Cloudflare "Software Engineer, Mobile SDK"
    assert check("What you'll do We're looking for a Senior Software Engineer to join our WARP Mobile SDK "
                 "team")[1] == "senior role"
    assert check("As a senior software engineer, you will set standards for compatibility")[1] == "senior role"
    # Real Stripe: working with seniors is fine
    assert check("on for critical infrastructure, working alongside senior engineers to debug and resolve "
                 "production issues")[0]


def test_years_headline_number():
    # Real OpenAI "Software Engineer, Developer Productivity"
    dev_prod = ("Have 5+ years of experience in engineering, including 3+ years of experience in "
                "infrastructure building tooling for developers.")
    assert min_years(dev_prod) == 5
    assert check(dev_prod)[1] == "5+ years"
    # Separate requirement sentences stack: the largest wins (a 6-year minimum is a 6-year job)
    assert min_years("2+ years of software engineering experience. 6+ years of professional experience "
                     "leading teams.") == 6


def test_soft_years():
    assert min_years("6+ years of software engineering experience preferred.") is None
    assert min_years("2+ years of experience required. 7+ years of industry experience is a plus.") == 2
    assert check("Bonus: 8+ years of professional experience with Rust")[0]


# Real Stripe "Software Engineer, Early Career — Immediate Start"
STRIPE_EARLY = ("Minimum requirements Must be available to start full-time before December 1, 2026 A Bachelor’s "
                "or Master’s degree in computer science or a directly related field, obtained by summer 2026, or "
                "equivalent work experience New grad candidates should have no more than 18 months of "
                "professional experience (excluding internship experience) Experience and familiarity with "
                "programming")


def test_experience_cap_is_a_flag_not_a_skip():
    assert experience_cap(STRIPE_EARLY)
    # Real Notion, OpenAI, MongoDB: kept as matches, with the cap shown
    assert check("SKILLS YOU'LL NEED TO BRING\n\n - You have less than two years of engineering experience. "
                 "You have solid fundamentals")[::3] == (True, ["exp cap: max 2 yrs"])
    assert check("- 0-1 years of experience in software engineering or a relevant field")[::3] == \
        (True, ["exp cap: max 1 yr"])
    assert check("Recent graduates (including Summer 2026) or professionals with up to 18 months of "
                 "experience.")[::3] == (True, ["exp cap: max 18 mo"])
    # Caps on internship experience don't count; caps of 3+ years aren't flagged
    assert not experience_cap("no more than 6 months of internship experience")
    assert not experience_cap("less than 5 years of professional experience")
    # minimums of 5+ still skip
    assert check("5+ years of professional software engineering experience")[1] == "5+ years"


def test_start_date():
    assert early_start(STRIPE_EARLY)
    # Real Notion "New Grad (Dec 2026)": January start is fine
    notion = ("To be eligible for this role, you need to graduate by Dec 2026 and be able to start FTE by "
              "January/February 2027.")
    assert check(notion)[0]
    assert check("Must be able to start no later than November 2026.")[1] == "start date"
    ok, _, _, flags = check("Software Engineer, Early Career — Immediate Start. Great team.")
    assert ok and flags == ["early start?"]


def test_graduation_window():
    # Real Stripe "Security Engineer, New Grad"
    assert check("Currently enrolled in a Bachelor’s or Master’s program in Computer Science or related field "
                 "(graduating by Summer 2026) Some exp")[1] == "graduation date"
    # Real Databricks: Fall 2026–Summer 2027 includes Dec 2026; Fall 2027–Summer 2028 does not
    assert check("What we look for: You will graduate between Fall 2026 and Summer 2027 with a bachelors")[0]
    assert check("What we look for: You will graduate between fall 2027 and Summer 2028 with a degree in "
                 "Computer Science")[1] == "graduation date"
    # Real Stripe "obtained by summer 2027" is fine
    assert not grad_outside("in a directly related field, obtained by summer 2027, or equivalent work")


def test_us_person():
    # Real Palantir "Forward Deployed Software Engineer - Warp Speed" and its New Grad variant
    assert check("iteration with users What We Require U.S. Person Required 1+ years of relevant, post-college "
                 "work experience.")[1] == "citizenship/clearance"
    assert check("What We Require U.S. Person Required Must be graduating in December 2026 or Spring 2027 Strong "
                 "engineering background, preferred in fields such as Computer Science")[1] == "citizenship/clearance"
    # Real OpenAI "Backend Software Engineer, Gov"
    assert check("This position requires U.S. person status as defined by the applicable government "
                 "contract.")[1] == "citizenship/clearance"


def test_workday_federal_blockers():
    # Real Workday "Software Development Engineer (US Federal)" wording
    for text in [
        "Workday Federal works with the Federal Government which, due to federal government security "
        "requirements, mandates that all Workday personnel working on the contracts be United States "
        "citizens (naturalized or native).",
        "due to federal government security requirements, mandates all Workday personnel working on the "
        "contracts be United States citizens (naturalized or native ).",
        "Candidates must have the ability to obtain and maintain a U.S. government issued security clearance.",
        "This role may require a security clearance at the TS/SCI w/CI Poly level.",
        "An active TS/SCI w/CI Poly is preferred.",
        "Active TS-SCI clearance.", "Top Secret/SCI eligibility.", "TS SCI with polygraph.",
    ]:
        assert check(text)[1] == "citizenship/clearance", text


def test_clearance_wish_still_only_flags():
    for text in ["Security clearance preferred.", "An active security clearance is a plus.",
                 "Ability to obtain a U.S. government security clearance is a plus."]:
        ok, reason, _, flags = check(text)
        assert ok and reason is None and flags == ["clearance preferred"], text
    assert check("Eligible for a TSA PreCheck sci-fi club")[0]   # no TS/SCI false positive


def test_missed_sponsorship_phrasings():
    # Real sentences from New jobs that should have been blocked
    genworth = ("POSITION TITLE Software Engineer - Java Development This role is not eligible for "
                "employment visa sponsorship. POSITION LOCATION Lynchburg, VA")
    avride = ("Candidates are required to be authorized to work in the U.S. The employer is not offering "
              "relocation, sponsorship, and remote work options are not available.")
    accenture = ("Applicants for employment in the US must have work authorization that does not now or in the "
                 "future require sponsorship of a visa for employment authorization in the United States.")
    for text in (genworth, avride, accenture):
        assert check(text)[1] == "no sponsorship", text
    # "authorized to work in the US" alone is still not a blocker
    assert check("Candidates are required to be authorized to work in the U.S.")[0]


def test_active_top_secret_required_beats_later_preferred():
    # Real Accenture Federal "Power Platforms Developer" bullet run-on
    text = ("1+ year of experience with Power BI and SharePoint Active Top Secret required with ability to "
            "obtain SCI Preferred Qualifications: Microsoft Power Platform certifications")
    assert check(text)[1] == "citizenship/clearance"


def test_years_in_a_role():
    # Real F5 "Forward Deployed Engineer - AI Security"
    text = ("Skills & Experience : 8+ years in a Post-Sales technical role (e.g., TAM, Solutions Engineer, "
            "Integration Engineer, Implementation Engineer)")
    assert min_years(text) == 8
    assert check(text)[1] == "8+ years"


# Real Johnson Controls "Performance Engineer - Sustainable Infrastructure Services" (building/HVAC)
JCI = 'What you will do As a member of the Sustainability Infrastructure Services (SIS) Team, the site performance engineer will participate in design-build and SIS infrastructure projects as a Facility Management/Building Engineering subject matter expert providing support to the Site Customer Business Managers. You will design conceptual solutions and operating plans for our sites. You are to have advanced understanding of energy management, security fire systems, building automation systems and services, operations and maintenance, facilities management, and are to be able to combine these capabil AC, building automation, and fire and life safety. Building design or construction experience with excellent knowledge of building-related systems and services Experience working in healthcare environments is an asset 5+ years of experience in engineering and facility operations is preferred. Abilit'


def test_not_software_gate():
    assert check(JCI, "Performance Engineer - Sustainable Infrastructure Services")[1] == "not software"
    # real Goodfire "Platform Engineer": software + APIs
    goodfire = ("We're looking for Platform Engineers to build the infrastructure and services behind Goodfire's "
                "interpretability platform. Build shared services and APIs: create the foundations that research "
                "tools and customer products use. Working with software engineers and researchers.")
    assert check(goodfire, "Platform Engineer")[0]
    # real Salient "Cloud Infrastructure Engineer": AWS + GCP
    salient = ("We're hiring a Cloud Infrastructure Engineer to own Salient's cloud footprint across AWS, GCP, "
               "and Render. You will make our infrastructure consistent across providers.")
    assert check(salient, "Cloud Infrastructure Engineer")[0]
    # a software title needs no signals; no title (old callers) skips the gate
    assert check(JCI, "Software Engineer, Building Systems")[0]
    assert check(JCI)[0]


def test_software_signals():
    from recon.eligibility import software_signals
    assert software_signals("Go above and beyond. Code in Go and C++ against our APIs.") == {"code", "go", "c++", "api"}
    assert software_signals("We go the extra mile on building codes.") == set()


def test_not_software_gate_second_pass():
    # Real titles a first, narrower version skipped: SRE / Cloud titles are software
    assert check("Own fleet health and delivery for our GPU clusters on Kubernetes.",
                 "Site Reliability Engineer, Fleet Health & Delivery")[0]
    assert check("Design and maintain AWS environments for federal customers.", "Cloud Engineer (AWS)")[0]
    # Real Saronic "Civil/Site Engineer - Infrastructure": construction "programming" + an S3 URL in
    # the privacy notice are not software signals
    saronic = ("Participate in the early programming and development of various capital project scopes of "
               "work. CCPA Notice for Candidates and California Employees "
               "https://saronic-assets-public.s3.us-east-2.amazonaws.com/Saronic%20CCPA%20Notice")
    assert check(saronic, "Civil/Site Engineer \u2013 Infrastructure")[1] == "not software"


def test_cleared_roles_named_in_the_title():
    # real Microsoft (Eightfold) titles: CTJ = Cleared Talent Jobs; descriptions don't always say it
    for t in ["Software Engineer II- CTJ- POLY", "Software Engineering II - CTJ - Poly",
              "Site Reliability Engineer - CTJ - Secret", "Software Engineer - Cleared",
              "Software Engineer (TS/SCI)", "Cloud Engineer - Top Secret"]:
        assert check("Build cloud services in C# and Python.", t)[1] == "citizenship/clearance", t
    for t in ["Software Engineer, Secrets Management", "Software Engineer, Polymer Informatics", "Software Engineer II - Backend",
              "Software Engineer, Clearing Systems"]:
        assert check("Build cloud services in C# and Python.", t)[0], t


def test_active_government_top_secret_clearance():
    # real Microsoft "Software Engineer - Cleared" description
    text = ("Security screenings: The successful candidate must have an active U.S. Government Top Secret "
            "Security Clearance. Failure to maintain or obtain the appropriate clearance")
    assert check(text, "Software Engineer")[1] == "citizenship/clearance"


def test_any_required_clearance_blocks():
    # real EY "Government and Infrastructure - Service Delivery Center - AI Solution Developer"
    ey = ("Must be able to obtain and maintain a secret clearance or higher Must have a bachelor’s degree and a "
          "minimum of two years of related professional experience Must be comfortable working in-person as needed")
    assert check(ey, "Government and Infrastructure - Service Delivery Center - AI Solution Developer")[:3] == (
        False, "citizenship/clearance", 2)
    for text in ["Secret clearance or higher.", "Candidates must hold a Public Trust clearance.",
                 "Ability to obtain a Public Trust.", "Active Secret clearance required.",
                 "Must possess a DoD clearance."]:
        assert check(text)[1] == "citizenship/clearance", text
    for text in ["An active Secret clearance is a plus.", "Security clearance preferred."]:   # wishes stay flags
        assert check(text)[0] and "clearance preferred" in check(text)[3], text


def test_years_in_words_and_minimums_decide():
    assert min_years("A minimum of two (2) years of professional software experience.") == 2
    assert min_years("Minimum of three years of experience building web applications.") == 3
    # real Google "Software Engineer, Automatic Prompt Optimization": minimums stack, preferred never counts
    google = ("Minimum qualifications: Bachelor’s degree or equivalent practical experience. 2 years of experience "
              "with software development in one or more programming languages. 1 year of experience building "
              "recommendation or ranking models in production. Preferred qualifications: 5 years of experience with "
              "data structures and algorithms.")
    assert min_years(google) == 2
    # company boilerplate isn't an ask
    assert min_years("Requirements: 1+ years of experience with Python. Benefits: for over 12 years we have been "
                     "building great software.") == 1


def test_sections_ignore_headings_inside_sentences():
    s = sections("We translate defined requirements into working technology. Requirements: 2+ years of Java. "
                 "Preferred qualifications: Kafka. Equal Opportunity Employer: we welcome everyone.")
    assert s["minimum"] == "2+ years of Java." and s["preferred"] == "Kafka."
    assert s["other"].startswith("We translate defined requirements") and "welcome" in s["boilerplate"]


def test_degree_ladders_use_your_degree_line():
    # real Microsoft "Software Engineer II": the Master's line applies (YOUR_DEGREE master)
    ms = ("Master's Degree in Computer Science or related technical field AND 3+ years technical engineering experience "
          "with coding in languages including, but not limited to, C, C++, C#, Java, JavaScript, or Python OR Bachelor's "
          "Degree in Computer Science or related technical field AND 5+ years technical engineering experience with coding "
          "in languages including, but not limited to, C, C++, C#, Java, JavaScript, or Python OR equivalent experience.")
    assert min_years(ms) == 3
    # real Cisco: one sentence
    assert min_years("Bachelors + 5 years of related experience OR Masters + 3 years of related experience OR PhD + 0 "
                     "years of designing, developing, and deploying enterprise software in production") == 3
    # real KLA: the ladder across sentences ("one of the following")
    assert min_years("Minimum Qualifications Education and experience (one of the following): Bachelor’s degree in "
                     "computer science, with 5+ years of relevant experience. Master's degree in a related field with 3+ "
                     "years of relevant experience. Doctorate in a related field with 1+ year of relevant experience.") == 3
    # real Intel: a separate requirement after the ladder still counts
    assert min_years("Minimum Qualifications: Bachelor's degree in a relevant field with 6+ years of hands-on experience "
                     "in software integration; OR Master's degree with 4+ years of relevant experience; -OR- PhD with 2+ "
                     "years of relevant experience. 2+ years of experience in software build systems.") == 4


def test_degree_substitutes_and_ranges():
    # real M&T Bank: "in lieu of a degree" is for people without one
    assert min_years("Bachelor's degree and a minimum of 2 years' systems analysis experience. In lieu of a degree, a "
                     "combined minimum of 5 years' education and/or relevant work experience, including a minimum of 1 "
                     "year of systems analysis and/or application development work experience") == 2
    # real Paypay: "or 5+ years equivalent experience" replaces the degree
    assert min_years("Bachelor's Degree in Computer Engineering or Computer Science or 5+ years equivalent experience "
                     "in SaaS platform development") is None
    # real U.S. Bank: a range in words is its low end
    assert min_years("Bachelor's degree, or equivalent work experience - Three to five years of relevant experience") == 3
    assert min_years("Bachelor’s Degree and four to six years of experience or equivalent education") == 4
    # real stacked minimums still take the largest (OpenAI)
    assert min_years("- 7+ years of experience as a software engineer") == 7


def test_a_preferred_inside_a_parenthetical_list_doesnt_soften_the_ask():
    # Highmark Health (Nov 2026): the "preferred" is about which language, not the 3 years
    text = ("EXPERIENCE Required 3 years of Experience in at least one modern programming languages "
            "(Java, Python , JavaScript, ACE, IIB/ITX, Informatica preferred), and experience with at least two "
            "of the following: React, Angular v4+, NodeJS.")
    assert min_years(text) == 3
    assert min_years("Python experience. 5+ years of backend experience (preferred).") is None


def test_citizenship_or_permanent_residency_restrictions_block():
    # Robinhood "Software Engineer, Web, Government Products" (Menlo Park / New York), Nov 2026
    robinhood = ("Position Restriction: This position is restricted to US citizens or lawful permanent residents "
                 "In addition to the base pay range listed below, this role is also eligible for bonus opportunities.")
    assert check(robinhood, "Software Engineer, Web, Government Products")[:2] == (False, "citizenship/clearance")
    for text in ["This role is restricted to U.S. citizens.",
                 "Open to US citizens or permanent residents only.",
                 "Applicants must be U.S. citizens or green card holders.",
                 "Green card holders only, please.",
                 "You must be a U.S. citizen or permanent resident to apply.",
                 "US persons only.",
                 "Due to contract requirements, this position requires U.S. citizenship.",
                 "Candidates must hold US citizenship or permanent residency.",
                 "We can only consider US citizens for this role."]:
        assert check(text)[:2] == (False, "citizenship/clearance"), text


def test_work_authorization_or_a_visa_alternative_is_not_a_citizenship_block():
    assert check("Candidates must be authorized to work in the United States.")[0]
    # ALS: "Citizen or Permanent Resident ... or ... a valid work visa"
    assert check("To be eligible to work at ALS you must be a Citizen or Permanent Resident of the country you "
                 "are applying for, or either hold or be able to obtain a valid work visa.")[0]


def test_a_sanctions_question_about_other_countries_is_not_a_citizenship_block():
    # Databricks "Software Engineer New Grad" application questions
    assert check("Note: This information will only be used to ensure compliance with U.S. sanctions and export "
                 "controls. * Citizen or permanent resident of Cuba, Iran, North Korea, or Syria")[0]
    # Trimble SRE: a US person, explained as citizen or permanent resident, still blocks
    assert not check("Per FedRAMP and DoD requirements, you must be a verifiable US person on US soil (citizen or "
                     "permanent resident, state or territory).")[0]


def test_a_degree_length_is_not_years_of_experience():
    # Abbott "Software Development Quality Engineer II"
    text = ("Education Bachelors Degree (± 16 years) in an Engineering or Technical Field (OR) an equivalent "
            "combination of education and work experience. Experience/Background Minimum 2 years 2–5+ years of "
            "combined experience in software development and/or embedded systems applications")
    assert min_years(text) == 2


def test_the_no_degree_rung_of_a_ladder_doesnt_count():
    # Cox "Software Engineer II" Min Qualifications
    text = ("Min Qualifications Bachelor’s degree in a related discipline and 2 years’ experience in a related "
            "field. The right candidate could also have a different combination, such as a master’s degree and up "
            "to 2years’ experience; or 6 years’ experience in a related field Hands-on software development "
            "experience with at least one of the following: Java, Python, JavaScript, or TypeScript.")
    assert min_years(text) == 2
    assert min_years("Minimum qualifications: 3+ years of backend experience, or 5 years of full-stack experience.") == 5
