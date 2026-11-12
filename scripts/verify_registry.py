"""Download registry artifacts only when they match the tested build's hashes."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import quote, urlsplit
from urllib.request import urlopen


def verify_registry(version: str, target: str, expected: Path, output: Path) -> None:
    hosts = {"pypi": "pypi.org", "testpypi": "test.pypi.org"}
    host = hosts[target]
    manifest = {}
    for line in (expected / "SHA256SUMS").read_text().splitlines():
        digest, filename = line.split()
        if not re.fullmatch(r"[a-f0-9]{64}", digest) or Path(filename).name != filename:
            raise ValueError("Invalid build checksum manifest")
        manifest[filename] = digest
    if len(manifest) != 2 or not any(name.endswith(".whl") for name in manifest):
        raise ValueError("Expected exactly one wheel and one source archive")
    if not any(name.endswith(".tar.gz") for name in manifest):
        raise ValueError("Missing source archive")
    for attempt in range(6):
        try:
            with urlopen(
                f"https://{host}/pypi/qcloud-ai/{quote(version, safe='')}/json",
                timeout=30,
            ) as response:
                metadata = json.load(response)
            break
        except HTTPError as error:
            if error.code != 404 or attempt == 5:
                raise
            time.sleep(10)
    files = {item["filename"]: item for item in metadata["urls"]}
    if set(files) != set(manifest):
        raise ValueError("Registry file set differs from the tested build")
    output.mkdir(parents=True, exist_ok=True)
    if any(output.iterdir()):
        raise ValueError("Registry output directory must be empty")
    for filename, digest in manifest.items():
        item = files[filename]
        if item["digests"]["sha256"] != digest:
            raise ValueError(f"Registry checksum differs: {filename}")
        url = urlsplit(item["url"])
        if url.scheme != "https" or url.hostname not in {
            "files.pythonhosted.org",
            "test-files.pythonhosted.org",
        }:
            raise ValueError("Unexpected registry download origin")
        with urlopen(item["url"], timeout=60) as response:
            content = response.read()
        if hashlib.sha256(content).hexdigest() != digest:
            raise ValueError(f"Downloaded checksum differs: {filename}")
        (output / filename).write_bytes(content)
        print(f"Verified {filename}: {digest}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", required=True)
    parser.add_argument("--target", choices=["pypi", "testpypi"], required=True)
    parser.add_argument("--expected", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    verify_registry(args.version, args.target, args.expected, args.output)
