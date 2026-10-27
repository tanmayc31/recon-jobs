import html
import re

TAG = re.compile(r"<[^>]+>")
SPACE = re.compile(r"\s+")


def strip_html(s: str | None) -> str:
    """HTML (possibly escaped) -> plain text."""
    if not s:
        return ""
    s = html.unescape(html.unescape(s))   # Greenhouse double-escapes
    s = TAG.sub(" ", s)
    return SPACE.sub(" ", s).strip()
