# Changelog

All notable changes to compile-pdf-impose are documented here.
Format: [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).
Versioning: [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.1] - 2026-06-11

### Fixed

- Ship `py.typed` (PEP 561) so strict-mypy consumers (compile-pdf) resolve this
  producer's types instead of treating the package as untyped.

## [0.1.1] - 2026-06-04

### Security
- Add security-only CI workflow (`.github/workflows/security.yml`) running
  semgrep (`p/security-audit`, `p/secrets`, `p/python`) and bandit
  (medium severity/confidence) on every push to `main` and all PRs.
- Harden `publish-pypi.yml`: add top-level `permissions: contents: read`
  and `persist-credentials: false` on the checkout step to limit the
  blast-radius of a compromised workflow run.

### Fixed
- Correct import ordering in `src/compile_pdf_impose/__init__.py` and
  `src/compile_pdf_impose/api.py` (ruff I001).

### Dismissed false positives
- `pip-audit` reported four PyJWT CVEs (PYSEC-2026-175/177/178/179)
  against the scan-environment's system Python installation. PyJWT is
  not a dependency of compile-pdf-impose and does not appear in
  `pyproject.toml` directly or transitively through this package's
  declared deps. No action taken.

## [0.1.0] - 2026-05-01

### Added
- Initial release: impose producer for sheet-level step-and-repeat layout.
- `POST /v1/impose/apply` FastAPI endpoint with inline base64 PDF + plan.
- Four-layer post-condition verification (schema, determinism, unchanged,
  cell-extract round-trip).
- CLI `compile-pdf-impose impose` and `impose-schema` subcommands.
- PyPI Trusted Publishers (OIDC) publish workflow.
