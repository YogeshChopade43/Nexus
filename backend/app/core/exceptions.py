from __future__ import annotations


class NexusError(Exception):
    pass


class AppNotConnectedError(NexusError):
    pass


class ToolNotFoundError(NexusError):
    pass


class WorkflowNotFoundError(NexusError):
    pass


class ValidationError(NexusError):
    pass