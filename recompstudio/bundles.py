"""Locate framework and toolchain resources embedded in a packaged RecompStudio build."""
from __future__ import annotations

import json
import sys
from pathlib import Path


def bundle_root() -> Path | None:
    """Resolve the bundle directory in source, PyInstaller one-dir, or one-file mode."""
    candidates: list[Path] = []
    frozen_root = getattr(sys, "_MEIPASS", None)
    if frozen_root:
        candidates.append(Path(frozen_root) / "recompstudio" / "bundled")
        candidates.append(Path(frozen_root) / "bundled")
    candidates.append(Path(__file__).resolve().parent / "bundled")
    for candidate in candidates:
        if candidate.is_dir():
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
    manifest = bundle_manifest()
    info = manifest.get("toolchain")
    if not isinstance(info, dict):
        return None
    asset = info.get("asset")
    if not isinstance(asset, str) or Path(asset).name != asset:
        return None
    archive = root / "toolchains" / asset
    if archive.is_file():
        return archive, info
    return None
