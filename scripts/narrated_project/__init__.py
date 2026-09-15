"""NarratedProject v1 authoring contract and legacy compatibility facade."""

from .model import (
    KIND,
    VERSION,
    NarratedProject,
    is_narrated_project,
    load_project,
    migrate_project,
    runtime_config_for,
    save_runtime_config,
)
from .validate import validate_project

__all__ = [
    'KIND',
    'VERSION',
    'NarratedProject',
    'is_narrated_project',
    'load_project',
    'migrate_project',
    'runtime_config_for',
    'save_runtime_config',
    'validate_project',
]
