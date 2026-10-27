from recon.models import Job
from recon.store import Store


def test_new_then_seen(tmp_path):
    s = Store(tmp_path / "t.db")
    j = Job("greenhouse:co:1", "Co", "SWE", "NYC", "u", None, "greenhouse", 1)
    assert s.is_empty()
    assert s.upsert(j, "match", None, None) is True     # first time
    assert s.upsert(j, "match", None, None) is False    # already seen
    assert not s.is_empty()
