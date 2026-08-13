Contract Versioning Policy

- Each contract (command/event) includes a meta.version field (semantic string like "1.0").
- Compatibility rules:
  - Backwards-compatible additions: bump minor (1.0 -> 1.1). Consumers designed to ignore unknown properties should accept minor bumps.
  - Backwards-incompatible changes: bump major (1.0 -> 2.0). Maintain older major versions for a transition period.
- Event producers must set meta.version to the contract version they implement.
- Commands must include command_id (UUID) to enable idempotency; events include event_id (UUID).
- Deprecation: mark contracts deprecated in documentation and maintain for at least N months depending on SLAs.

Guidance:
- Avoid changing required properties in a minor release.
- Add new optional properties rather than change existing ones.
- Use $id to point to schema canonical location.
