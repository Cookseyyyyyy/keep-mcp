"""User-facing errors from Keep operations."""

from __future__ import annotations


class KeepMcpError(RuntimeError):
    """A Keep operation failed in a way the agent should see as a tool error."""
