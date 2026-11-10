# Release guide

Version 0.3.0 is a source release candidate. PyPI publication is deferred until the owner finishes account verification and two-factor setup. GitHub source and built wheels remain usable separately; this version does not imply a registry release or release tag.

Before publishing, confirm ownership of the registry name, review the exact commit, run all checks, and verify one authenticated inference request with a QCloud API key and an active catalog model. Mock tests do not establish live model access.

## Python / PyPI

1. Complete your individual PyPI account, email verification, and two-factor setup.
2. Confirm package-name ownership. Choose personal package ownership or apply for a company organization; an organization is not required to publish an SDK.
3. On the designated release host, run `python -m pip install -e ".[dev]"`, `python -m pytest`, `python -m build`, `python -m twine check dist/*`, and `python scripts/check_package.py`. Build produces a wheel from the sdist; the package check installs the wheel and realtime extra into a fresh virtual environment, checks dependencies and sync/async imports, and makes mocked HTTP requests. Set `QCLOUD_WHEELHOUSE` to a directory of verified dependency wheels for an offline install.
4. Retain the wheel, sdist, SHA-256 hashes and tested source commit, then publish those exact reviewed artifacts through your authenticated PyPI release process. Prefer GitHub Actions Trusted Publishing once the repository and publisher are configured. Do not commit registry tokens.
5. After the release exists on PyPI, install it by exact version in a clean consumer, update installation instructions to `python -m pip install qcloud-ai`, remove the candidate marker in the changelog, and tag the released commit `v0.3.0`.

Publisher configuration, if using a future GitHub release workflow: owner `qcloud-host`, repository `qcloud-python`, with an exact workflow filename and a protected release environment. No trusted publisher or registry credential has been created by this repository.

The app's `sdks/python` tree is canonical. Promote the complete tested subtree to `qcloud-host/qcloud-python` and verify the Git tree matches before publication. Do not include application settings, provider credentials or release-host caches. Public queue capabilities and model admission remain server decisions; passing SDK tests does not activate billing or inference.

[PyPI organizations](https://pypi.org/organizations/) · [Trusted Publishing](https://docs.pypi.org/trusted-publishers/)
