# Contributing to org-workspace

Thanks for your interest. This document covers setup, testing, and the PR process.

## Development setup

```bash
git clone https://github.com/datacore-one/org-workspace
cd org-workspace
pip install -e ".[dev]"
```

Requires Python 3.10+.

## Running tests

```bash
pytest                          # run all tests
pytest --cov=org_workspace      # with coverage report
```

The CI enforces 80% coverage — PRs that drop below this will fail the build.

## Code style

```bash
ruff check src tests            # lint
ruff format src tests           # format
```

`src/org_workspace/_vendor/` is excluded from linting (vendored orgparse fork).

## What to work on

Open issues are tracked at [github.com/datacore-one/org-workspace/issues](https://github.com/datacore-one/org-workspace/issues).

The most useful contributions right now:
- Bug reports with a minimal reproducing org file
- Tests covering edge cases in existing query/mutation methods
- Upstream orgparse compatibility improvements

## Submitting a PR

1. Fork the repo and create a branch from `main`
2. Add tests for any new behaviour
3. Make sure `ruff check` and `pytest --cov` both pass locally
4. Open a PR with a clear description of what changes and why

## Vendored orgparse

`src/org_workspace/_vendor/orgparse/` is a fork of [karlicoss/orgparse](https://github.com/karlicoss/orgparse) with write support added (the upstream [PR #77](https://github.com/karlicoss/orgparse/pull/77) was closed without merging). Changes to the vendor copy must preserve the BSD 2-Clause license header.
