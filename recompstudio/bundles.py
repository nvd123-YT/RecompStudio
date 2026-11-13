"""Locate framework and toolchain resources embedded in RecompStudio packages."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def bundle_root() -> Path | None:
    """Resolve embedded resources for source, GUI, CLI, and AppImage launch modes."""
    candidates: list[Path] = []
    override = os.environ.get("RECOMPSTUDIO_BUNDLED_ROOT")
    if override:
        candidates.append(Path(override).expanduser())
    frozen_root = getattr(sys, "_MEIPASS", None)
    if frozen_root:
        candidates.append(Path(frozen_root) / "recompstudio" / "bundled")
        candidates.append(Path(frozen_root) / "bundled")

    executable_dir = Path(sys.executable).resolve().parent
    candidates.extend([
        executable_dir / "RecompStudio" / "_internal" / "recompstudio" / "bundled",
        executable_dir / "RecompStudio" / "recompstudio" / "bundled",
        executable_dir / "RecompStudio.app" / "Contents" / "Frameworks" / "recompstudio" / "bundled",
        executable_dir / "RecompStudio.app" / "Contents" / "Resources" / "recompstudio" / "bundled",
    ])
    appdir = os.environ.get("APPDIR")
    if appdir:
        app_root = Path(appdir) / "usr" / "bin" / "RecompStudio"
        candidates.extend([
            app_root / "_internal" / "recompstudio" / "bundled",
            app_root / "recompstudio" / "bundled",
        ])

    candidates.append(Path(__file__).resolve().parent / "bundled")
    seen: set[Path] = set()
    for candidate in candidates:
        try:
            candidate = candidate.resolve()
        except OSError:
            continue
        if candidate in seen:
            continue
        seen.add(candidate)
        if (candidate / "bundle.json").is_file() or (candidate / "frameworks").is_dir():
            return candidate
    return None


def bundled_framework_path(framework_id: str) -> Path | None:
    root = bundle_root()
    if root is None:
        return None
    candidate = root / "frameworks" / framework_id
    marker = candidate / ".git"
    if marker.exists() or marker.is_file():
        return candidate
    return None


def bundle_manifest() -> dict:
    root = bundle_root()
    if root is None:
        return {}
    path = root / "bundle.json"
    if not path.is_file():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def bundled_toolchain() -> tuple[Path, dict] | None:
    root = bundle_root()
    if root is None:
        return None
    info = bundle_manifest().get("toolchain")
    if not isinstance(info, dict):
        return None
    asset = info.get("asset")
    if not isinstance(asset, str) or Path(asset).name != asset:
        return None
    archive = root / "toolchains" / asset
    if archive.is_file():
        return archive, info
    return None
