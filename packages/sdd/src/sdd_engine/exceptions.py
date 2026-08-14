"""
devscripts.sdd.exceptions — Custom exception hierarchy for SDD operations.
"""
from __future__ import annotations


class SDDError(Exception):
    """Base exception for all SDD operations."""
    pass


class FeatureNotFoundError(SDDError):
    """Raised when no active feature is configured or found."""
    pass


class AnalysisError(SDDError):
    """Raised when static cross-artifact analysis fails."""
    pass


class SDDMemoryError(SDDError):
    """Raised when memory logging or reading operations fail."""
    pass


class RunnerError(SDDError):
    """Raised when multi-agent harness task execution fails."""
    pass
