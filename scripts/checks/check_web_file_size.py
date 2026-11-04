#!/usr/bin/env python3
"""Enforce the web module line limit from config/quality.yaml.

Lines of code exclude blank lines and lines whose first non-space
characters are '#' or '//'.
"""
from __future__ import annotations

import argparse
import fnmatch
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = REPO_ROOT / "config" / "quality.yaml"


def load_quality(path: Path = CONFIG_PATH) -> dict:
    data = yaml.safe_load(path.read_text()) or {}
    return data.get("web_module", {})


def count_lines(path: Path) -> int:
    count = 0
    for line in path.read_text(errors="replace").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or stripped.startswith("//"):
            continue
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
