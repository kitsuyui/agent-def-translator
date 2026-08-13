# Release Process

`agent-def-translator` is alpha software. The command model and generated file
formats may change before 1.0.0, so release notes must call out user-visible CLI
changes, definition-format changes, and deprecation timeline changes.

## Version Policy

Use Git tags in the `vMAJOR.MINOR.PATCH` form. The package version is derived
from Git tags with `setuptools-scm`; there is no manually edited version field
in `pyproject.toml`.

While the project is in `0.x`, minor versions can include breaking changes when
the release notes describe the migration path. Patch versions should be limited
to compatible fixes, documentation updates, and small CLI behavior corrections.

The current package metadata declares `requires-python = ">=3.10"`. Before a
release, compare that declaration with the CI test matrix in
`.github/workflows/python-test.yml`. Add newly supported Python versions to the
matrix before treating them as release-tested.

## Release Checklist

Before creating a GitHub Release:

1. Start from the current `main` branch.
2. Confirm the release commit has passed the Python test workflow, packaging
   workflow, spellcheck, link check, octocov, and CodeQL checks.
3. Run the local baseline checks:

   ```bash
   uv sync
   uv run poe check
   uv run poe test
   uv run poe coverage-xml
   uv build
   ```

4. Review user-facing changes since the previous tag and draft release notes.
5. Update `CHANGELOG.md`: add a `## [X.Y.Z] - YYYY-MM-DD` section under
   `## [Unreleased]`, move the relevant entries in, and update the comparison
   links at the bottom of the file.
6. Create either a prerelease or a final release from GitHub Releases with a tag
   that matches the version policy.

The packaging workflow builds from the release event. It publishes prereleases
to TestPyPI and final releases to PyPI.

## Prerelease Flow

Use a GitHub prerelease when you want to validate the package before publishing
the final PyPI artifact.

1. Create a prerelease with the intended version tag.
2. Wait for the packaging workflow to publish to TestPyPI.
3. Install the TestPyPI artifact in a clean environment and run a smoke check:

   ```bash
   uvx --isolated \
     --default-index https://test.pypi.org/simple \
     --index https://pypi.org/simple \
     --from agent-def-translator \
     agent-def-translator --help
   ```

4. If the artifact is correct, edit the GitHub Release and clear the prerelease
   flag to publish the same version to PyPI.

The release workflow listens for both `prereleased` and `released` events. Editing
an existing release can therefore start the packaging workflow again. A repeated
upload for an already published version should fail loudly at the package index.

## Publish Failure Notes

Release builds must run from a checkout that still has the release tag
available to `setuptools-scm`. This repository intentionally does not define a
`fallback_version`. If Git metadata or tag refs are missing, `uv build` fails
early with a `setuptools-scm was unable to detect version` error instead of
silently producing a reused package version.

Treat that failure as a checkout-integrity problem. Inspect the release
workflow's tag visibility before retrying the release rather than debugging it
as a PyPI credential or upload issue.

The current workflow uses PyPI API tokens. Moving to Trusted Publishing, adding
artifact attestations, or changing release-note generation should be handled as
separate release-infrastructure changes.
