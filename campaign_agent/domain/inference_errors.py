"""Sanitized inference failure shared by application and provider adapters."""

class ReviewInferenceError(RuntimeError):
    """A sanitized provider failure that is safe to show in the planner."""
