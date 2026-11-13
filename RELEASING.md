# Release guide

Check PyPI before releasing. An uploaded version is immutable. Release changed files under a new version of `qcloud-ai`.

## One-time setup

1. Complete the destination registry account's email verification and two-factor
   authentication. PyPI and TestPyPI are separate services and accounts.
2. In `qcloud-host/qcloud-python`, create a GitHub environment named `pypi`, with
   a deployment branch rule allowing only `main` and at least one required
   reviewer. Create `testpypi` only if you intend to publish there.
3. On the selected registry, register a pending trusted publisher: project
   `qcloud-ai`, owner `qcloud-host`, repository `qcloud-python`, workflow
   `release.yml`, and the matching environment (`pypi` or `testpypi`). If the
   project already exists, add the publisher in its Publishing settings instead.
   This authorizes that workflow to publish; no permanent API token is needed.

A production release does not require a TestPyPI account or TestPyPI publication.

## Verify locally

```bash
python -m pip install -e ".[dev]"
python -m pytest
python -m build
python -m twine check --strict dist/*
python scripts/check_package.py
```

Start with an empty `dist` directory for the selected version. The package check
installs the built wheel with its realtime extra in an isolated environment,
checks dependencies, and runs sync/async calls against a mock transport. These
checks do not make paid QCloud requests.

## Publish to one registry

1. Ensure the reviewed source is on `main` and any SDK mirror in the application
   repository matches it. Confirm `pyproject.toml`, `SDK_VERSION`, and the
   changelog use the same version. Do not include credentials or local settings.
2. Run **Actions → Release** on `main`, with the version and either `pypi` or
   `testpypi` as the target. Each run tests Python 3.10 and 3.13, builds a wheel
   and source archive, checks metadata strictly, and clean-installs the wheel.
3. Approve the selected GitHub environment when required. That run's files are
   checked against `SHA256SUMS`, attested, and uploaded to the selected registry.
4. The workflow downloads both files from that registry, compares both the
   registry metadata and downloaded bytes to the tested checksums, and runs the
   clean-install package check again. For PyPI only, successful verification
   creates a draft GitHub release with the artifacts and checksums.
5. Confirm the registry page and draft release, then publish the draft as tag
   `v<version>`.

TestPyPI and PyPI runs are independent builds. A separate run does **not** reuse
first-run artifacts, and this workflow does not claim byte-for-byte promotion
between registries. Within each run, published and downloaded files must match
the tested files exactly. Do not rerun publication for a version already uploaded
to the selected registry. If verification fails after upload, inspect and verify
the existing files; prepare a new version for any code change.

## Live acceptance before announcing

From a fresh environment, install `qcloud-ai==<version>` from PyPI. With an
authorized QCloud key and an active model, make one non-streaming and one
streaming chat request, then confirm the request IDs, token usage, and resulting
charge against the console. Record artifact hashes and distinguish mock checks
from live provider checks. Do not announce generation execution, uploads,
realtime, or serverless execution as available without checking current gates.

[Trusted Publishing](https://docs.pypi.org/trusted-publishers/) ·
[Attestations](https://docs.pypi.org/attestations/)
