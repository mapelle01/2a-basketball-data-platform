Contracts (Domain) — README

Location: contracts/
  commands/  -> JSON Schema files for Commands (v1)
  events/    -> JSON Schema files for Events (v1)

Schema standard: JSON Schema Draft 2020-12.
Each schema file is self-contained, includes $id, title, description, examples and uses meta.version and command_id/event_id.

Usage:
- Use these schemas to validate incoming commands and produced events during development.
- Commands must include command_id (UUID) for idempotency. Events must include event_id (UUID).
- All schemas include examples in the file. Use validation_examples/ for additional fixtures.

Next steps:
- Run contract tests (consumer-driven contract tests) using these schemas.
- Propose any changes via PR with schema version bump following contract_versioning.md.
