from recon.filters import classify, is_match
from recon.models import Job


def job(title, location="New York, NY", description=""):
    return Job("x", "Co", title, location, "", None, "greenhouse", 1, description)


def test_keeps_entry_roles():
    assert is_match(job("Software Engineer, New Grad"))
    assert is_match(job("Software Development Engineer - Early Career 2027"))
    assert is_match(job("Full Stack Engineer"))
    assert is_match(job("Cloud Engineer I", "Remote - US"))
    assert is_match(job("Forward Deployed Engineer"))
    assert is_match(job("Software Engineer II"))
    assert is_match(job("Software Engineer 2, Backend"))


def test_drops_senior_students_non_eng():
    for t in ["Senior Software Engineer", "Staff Backend Engineer", "Engineering Manager, Cloud",
              "Software Engineer Intern", "Software Engineer, Internship",
              "High School Internship, Software Engineering (Summer 2027)",
              "Software Engineer 3, Atlas Clusters Platform", "Systems PhD - Software Engineer",
              "FP&A Analyst, Cloud Finance", "Deployment Strategist - Japan Forward Deployed",
              "Technical Consultant, Strategic, Oracle Cloud", "Solutions Engineer",
              "Cloud Sales Account Executive",
              "Data Center Infrastructure Electrical Engineer",
              "Mechanical Engineer, PCBA Test Infrastructure, Robotics",
              "Hardware / Software CoDesign Engineer  - 3P", "Support Engineer, AI Infrastructure",
              "Software Quality Assurance Engineer",
              "Infrastructure Network & Supply Engineer - FTC (6 months)",
              "Security Engineer, Infrastructure Security",
              "Full Stack Engineer - 4 (Java, JavaScript, TypeScript, AWS)",
              "Software Engineer – 5"]:
        assert not is_match(job(t)), t


def test_location():
    assert not is_match(job("Software Engineer", "London, UK"))
    assert not is_match(job("Software Engineer", "Remote - Bangalore, India"))
    assert not is_match(job("Software Engineer", "Remote - Brazil"))
    assert not is_match(job("Software Engineer", "Toronto, Vancouver, Canada-Remote"))
    assert is_match(job("Software Engineer", "SEA, SF, NY, Toronto"))
    assert is_match(job("Software Engineer", "US-Remote, Chicago"))
    for loc in ["Belgrade, Serbia", "Gurugram", "Sao Paulo", "Barcelona", "Taiwan",
                "Bucharest", "Zurich, Switzerland", "Abu Dhabi, UAE"]:
        assert not is_match(job("Software Engineer", loc)), loc
    for loc in ["Remote", "Hybrid", "N/A", "In-Office", ""]:
        keep, flags = classify(job("Software Engineer", loc))
        assert keep and "location?" in flags, loc
    assert is_match(job("Software Engineer, Security Rules", "Austin, TX"))


def test_vague_location_reads_description():
    # Real Cloudflare postings: location field says "Hybrid", the city is in the description
    intro = "to keep the Internet moving forward, you'll fit right in. "
    london = intro + "Available Locations: London About Engineering at Cloudflare Cloudflare's Engineering team"
    assert not is_match(job("Software Engineer, CDN Configuration Group", "Hybrid", london))
    austin = intro + "Available Locations: Austin, TX What you'll do We're building"
    keep, flags = classify(job("Software Engineer, Security Rules", "Hybrid", austin))
    assert keep and flags == []
    # "or" between cities must not read as Oregon
    eu = intro + "Available Locations: London or Lisbon About the Department Emerging Technologies"
    assert not is_match(job("Software Engineer, Agentic Commerce", "Hybrid; In-Office", eu))
    mixed = intro + ("Available Locations: Austin, TX | New York, NY | San Francisco, CA or London, UK "
                     "(Hybrid) About the team")
    assert is_match(job("Software Engineer, R2 Gateway", "In-Office", mixed))
    # No "Available Locations" line: still kept, still flagged
    assert classify(job("Software Engineer", "Hybrid; In-Office"))[1] == ["location?"]


def test_cloud_whole_word():
    assert not is_match(job("Response Engineer - Cloudflare Managed Defense Center (CMDC)"))
    assert is_match(job("Cloud Engineer I", "Remote - US"))


def test_drops_specialty_tracks():
    for t in ["Software Engineer, TPU Compilers", "Software Engineer, Accelerators",
              "Software Engineer, AI accelerator Runtime", "Software Engineer, Kernel Performance & AI Tooling",
              "Systems Software Engineer, Silicon Bringup", "Firmware Engineer, RTOS, Consumer Devices",
              "Embedded Engineer, Compliance [Office of the CTO]", "Control Systems Software Engineer, Robotics",
              "Backend Engineer, Consumer Devices", "Software Engineer, GPU Infrastructure - HPC",
              "Software Engineer, RDMA Networking"]:
        assert not is_match(job(t)), t
    assert is_match(job("Frontend Software Engineer, ChatGPT Space", "San Francisco"))


def test_gov_flag():
    keep, flags = classify(job("Forward Deployed Software Engineer - US Government", "Washington, D.C."))
    assert keep and flags == ["gov/clearance?"]


def test_drops_internships_and_coops_with_a_reason():
    # real titles: Nvidia's plural "Internships" slipped past the old rule
    for t in ["NVIDIA 2027 Internships: Software Engineering", "NVIDIA 2027 Internships: Systems Software Engineer",
              "Software Engineer Intern", "Software Engineering Interns - Summer 2027",
              "Software Engineer Co-op (Spring 2027)", "Software Developer Co-ops", "Software Engineer, Coop"]:
        assert classify(job(t)) == (False, ["intern/co-op"]), t
    assert is_match(job("Software Engineer, Internal Tools"))       # "Internal" isn't "intern"
    assert is_match(job("Backend Engineer, International Payments"))
    assert classify(job("Senior Software Engineer")) == (False, ["title: Senior"])   # the word that dropped it
    assert classify(job("Sr Backend Software Engineer I")) == (False, ["title: Sr"])


def test_leading_country_code_is_not_a_us_state():
    # real Workday locations (DXC, Iberdrola-style "ESP - MD - LAS ROZAS"): MD here is Madrid, not Maryland
    for loc in ["ESP - MD - LAS ROZAS", "ESP - MD - LAS ROZAS; ESP - AR - ZARAGOZA",
                "ITA - MI - CERNUSCO SUL NAVIGLIO", "CRI - SJ - SAN JOSE",
                "AUS - VIC - MELBOURNE; AUS - WA - PERTH; AUS - NSW - MACQUARIE PARK"]:
        assert classify(job("Forward Deployed Engineer", loc)) == (False, ["non-US location"]), loc
    # US city codes in the same spot, and a US site listed next to a foreign one
    for loc in ["USA - Daytona Beach, FL", "RTP - Durham, NC", "NYC - New York", "ESP - MD - LAS ROZAS; USA - Austin, TX"]:
        assert is_match(job("Cloud Engineer", loc)), loc


def test_any_state_code_after_a_comma_is_us():
    # real list rows (vanshb03/New-Grad-2027): states the bare-word rule didn't know
    for loc in ["Columbus, OH", "Indianapolis, IN", "Minneapolis, MN", "Madison, WI", "Peoria, IL; Tempe, AZ",
                "Kansas City, MO", "Nashville, TN"]:
        assert is_match(job("Software Engineer", loc)), loc
    for loc in ["Remote in Canada", "Toronto, ON", "Pune, MH", "Zurich, ZH", "Vancouver, BC"]:
        assert not is_match(job("Software Engineer", loc)), loc
