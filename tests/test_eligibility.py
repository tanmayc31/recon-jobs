from recon.eligibility import check, min_years


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


def test_soft_years():
    assert min_years("6+ years of software engineering experience preferred.") is None
    assert min_years("2+ years of experience required. 7+ years of industry experience is a plus.") == 2
    assert check("Bonus: 8+ years of professional experience with Rust")[0]
