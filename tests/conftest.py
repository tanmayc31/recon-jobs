import pytest

from recon import linkcheck


@pytest.fixture(autouse=True)
def every_job_is_open(monkeypatch):
    """main.run checks new matches through each site's API: no network in tests. A test that
    needs a gone job patches linkcheck.check_open itself."""
    async def check_open(jobs, transport=None):
        return [(j, True) for j in jobs]
    monkeypatch.setattr(linkcheck, "check_open", check_open)
