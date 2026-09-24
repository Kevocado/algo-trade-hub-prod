"""Fail if any test that passed in a baseline JUnit report no longer passes.

Inputs are JUnit files pytest just wrote locally, so stdlib ElementTree is acceptable here;
never point this tool at XML from an untrusted source.
"""
from __future__ import annotations

import argparse
import fnmatch
import sys
import xml.etree.ElementTree as ET
from pathlib import Path


def test_key(classname: str, name: str) -> str:
    parts = classname.split(".")
    start = next((i for i, part in enumerate(parts) if part.startswith("test_")), 0)
    return f"{'.'.join(parts[start:])}::{name}"


def load_results(path: Path) -> dict[str, str]:
    results: dict[str, str] = {}
    for case in ET.parse(path).getroot().iter("testcase"):
        if case.find("failure") is not None or case.find("error") is not None:
            status = "failed"
        elif case.find("skipped") is not None:
            status = "skipped"
        else:
            status = "passed"
        results[test_key(case.get("classname", ""), case.get("name", ""))] = status
    return results


def regressions(baseline: dict[str, str], current: dict[str, str], allowed_removed: list[str]) -> list[str]:
    found = []
    for key, status in sorted(baseline.items()):
        if status != "passed" or any(fnmatch.fnmatchcase(key, glob) for glob in allowed_removed):
            continue
        now = current.get(key, "missing")
        if now != "passed":
            found.append(f"{key}: passed -> {now}")
    return found


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("baseline", type=Path)
    parser.add_argument("current", type=Path)
    parser.add_argument("--allow-removed", nargs="*", default=[])
    args = parser.parse_args(argv)
    baseline = load_results(args.baseline)
    current = load_results(args.current)
    lost = regressions(baseline, current, args.allow_removed)
    passed_before = sum(1 for s in baseline.values() if s == "passed")
    passed_now = sum(1 for s in current.values() if s == "passed")
    print(f"baseline passed: {passed_before}  current passed: {passed_now}  regressions: {len(lost)}")
    for line in lost:
        print(f"  REGRESSION {line}")
    return 1 if lost else 0


if __name__ == "__main__":
    sys.exit(main())
