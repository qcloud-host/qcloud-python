# Release guide

Version 0.2.0 is prepared from tested source. Installing from GitHub or a locally built archive works before registry publication.

Before publishing, confirm ownership of the registry name, review the exact commit, run all checks, and verify one authenticated inference request with a QCloud API key and an active catalog model. Mock tests do not establish live model access.

## Python / PyPI

1. Complete your individual PyPI account, email verification, and two-factor setup.
2. Choose personal package ownership or apply for a company organization. Company organizations currently cost $5 per member per month and require PyPI approval; an organization is not required to publish an SDK.
3. Run `python -m pip install -e ".[dev]"`, `python -m pytest`, `python -m build`, and `python -m twine check dist/*`.
4. Publish the reviewed artifacts through your authenticated PyPI release process. Prefer GitHub Actions Trusted Publishing once the repository and publisher are configured. Do not commit registry tokens.
5. After the release exists on PyPI, update installation instructions to `python -m pip install qcloud-ai` and tag the released commit `v0.2.0`.

Publisher configuration, if using a future GitHub release workflow: owner `qcloud-host`, repository `qcloud-python`, with an exact workflow filename and a protected release environment. No trusted publisher or registry credential has been created by this repository.

[PyPI organizations](https://pypi.org/organizations/) · [Trusted Publishing](https://docs.pypi.org/trusted-publishers/)
