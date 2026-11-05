import os

from recon.env import load_env


def test_loads_values_and_skips_comments(tmp_path, monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("RECON_TEST_QUOTED", raising=False)
    f = tmp_path / "env"
    f.write_text("# comment\n\nDATABASE_URL=postgresql://u:p@host:5432/postgres?sslmode=require\n"
                 "RECON_TEST_QUOTED=\"hello\"\n")
    load_env(f)
    assert os.environ["DATABASE_URL"] == "postgresql://u:p@host:5432/postgres?sslmode=require"
    assert os.environ["RECON_TEST_QUOTED"] == "hello"


def test_real_env_wins(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "from-github-secrets")
    f = tmp_path / "env"
    f.write_text("DATABASE_URL=from-file\n")
    load_env(f)
    assert os.environ["DATABASE_URL"] == "from-github-secrets"


def test_missing_file_is_fine(tmp_path):
    load_env(tmp_path / "nope")
