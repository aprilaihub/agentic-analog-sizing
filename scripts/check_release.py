"""Fail when a source tree or built artifact contains private/generated files."""

from __future__ import annotations

import argparse
import re
import tarfile
import zipfile
from pathlib import Path

FORBIDDEN_NAMES = (
    ".env.local",
    "cds.lib",
    "essab_sim/",
    "trainLogs/",
    "__pycache__/",
    "simResults.csv",
)
SECRET_PATTERNS = (
    re.compile(rb"sk-[A-Za-z0-9_-]{20,}"),
    re.compile(rb"OPENAI_API_KEY\s*=\s*[^\s]+"),
    re.compile(rb"/(?:home|Users)/[A-Za-z0-9_.-]+/"),
)


def members(path: Path):
    if path.suffix == ".whl" or path.suffix == ".zip":
        with zipfile.ZipFile(path) as archive:
            for name in archive.namelist():
                yield name, archive.read(name)
    elif path.name.endswith(".tar.gz"):
        with tarfile.open(path) as archive:
            for item in archive.getmembers():
                if item.isfile():
                    stream = archive.extractfile(item)
                    yield item.name, stream.read() if stream else b""


def check(path: Path) -> list[str]:
    failures: list[str] = []
    artifacts = [path] if path.is_file() else sorted(path.glob("*"))
    for artifact in artifacts:
        for name, payload in members(artifact) or ():
            normalized = name.replace("\\", "/")
            if any(token in normalized for token in FORBIDDEN_NAMES):
                failures.append(f"{artifact}: forbidden path {name}")
            if any(pattern.search(payload) for pattern in SECRET_PATTERNS):
                failures.append(f"{artifact}: possible credential in {name}")
    return failures


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("path", type=Path)
    failures = check(parser.parse_args().path)
    if failures:
        print("\n".join(failures))
        return 1
    print("Release artifacts contain no forbidden paths or credential patterns.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
