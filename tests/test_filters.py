from recon.filters import is_match
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


def test_drops_senior_and_non_eng():
    assert not is_match(job("Senior Software Engineer"))
    assert not is_match(job("Staff Backend Engineer"))
    assert not is_match(job("Engineering Manager, Cloud"))
    assert not is_match(job("Software Engineer Intern"))
    assert not is_match(job("Cloud Sales Account Executive"))


def test_drops_non_us():
    assert not is_match(job("Software Engineer", "London, UK"))
    assert not is_match(job("Software Engineer", "Bangalore, India"))
