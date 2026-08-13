Contracts folder created for Domain Contracts (commands & events).

Structure:

contracts/
  commands/*.v1.json
  events/*.v1.json

validation_examples/ contains example payloads (valid/invalid) and can be used as fixtures for contract tests.

Use Draft 2020-12 of JSON Schema. Each file is self-contained and versioned in its $id and meta.version.

Running tests:

- Install development dependencies if needed (pytest and pytest-cov are useful).
- From the repository root, run:

    python3 -m pytest -q

- To measure coverage, run:

    python3 -m pytest --cov=feb_score --cov-report=term -q

This will execute the Core Domain unit tests and display coverage for the feb_score package.
