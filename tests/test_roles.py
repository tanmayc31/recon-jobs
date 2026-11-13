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


def test_level_from_title_then_ai_then_years():
    from recon.roles import level
    # real titles
    for t in ["Software Engineer, New Grad 2027", "Software Development Engineer - Early Career 2027",
              "Software Engineer I", "SDE I", "Associate Software Engineer", "Full-stack Engineer 1",
              "Software Engineer, University Grad", "Junior Backend Developer", "Cloud Engineer I"]:
        assert level(t) == "entry", t
    for t in ["Software Engineer II", "Software Engineer 2, Backend", "Software Dev Engineer II, Programming Foundations"]:
        assert level(t) == "ii", t
    for t in ["Engineer In Test", "Software Engineer 1.5", "Software Engineer, Infrastructure"]:
        assert level(t) == "unknown", t
    assert level("Software Engineer", min_years=2) == "entry"          # 0-2 years required
    assert level("Software Engineer", min_years=3) == "unknown"
    assert level("Software Engineer", ai_seniority="new grad") == "entry"
    assert level("Software Engineer", ai_seniority="mid") == "ii"
    assert level("Software Engineer II", min_years=1) == "ii"          # the title decides first


def test_level_is_saved_and_updated_when_judged(tmp_path):
    from recon.models import Job
    from recon.store import Store
    s = Store(tmp_path / "t.db")
    s.upsert_many([(Job("greenhouse:co:1", "Co", "Software Engineer", "NYC", "u", None, "greenhouse", 1, "x"),
                    "match", None, None, "new")])
    assert s.execute("SELECT level FROM jobs").fetchone()[0] == "unknown"
    a = {"skills_match": 80, "level_fit": 95, "domain_fit": 70, "fit_score": 83, "why": "w", "missing_skills": [],
         "resume": "general", "seniority": "new grad", "sponsorship": "unclear", "required_years": None,
         "max_years_allowed": None}
    s.save_scores([("greenhouse:co:1", a, None)])
    assert s.execute("SELECT level FROM jobs").fetchone()[0] == "entry"
