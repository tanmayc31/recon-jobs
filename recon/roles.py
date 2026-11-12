"""Role type from the title, for the dashboard's role filter. First match wins."""
import re

ROLES = [   # (key, title pattern); order matters: "Backend Software Engineer" is backend, not plain SWE
    ("fde", r"forward[\s-]deploy|\bfde\b"),
    ("ml", r"machine learning|\bml\b|\bai\b|\bllm|deep learning|computer vision|\bnlp\b|gen ?ai|generative"),
    ("fullstack", r"full[\s-]?stack"),
    ("backend", r"back[\s-]?end|server[\s-]side"),
    ("frontend", r"front[\s-]?end|\bui\b|\bweb (developer|engineer)"),
    ("cloud", r"cloud|devops|dev ops|site reliability|\bsre\b|reliability engineer|platform engineer|"
              r"infrastructure|systems? development engineer|\bsysde\b"),
    ("swe", r"software|\bswe\b|\bsde\b|developer|programmer|application engineer"),
]
ROLES = [(key, re.compile(rx, re.I)) for key, rx in ROLES]


def role_type(title: str) -> str:
    """swe / fullstack / backend / frontend / cloud / fde / ml / other."""
    return next((key for key, rx in ROLES if rx.search(title or "")), "other")
