"""Load and refresh RecompStudio's data-driven upstream registry."""

from __future__ import annotations

import json
import shutil
import sys
import urllib.request
from pathlib import Path
from typing import Any

CATALOG_URL = (
    "https://raw.githubusercontent.com/nvd123-YT/RecompStudio/main/"
    "recompstudio/data/frameworks.json"
)


def app_data_dir() -> Path:
    """Return an OS-appropriate per-user data directory."""
    if sys.platform == "win32":
        base = Path.home() / "AppData" / "Local"
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path.home() / ".local" / "share"
    result = base / "RecompStudio"
    result.mkdir(parents=True, exist_ok=True)
    return result


def bundled_catalog_path() -> Path:
    return Path(__file__).resolve().parent / "data" / "frameworks.json"


def cached_catalog_path() -> Path:
    return app_data_dir() / "frameworks.json"


def _read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as stream:
        data = json.load(stream)
    if not isinstance(data, dict) or not isinstance(data.get("frameworks"), list):
        raise ValueError(f"Invalid RecompStudio catalog: {path}")
    return data


def load_catalog() -> dict[str, Any]:
    """Load cached registry first, then the catalog bundled with the app."""
    cache = cached_catalog_path()
    if cache.is_file():
        try:
            return _read_json(cache)
        except (OSError, ValueError, json.JSONDecodeError):
            # A damaged cache must not prevent the app from starting.
            cache.unlink(missing_ok=True)
    return _read_json(bundled_catalog_path())


def refresh_catalog(timeout: int = 15) -> dict[str, Any]:
    """Fetch the latest registry; keep the installed catalog on network failure."""
    request = urllib.request.Request(
        CATALOG_URL,
        headers={"User-Agent": "RecompStudio/0.1 (+framework-catalog-refresh)"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        raw = response.read()
    data = json.loads(raw.decode("utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("frameworks"), list):
        raise ValueError("The upstream catalog has an unexpected format.")
    # Validate unique IDs and required fields before replacing the current cache.
    seen: set[str] = set()
    for item in data["frameworks"]:
        if not isinstance(item, dict):
            raise ValueError("Catalog entries must be JSON objects.")
        for required in ("id", "name", "repository", "category"):
            if not item.get(required):
                raise ValueError(f"Catalog entry is missing {required!r}.")
        if item["id"] in seen:
            raise ValueError(f"Duplicate catalog ID: {item['id']}")
        seen.add(item["id"])
    target = cached_catalog_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_suffix(".json.tmp")
    temp.write_bytes(raw)
    temp.replace(target)
    return data


def frameworks(include_components: bool = True) -> list[dict[str, Any]]:
    entries = load_catalog()["frameworks"]
    if include_components:
        return entries
    return [item for item in entries if item.get("category") == "framework"]


def get_framework(framework_id: str) -> dict[str, Any]:
    for item in frameworks():
        if item.get("id") == framework_id:
            return item
    raise KeyError(f"Unknown framework: {framework_id}")


def validate_catalog() -> list[str]:
    errors: list[str] = []
    ids: set[str] = set()
    for item in frameworks():
        entry_id = str(item.get("id", ""))
        if not entry_id:
            errors.append("An entry has no id.")
        elif entry_id in ids:
            errors.append(f"Duplicate id: {entry_id}")
        ids.add(entry_id)
        repository = str(item.get("repository", ""))
        if not repository.startswith("https://github.com/"):
            errors.append(f"{entry_id}: repository must be a GitHub HTTPS URL.")
    return errors
