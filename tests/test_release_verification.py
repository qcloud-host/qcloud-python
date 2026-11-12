"""An upload is not verified until both registry metadata and file bytes agree."""

import hashlib
import importlib.util
import io
import json
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "verify_registry", Path(__file__).parents[1] / "scripts" / "verify_registry.py"
)
registry = importlib.util.module_from_spec(spec)
spec.loader.exec_module(registry)


@pytest.mark.parametrize("failure", [None, "metadata", "bytes", "files", "origin"])
def test_registry_verification_requires_exact_tested_files(
    tmp_path, monkeypatch, failure
):
    names = ["qcloud_ai-0.4.0-py3-none-any.whl", "qcloud_ai-0.4.0.tar.gz"]
    bodies = {name: name.encode() for name in names}
    digests = {name: hashlib.sha256(body).hexdigest() for name, body in bodies.items()}
    expected = tmp_path / "expected"
    expected.mkdir()
    (expected / "SHA256SUMS").write_text(
        "\n".join(f"{digest}  {name}" for name, digest in digests.items())
    )
    metadata = {
        "urls": [
            {
                "filename": name,
                "digests": {"sha256": digests[name]},
                "url": f"https://files.pythonhosted.org/{name}",
            }
            for name in names
        ]
    }
    if failure == "metadata":
        metadata["urls"][0]["digests"]["sha256"] = "0" * 64
    if failure == "bytes":
        bodies[names[0]] = b"tampered"
    if failure == "files":
        metadata["urls"].pop()
    if failure == "origin":
        metadata["urls"][0]["url"] = "https://unexpected.invalid/package.whl"

    def download(url, timeout):
        if url.endswith("/json"):
            return io.BytesIO(json.dumps(metadata).encode())
        return io.BytesIO(bodies[url.rsplit("/", 1)[1]])

    monkeypatch.setattr(registry, "urlopen", download)
    output = tmp_path / "downloaded"
    if failure:
        with pytest.raises(ValueError):
            registry.verify_registry("0.4.0", "pypi", expected, output)
    else:
        registry.verify_registry("0.4.0", "pypi", expected, output)
        assert {path.name: path.read_bytes() for path in output.iterdir()} == bodies
