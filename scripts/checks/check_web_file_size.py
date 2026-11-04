#!/usr/bin/env python3
"""Enforce the web module line limit from config/quality.yaml.

Lines of code exclude blank lines and comments, matching ESLint's
max-lines skipBlankLines + skipComments behaviour. That includes line
comments, block comments and JSX comment-only lines such as {/* x */}.
"""
from __future__ import annotations

import argparse
import fnmatch
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = REPO_ROOT / "config" / "quality.yaml"
HASH_COMMENT_SUFFIXES = {".py", ".yaml", ".yml", ".sh", ".toml", ".env"}


def load_quality(path: Path = CONFIG_PATH) -> dict:
    data = yaml.safe_load(path.read_text()) or {}
    return data.get("web_module", {})


def _strip_jsx_wrappers(line: str) -> str:
    stripped = line.strip()
    if stripped.startswith("{/*"):
        line = line.replace("{", " ", 1)
        stripped = line.strip()
    if stripped.endswith("*/}"):
        index = line.rfind("*/}")
        line = line[: index + 2] + " " + line[index + 3 :]
    return line


def count_lines(path: Path) -> int:
    suffix = path.suffix.lower()
    in_block = False
    in_string: str | None = None
    escaped = False
    count = 0

    for raw in path.read_text(errors="replace").splitlines():
        line = _strip_jsx_wrappers(raw)
        has_code = False
        index = 0

        while index < len(line):
            char = line[index]

            if in_block:
                if line.startswith("*/", index):
                    in_block = False
                    index += 2
                else:
                    index += 1
                continue

            if in_string is not None:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == in_string:
                    in_string = None
                index += 1
                continue

            if line.startswith("//", index):
                break
            if line.startswith("/*", index):
                in_block = True
                index += 2
                continue
            if char == "#" and suffix in HASH_COMMENT_SUFFIXES:
                break
            if char in {"'", '"', "`"}:
                in_string = char
                has_code = True
                index += 1
                continue
            if not char.isspace():
                has_code = True
            index += 1

        if has_code:
            count += 1

    return count


def is_exempt(relative: str, patterns: list[str]) -> bool:
    return any(fnmatch.fnmatch(relative, pattern) for pattern in patterns)


def collect_files(root: Path, globs: list[str], exempt: list[str]) -> list[Path]:
    found: set[Path] = set()
    for pattern in globs:
        for path in root.glob(pattern):
            if not path.is_file():
                continue
            relative = path.relative_to(root).as_posix()
            if is_exempt(relative, exempt):
                continue
            found.add(path)
    return sorted(found)


def check(scope: str, root: Path = REPO_ROOT, config_path: Path = CONFIG_PATH):
    quality = load_quality(config_path)
    max_lines = int(quality.get("max_file_lines", 250))
    include = quality.get("include", {})
    exempt = list(quality.get("exempt", []))
    scopes = ["python", "web"] if scope == "all" else [scope]

    results = []
    for name in scopes:
        globs = include.get(name, []) or []
        for path in collect_files(root, globs, exempt):
            results.append((path.relative_to(root).as_posix(), count_lines(path)))

    offenders = []
    for relative, lines in results:
        print(f"{lines:5d}  {relative}")
        if lines > max_lines:
            offenders.append((relative, lines))

    if offenders:
        print(f"\nFAIL: {len(offenders)} file(s) over {max_lines} lines of code:")
        for relative, lines in offenders:
            print(f"  {relative}: {lines} > {max_lines}")
        return 1
    print(f"\nOK: all {len(results)} file(s) at or under {max_lines} lines of code")
    return 0


def main(argv=None, root: Path = REPO_ROOT, config_path: Path = CONFIG_PATH) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--scope",
        choices=["python", "web", "all"],
        default="all",
        help="which part of the web module to check (default: all)",
    )
    args = parser.parse_args(argv)
    return check(args.scope, root=root, config_path=config_path)


if __name__ == "__main__":
    sys.exit(main())
