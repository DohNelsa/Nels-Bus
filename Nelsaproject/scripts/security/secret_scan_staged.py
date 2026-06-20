#!/usr/bin/env python3
import re
import subprocess
import sys
from pathlib import Path


SECRET_PATTERNS = [
    re.compile(r"AKIA[0-9A-Z]{16}"),  # AWS access key
    re.compile(r"-----BEGIN (RSA|EC|OPENSSH|PRIVATE) KEY-----"),
    re.compile(r"(?i)(api[_-]?key|secret|token|password)\s*[:=]\s*['\"][^'\"]{8,}['\"]"),
]

BLOCKED_PATH_PATTERNS = [
    re.compile(r"(^|/)\.env($|\.)"),
    re.compile(r"(^|/).*credentials.*\.json$"),
    re.compile(r"(^|/).*secret.*\.(txt|json|yaml|yml)$"),
]


def staged_files():
    out = subprocess.check_output(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMRT"],
        text=True,
    )
    return [line.strip() for line in out.splitlines() if line.strip()]


def main() -> int:
    files = staged_files()
    violations = []
    for rel in files:
        rel_norm = rel.replace("\\", "/")
        for p in BLOCKED_PATH_PATTERNS:
            if p.search(rel_norm):
                violations.append(f"blocked file path pattern: {rel}")
                break

        path = Path(rel)
        if not path.exists() or path.is_dir():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        for pat in SECRET_PATTERNS:
            if pat.search(text):
                violations.append(f"possible secret pattern in {rel}: {pat.pattern}")

    if violations:
        print("Secret scan failed:")
        for v in violations:
            print(f" - {v}")
        print("\nCommit blocked. Remove secrets or unstage offending files.")
        return 1
    print("Secret scan passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
