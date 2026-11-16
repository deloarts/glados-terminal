#!/usr/bin/env python3
"""Fail when a comment or docstring references a planning label.

Plans and decision records are local working artifacts, so code must not
point at them: labels such as decision ids (D06), work-package ids (WP-B1),
plan items (Item 12, (k1)), plan phases (Phase 2), plan addenda, audit
finding ids (03-High), "chapter" or the local planning folder mean nothing to
a reader of the repository. In code only comments and docstrings are scanned,
never ordinary string literals, so test data such as a 'D10' bar dimension
does not trip the check; Markdown documentation is scanned as a whole.

Run without arguments to scan every tracked file in scope, or pass file paths
(as pre-commit does) to scan only those. Known legitimate hits live in
scripts/plan_refs_allowlist.txt, one `path::text` entry per line, where the
hit is allowed when the flagged line in that file contains the text. A full
run also fails on an allowlist entry that no longer matches any line, so the
list cannot outlive the code it excuses.
"""

from __future__ import annotations

import io
import re
import subprocess
import sys
import tokenize
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ALLOWLIST = REPO_ROOT / "scripts" / "plan_refs_allowlist.txt"

PATTERNS = [
    re.compile(r"\bD[0-9]{2}\b"),
    re.compile(r"\bWP-[A-Z][0-9]"),
    re.compile(r"\(k[0-9]+\)"),
    re.compile(r"\bItems? [0-9]+\b"),
    re.compile(r"\bchapter\b", re.IGNORECASE),
    re.compile(r"\bPhase [0-9]+\b", re.IGNORECASE),
    re.compile(r"\.playground\b"),
    re.compile(r"\baddend(um|a)\b", re.IGNORECASE),
    re.compile(r"\b[0-9]{2}-(High|Medium|Low)\b"),
    re.compile(r"\baudit-tracked\b", re.IGNORECASE),
]

SCOPE_PREFIXES = (
    "src/",
    "tests/",
    "scripts/",
    "docs/",
    "docker/",
    ".github/",
)
SCOPE_FILES = (
    "pyproject.toml",
    ".pre-commit-config.yaml",
    "docker-compose.yml",
    "docker-compose.build.yml",
    "README.md",
)
EXCLUDED_PARTS: tuple[str, ...] = ()
HASH_COMMENT_SUFFIXES = (".toml", ".yml", ".yaml", ".sh", ".Dockerfile")
SLASH_COMMENT_SUFFIXES = (".js",)
WHOLE_FILE_SUFFIXES = (".md",)

_SLASH_COMMENT = re.compile(r"/\*.*?\*/|<!--.*?-->|(?<![:\"'`\w])//[^\n]*", re.DOTALL)


# The checker and its allowlist name the labels they look for.
EXCLUDED_FILES = ("scripts/check_plan_refs.py", "scripts/plan_refs_allowlist.txt")


def in_scope(path: str) -> bool:
    if path in EXCLUDED_FILES or any(part in path for part in EXCLUDED_PARTS):
        return False
    if path in SCOPE_FILES:
        return True
    if not path.startswith(SCOPE_PREFIXES):
        return False
    return path.endswith(
        (".py", *HASH_COMMENT_SUFFIXES, *SLASH_COMMENT_SUFFIXES, *WHOLE_FILE_SUFFIXES)
    )


def python_comment_spans(source: str) -> list[tuple[int, str]]:
    """Comments plus triple-quoted strings (docstrings), as (line, text)."""
    spans: list[tuple[int, str]] = []
    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(source).readline))
    except (tokenize.TokenError, SyntaxError):
        return spans
    for tok in tokens:
        if tok.type == tokenize.COMMENT:
            spans.append((tok.start[0], tok.string))
        elif tok.type == tokenize.STRING:
            body = tok.string.lstrip("rRbBuUfF")
            if body.startswith(('"""', "'''")):
                spans.append((tok.start[0], tok.string))
    return spans


def hash_comment_spans(source: str) -> list[tuple[int, str]]:
    spans = []
    for number, line in enumerate(source.splitlines(), start=1):
        index = line.find("#")
        if index != -1:
            spans.append((number, line[index:]))
    return spans


def slash_comment_spans(source: str) -> list[tuple[int, str]]:
    return [
        (source.count("\n", 0, match.start()) + 1, match.group(0))
        for match in _SLASH_COMMENT.finditer(source)
    ]


def comment_spans(path: str, source: str) -> list[tuple[int, str]]:
    if path.endswith(WHOLE_FILE_SUFFIXES):
        return [(1, source)]
    if path.endswith(".py"):
        return python_comment_spans(source)
    if path.endswith(HASH_COMMENT_SUFFIXES):
        return hash_comment_spans(source)
    return slash_comment_spans(source)


def load_allowlist() -> list[tuple[str, str]]:
    entries = []
    if not ALLOWLIST.exists():
        return entries
    for raw in ALLOWLIST.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        path, _, text = line.partition("::")
        entries.append((path.strip(), text.strip()))
    return entries


def tracked_files() -> list[str]:
    result = subprocess.run(
        ["git", "ls-files"], cwd=REPO_ROOT, capture_output=True, text=True, check=True
    )
    return result.stdout.splitlines()


def check_file(
    path: str, allowlist: list[tuple[str, str]], used: set[tuple[str, str]]
) -> list[str]:
    try:
        source = (REPO_ROOT / path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    lines = source.splitlines()
    problems = []
    for start_line, text in comment_spans(path, source):
        for offset, span_line in enumerate(text.splitlines()):
            if not any(pattern.search(span_line) for pattern in PATTERNS):
                continue
            number = start_line + offset
            full_line = lines[number - 1] if number <= len(lines) else span_line
            matches = [entry for entry in allowlist if path == entry[0] and entry[1] in full_line]
            if matches:
                used.update(matches)
                continue
            problems.append(f"{path}:{number}: {full_line.strip()}")
    return problems


def main(argv: list[str]) -> int:
    if argv:
        paths = [Path(p).resolve().relative_to(REPO_ROOT).as_posix() for p in argv]
    else:
        paths = tracked_files()
    allowlist = load_allowlist()
    used: set[tuple[str, str]] = set()
    problems = []
    for path in paths:
        if in_scope(path):
            problems.extend(check_file(path, allowlist, used))
    if not argv:
        problems.extend(
            f"{ALLOWLIST.relative_to(REPO_ROOT)}: stale entry {a_path}::{a_text}"
            for a_path, a_text in allowlist
            if (a_path, a_text) not in used
        )
    if problems:
        print("Planning labels found in comments or docstrings:")
        print("\n".join(problems))
        print(
            "\nRewrite the comment so it says what and why without the label. If the hit is"
            " genuine, add a `path::text` line to scripts/plan_refs_allowlist.txt."
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
