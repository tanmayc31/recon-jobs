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
              "Security Engineer, Infrastructure Security"]:
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
