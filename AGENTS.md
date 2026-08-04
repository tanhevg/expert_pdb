# Expert publications downloader and analyser

## General overview

This is a command line tool written in Python 3.12. The objective is to retrieve academic 
publications that are linked to protein structures in PDB, and extract protein productions
protocols from them using AI. 

## Tools

Use `/Users/evgeny/micromamba/envs/expert-pdb/bin/python` for running Python

## Coding guidelines
* Use `polars` for handling dataframes or tabular files, like `*.csv[.gz]`, `*.tsv[.gz]`, `.paquet`, etc.
* Use `requests` for handling with web APIs.
* Use `boto3` for interacting with S3.
* Use four spaces indentation.
* Use type annotations where reasonably possible .
* Do not use future imports.

## Testing Guidelines

Tests use pytest and `pytest-httpx` to mock external APIs. Name files
`test_<area>.py` and tests `test_<behavior>`. Use `tmp_path` for filesystem
effects and avoid real network calls. Add regression coverage for API parsing,
input validation, output manifests, and failure handling; run the full suite
before opening a PR.

## Commit & Pull Request Guidelines

Local Git history is unavailable in this checkout. Use short, imperative commit
subjects such as `Add PMC supplement manifest validation`, keeping unrelated
changes separate. PRs should explain the behavior change, include tests and
the commands run, document any CLI or output-format changes, and call out new
network-service assumptions or configuration requirements.

## Security & Data Handling

Do not bypass paywalls or commit downloaded articles, supplements, caches, or
credentials. Respect service rate limits and article licenses. Keep secrets in
the environment or local untracked configuration, never in fixtures or
`data/runs/`.
