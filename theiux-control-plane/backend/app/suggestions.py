"""Suggested actions for deployment error types (UX hints)."""

from typing import Any


def suggested_actions_for_error(last_error_type: str | None) -> list[str]:
    if not last_error_type:
        return []
    mapping: dict[str, list[str]] = {
        'build_error': [
            'Review Dockerfile and dependency lockfiles in the repository.',
            'Fix version pins, then create a new deployment.',
        ],
        'migration_error': [
            'Inspect database and migration scripts for the app.',
            'Run migrate on the site from the control plane after fixing schema.',
        ],
        'runtime_error': [
            'Review structured logs for stack traces and failing services.',
            'Retry the deployment after addressing the runtime issue.',
        ],
    }
    return list(mapping.get(last_error_type, ['Review logs and retry or open a support ticket.']))
