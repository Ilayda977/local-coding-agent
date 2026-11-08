"""Domain errors shared by every taskflow module."""


class TaskflowError(Exception):
    """Base class for all expected business errors."""


class NotFoundError(TaskflowError):
    """The requested entity does not exist."""


class ValidationError(TaskflowError):
    """Input data or a requested state change is invalid."""


class PermissionDeniedError(TaskflowError):
    """The acting user is not allowed to perform the operation."""


class ConflictError(TaskflowError):
    """The operation conflicts with existing data (e.g. duplicate email)."""
