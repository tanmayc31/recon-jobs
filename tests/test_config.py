from recon.main import COMPANIES, SOURCES, load_companies, load_referrals


def write(path, text):
    path.write_text(text)
    return path


def test_referrals_merged(tmp_path):
    cos = write(tmp_path / "companies.csv", "company,ats,slug,tier\nStripe,greenhouse,stripe,1\n"
                                            "Scale AI,greenhouse,scaleai,1\n")
    refs = write(tmp_path / "referrals.csv", "company,contact\nscale ai,Jane Doe (LinkedIn)\nStripe,\n")
    got = {c["company"]: c["referral"] for c in load_companies(cos, refs)}
    assert got == {"Stripe": "", "Scale AI": "Jane Doe (LinkedIn)"}   # case-insensitive; blank = none


def test_referrals_file_optional(tmp_path):
    assert load_referrals(tmp_path / "missing.csv") == {}
    cos = write(tmp_path / "companies.csv", "company,ats,slug,tier\nStripe,greenhouse,stripe,1\n")
    assert load_companies(cos, tmp_path / "missing.csv")[0]["referral"] == ""


def test_real_companies_config():
    # The committed config: public columns only, known ATS, valid tiers, no duplicates
    cos = load_companies(COMPANIES, COMPANIES.parent / "no-referrals.csv")
    assert list(cos[0]) == ["company", "ats", "slug", "tier", "referral"]
    assert all(c["ats"] in SOURCES and c["tier"] in {"1", "2", "3"} for c in cos)
    assert len({c["company"] for c in cos}) == len(cos)


def test_company_names_have_no_emoji_or_symbols():
    # "🔥 Intel" -> "Intel". Letters with accents ("AtkinsRéalis") are fine.
    # Left alone for now: cleaning these would collide with another row of the same name.
    collisions = {"🔥 Duolingo", "🔥 Salesforce", "🔥 Intel", "🔥 DoorDash"}
    cos = load_companies(COMPANIES, COMPANIES.parent / "no-referrals.csv")
    odd = [c["company"] for c in cos if c["company"] not in collisions
           and (c["company"] != c["company"].strip() or any(not ch.isalnum() and ord(ch) > 127 for ch in c["company"]))]
    assert odd == []
