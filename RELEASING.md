# Release guide

Version 0.4.0 is a source release candidate. Nothing has been published to PyPI or TestPyPI. The name `qcloud-ai` was unregistered on both indexes on 10 November 2026 (JSON API 404); `qcloud` belongs to an unrelated project.

A published version is immutable: never re-upload a changed file under an existing version. Mock and contract tests do not establish live model access or billing; the release is complete only after the live acceptance at the end of this guide.

## One-time setup (owner)

1. Complete the PyPI and TestPyPI accounts: email verification and two-factor authentication. An organization is optional; it groups ownership and permissions but does not create a package namespace.
2. In `qcloud-host/qcloud-python` create two GitHub environments:
   - `testpypi`: deployment branch rule `main` only.
   - `pypi`: deployment branch rule `main` only and at least one required reviewer.
3. Register a **pending trusted publisher** on test.pypi.org and on pypi.org (Account → Publishing): project `qcloud-ai`, owner `qcloud-host`, repository `qcloud-python`, workflow `release.yml`, environment `testpypi` and `pypi` respectively. No API token is created or stored.

## Release

1. Promote the complete tested `sdks/python` tree from the backend repository to `qcloud-host/qcloud-python` and verify the Git trees match. Do not include application settings, provider credentials or release-host caches.
2. Confirm the version in `pyproject.toml`, `SDK_VERSION` and `CHANGELOG.md`.
3. Run **Actions → Release** with `version` and `target: testpypi`. The workflow tests Python 3.10 and 3.13, builds the sdist and wheel once, runs `twine check --strict` and the clean-install package check, writes `SHA256SUMS`, attests build provenance, uploads the files to TestPyPI and then downloads them back from TestPyPI to verify they are byte-identical and install in a clean environment. PyPI publication also produces PEP 740 attestations.
4. Install from TestPyPI on the PVE build host in a fresh environment (dependencies from PyPI):
   `python -m pip install --index-url https://test.pypi.org/simple/ --extra-index-url https://pypi.org/simple/ qcloud-ai==0.4.0`
5. Run the workflow again with `target: pypi`. A reviewer approves the `pypi` environment; the identical, already verified files are published and a draft GitHub release with the files and checksums is created.
6. Update the README install line to `python -m pip install qcloud-ai`, remove the candidate marker in the changelog and publish the draft release as tag `v0.4.0`.

## Live acceptance (required before announcing)

From a clean environment on PVE, with only `QCLOUD_API_KEY` and an active `QCLOUD_MODEL`:

1. `pip install qcloud-ai==<version>` from PyPI.
2. One non-streaming and one streaming chat request.
3. Confirm the request's usage record (request ID, tokens) and the resulting charge in the console match the provider-reported usage.
4. Record the evidence with the exact artifact hashes. Report separately which checks used mocks and which used the live provider.

[PyPI organizations](https://docs.pypi.org/organization-accounts/) · [Trusted Publishing](https://docs.pypi.org/trusted-publishers/) · [Attestations](https://docs.pypi.org/attestations/)
