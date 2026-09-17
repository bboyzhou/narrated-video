"""Persistent browser-I2V task orchestration.

The package owns deterministic state and media validation. A browser-capable
agent executes the returned semantic actions and records observations.
"""
from .manager import (browser_request_for_plan, next_action, observe_action,
                      plan_tasks, status_report, sync_downloads)

__all__ = [
    'browser_request_for_plan', 'next_action', 'observe_action', 'plan_tasks',
    'status_report', 'sync_downloads',
]
