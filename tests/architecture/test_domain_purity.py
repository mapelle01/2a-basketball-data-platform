import re
from pathlib import Path

PROHIBITED_PATTERNS = [
    r"\brequests\b",
    r"\bhttpx\b",
    r"\bsqlalchemy\b",
    r"\bpsycopg2\b",
    r"\bfastapi\b",
    r"\bkafka\b",
    r"\bredis\b",
    r"\bboto3\b",
    r"\bos\.environ\b",
    r"\bopen\(",
    r"\bPath\(",
]


def test_domain_package_has_no_infrastructure_imports():
    base_path = Path(__file__).resolve().parents[2] / "src" / "feb_score" / "domain"
    errors = []
    for path in sorted(base_path.rglob("*.py")):
        text = path.read_text()
        for pattern in PROHIBITED_PATTERNS:
            if re.search(pattern, text):
                errors.append((path.relative_to(base_path.parent), pattern))
    if errors:
        raise AssertionError(
            "Found prohibited infrastructure references in domain:\n" + "\n".join(f"{path}: {pattern}" for path, pattern in errors)
        )
