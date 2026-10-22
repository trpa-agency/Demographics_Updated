"""The repository must not hold passwords, connection strings, or API keys.

Keys belong in .env (not stored in Git). This test reads every text file in the
repository and fails if it finds something that looks like a secret.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKIP_DIRS = {".git", "outputs", "__pycache__", ".pytest_cache"}
TEXT_SUFFIXES = {".py", ".md", ".csv", ".json", ".toml", ".txt", ".bat", ".html", ".ipynb", ".example", ".cfg", ".ini", ".yml", ".yaml", ""}
PATTERNS = {
    "Census API key": re.compile(r"\b[0-9a-f]{40}\b"),
    "password in a connection string": re.compile(r"(?i)\b(pwd|password)\s*=\s*[^;\s'\"]{3,}"),
    "SQL Server login": re.compile(r"(?i)\buid\s*=\s*\w+"),
    "key in a URL": re.compile(r"[?&]key=(?!\{|k\b|YOUR|\w*api_key)[0-9A-Za-z]{20,}"),
}


def _files():
    for path in ROOT.rglob("*"):
        if path.is_file() and not (set(path.relative_to(ROOT).parts) & SKIP_DIRS) and path.suffix.lower() in TEXT_SUFFIXES and path.name != ".env":
            yield path


def test_no_secrets_in_repository():
    found = []
    for path in _files():
        text = path.read_text(encoding="utf-8", errors="ignore")
        for label, pattern in PATTERNS.items():
            if path.name == "test_no_secrets.py":
                continue
            for match in pattern.finditer(text):
                found.append(f"{path.relative_to(ROOT)}: {label}: {match.group(0)[:12]}...")
    assert not found, "Possible secrets found:\n" + "\n".join(found)
