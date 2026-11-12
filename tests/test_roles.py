from recon.roles import role_type


def test_role_types_from_real_titles():
    cases = {
        "Software Development Engineer, AWS EC2 Nitro Team": "swe",
        "Software Engineer II": "swe",
        "Python Developer": "swe",
        "Software Engineer, Backend": "backend",
        "Full stack Developer with Python": "fullstack",
        "Front End Engineer II, Amazon Connect - Contact Control Panel": "frontend",
        "Site Reliability Engineer 2 - Freewheel": "cloud",
        "System Development Engineer, AFT - Platform Engineering & Services": "cloud",
        "Cloud Engineer (AWS)": "cloud",
        "Forward Deployed Engineer - AI Security": "fde",     # FDE before ML/AI
        "Machine Learning Engineer": "ml",
        "Software Engineer, AWS Applied AI Solutions": "ml",
        "Security Engineer II, AWS Vulnerability Management": "other",
    }
    assert {t: role_type(t) for t in cases} == cases
