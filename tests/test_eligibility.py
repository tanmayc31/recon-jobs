from recon.eligibility import check, early_start, experience_cap, grad_outside, min_years


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
    # Separate sentences: smallest wins (lenient)
    assert min_years("2+ years of software engineering experience. 6+ years of professional experience "
                     "leading teams.") == 2


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


def test_experience_cap():
    assert experience_cap(STRIPE_EARLY)
    # Real Notion, OpenAI, MongoDB
    assert check("SKILLS YOU'LL NEED TO BRING\n\n - You have less than two years of engineering experience. "
                 "You have solid fundamentals")[1] == "experience cap"
    assert check("- 0-1 years of experience in software engineering or a relevant field")[1] == "experience cap"
    assert check("Recent graduates (including Summer 2026) or professionals with up to 18 months of "
                 "experience.")[1] == "experience cap"
    # Caps on internship experience don't count; caps of 3+ years don't block
    assert not experience_cap("no more than 6 months of internship experience")
    assert not experience_cap("less than 5 years of professional experience")


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
