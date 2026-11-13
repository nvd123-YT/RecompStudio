"""Public project API; implementation is delegated to framework adapters."""
from pathlib import Path

from .integrations import (
    build_project,
    create_framework_project,
    load_local_settings,
    load_project_manifest,
    push_project,
    publish_project,
    recompile_project,
    set_project_inputs,
    update_project_framework,
)


def create_project(name: str, framework_id: str, workspace: Path,
                   input_path: Path | None = None,
                   bios_path: Path | None = None,
                   players: int = 1) -> Path:
    return create_framework_project(
        name, framework_id, workspace, input_path, bios_path, players
    )


def load_project(project_path: Path) -> dict:
    return load_project_manifest(project_path.expanduser().resolve())
