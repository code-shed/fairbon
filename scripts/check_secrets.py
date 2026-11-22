#!/usr/bin/env python3
"""Block a push if it would publish secrets or private data.

Run manually before pushing, or let the local ``pre-push`` hook do it:

    python3 scripts/check_secrets.py

The script never prints a secret value — only the affected key or file.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = ROOT / ".env"
EXAMPLE_FILE = ROOT / ".env.example"

#: Environment keys whose real values must never appear in tracked files.
SECRET_KEYS = (
    "SITE_PASSWORD",
    "ADMIN_PASSWORD",
    "SESSION_SECRET",
    "VISION_PRIMARY_API_KEY",
    "VISION_FALLBACK_API_KEY",
    "TURNSTILE_SECRET_KEY",
)

#: Generic shapes of credentials in staged changes.
PATTERNS: dict[str, str] = {
    "OpenAI-style API key": r"sk-[A-Za-z0-9]{20,}",
    "GitHub token": r"(?:ghp_|github_pat_)[A-Za-z0-9_]{20,}",
    "private key block": r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
}

#: Assignments that must stay empty in the committed example file.
EXAMPLE_ASSIGNMENT = re.compile(
    r"^(?:SITE_PASSWORD|ADMIN_PASSWORD|SESSION_SECRET|"
    r"VISION_[A-Z_]*API_KEY|TURNSTILE_SECRET_KEY)=.+$"
)


def git(*args: str) -> str:
    result = subprocess.run(
        ("git", *args), cwd=ROOT, capture_output=True, text=True, check=False
    )
    return result.stdout


def find_exact_values() -> list[str]:
    """Find real .env values in tracked files (file names only, no values)."""

    findings: list[str] = []
    if not ENV_FILE.is_file():
        return findings
    values: dict[str, str] = {}
    for line in ENV_FILE.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            value = value.strip()
            if key.strip() in SECRET_KEYS and len(value) >= 6:
                values[key.strip()] = value
    for key, value in values.items():
        if git("grep", "-l", "-I", "-F", value, "--"):
            findings.append(f"Wert aus {key} steht in einer getrackten Datei")
    return findings


def find_patterns() -> list[str]:
    findings: list[str] = []
    staged = git("diff", "--cached", "-U0")
    for label, pattern in PATTERNS.items():
        if re.search(pattern, staged):
            findings.append(f"{label} in gestagten Änderungen")
    if EXAMPLE_FILE.is_file():
        for line in EXAMPLE_FILE.read_text().splitlines():
            if EXAMPLE_ASSIGNMENT.match(line.strip()):
                findings.append(".env.example enthält einen belegten Wert")
                break
    # Assembled at runtime so the pattern does not match this file itself.
    home_path = "/home" + "/j/"
    if git("grep", "-l", "-I", home_path, "--"):
        findings.append("persönlicher Pfad im Benutzerverzeichnis gefunden")
    return findings


def main() -> int:
    findings = find_exact_values() + find_patterns()
    if findings:
        print("PUSH GESTOPPT – vertrauliche Daten gefunden:")
        for item in findings:
            print(f"  - {item}")
        return 1
    print("OK – keine vertraulichen Daten gefunden.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
