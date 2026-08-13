"""Infrastructure error classification.

Infrastructure failures (persistence, locking, corruption) are DISTINCT from
business errors (``domain.errors``): business errors are domain logic; these
signals mean "the store could not fulfill the request". Handlers/entrypoints can
classify them without catching domain exceptions.
"""


class InfrastructureError(Exception):
    """Base class for persistence/infrastructure failures."""


class StaleVersionError(InfrastructureError):
    """Optimistic-concurrency failure: the stored version no longer matches the
    version the caller loaded and mutated. The write was NOT applied."""


class CorruptedRecordError(InfrastructureError):
    """A stored record could not be deserialized (invalid/corrupt JSON)."""


class DatabaseUnavailableError(InfrastructureError):
    """The database could not be reached or the connection was lost."""


class SerializationConflictError(InfrastructureError):
    """PostgreSQL serialization failure (SQLSTATE 40001): the transaction would
    violate serializable isolation. Retryable, like a stale version."""


class DeadlockError(InfrastructureError):
    """PostgreSQL deadlock detected (SQLSTATE 40P01); the transaction was aborted."""


class ConstraintViolationError(InfrastructureError):
    """A DB-level constraint (unique/check/not-null) rejected the write."""