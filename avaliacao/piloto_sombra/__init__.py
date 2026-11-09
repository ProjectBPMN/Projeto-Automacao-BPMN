"""Piloto em sombra local, sem qualquer adaptador de mutação do GLPI."""

from .core import (
    AuditIntegrityError,
    IdempotencyConflict,
    InvalidTransition,
    KillSwitchEngaged,
    ShadowPilot,
    ShadowPilotError,
    ValidationError,
)

__all__ = [
    "AuditIntegrityError",
    "IdempotencyConflict",
    "InvalidTransition",
    "KillSwitchEngaged",
    "ShadowPilot",
    "ShadowPilotError",
    "ValidationError",
]
