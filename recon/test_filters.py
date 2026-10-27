from recon.filters import classify, is_match
from recon.models import Job


def job(title, location="New York, NY"):
    return Job("x", "Co", title, location, "", None, "greenhouse", 1)


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


def test_gov_flag():
    keep, flags = classify(job("Forward Deployed Software Engineer - US Government", "Washington, D.C."))
    assert keep and flags == ["gov/clearance?"]
