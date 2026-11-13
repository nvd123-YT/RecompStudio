"""Fetch-on-demand integration with the shared RetComM toolchain packs.

The pack is installed in the ecosystem-wide RetComM cache, not inside the
RecompStudio application or an individual game repository.
"""
from __future__ import annotations

import json
import os
import platform
import shutil
import sys
import tempfile
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

RELEASE_API = "https://api.github.com/repos/RetroPortingToolKit/RetroPorting-Toolchains/releases/latest"
PACK_ID = "cmake-clang-v1"


class ToolchainError(RuntimeError):
    pass


@dataclass
class ToolchainRelease:
    version: str
    tag: str
    asset_name: str
    download_url: str
    size: int
    published_at: str = ""


def retcomm_data_home() -> Path:
    override = os.environ.get("RETCOMM_DATA_HOME")
    if override:
        return Path(override).expanduser()
    if sys.platform == "win32":
        return Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))) / "retcomm"
    xdg = os.environ.get("XDG_DATA_HOME")
    base = Path(xdg).expanduser() if xdg else Path.home() / ".local" / "share"
    return base / "retcomm"


def pack_cache_root() -> Path:
    override = os.environ.get("RETCOMM_TOOLCHAIN_CACHE")
    if override:
        return Path(override).expanduser()
    custom_pack = os.environ.get("RETCOMM_TOOLCHAIN_DIR")
    if custom_pack:
        return Path(custom_pack).expanduser().parent
    return retcomm_data_home() / "toolchains" / PACK_ID


def expected_platform() -> tuple[str, str]:
    machine = platform.machine().lower()
    if sys.platform == "win32":
        if machine not in {"amd64", "x86_64"}:
            raise ToolchainError(f"No {PACK_ID} pack is published for Windows {machine}.")
        return "windows-x64", "windows-x64"
    if sys.platform == "darwin":
        if machine not in {"arm64", "aarch64", "x86_64", "amd64"}:
            raise ToolchainError(f"No {PACK_ID} pack is published for macOS {machine}.")
        return "macos-universal", "macos-universal"
    if sys.platform.startswith("linux"):
        if machine not in {"x86_64", "amd64"}:
            raise ToolchainError(f"No {PACK_ID} pack is published for Linux {machine}.")
        return "linux-x64", "linux-x64"
    raise ToolchainError(f"Unsupported host platform: {sys.platform}")


def _request(url: str, accept: str = "application/vnd.github+json", timeout: int = 30):
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "RecompStudio/0.1",
            "Accept": accept,
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        return urllib.request.urlopen(request, timeout=timeout)
    except Exception as exc:
        raise ToolchainError(f"Could not reach the RetComM toolchain release service: {exc}") from exc


def latest_release(timeout: int = 30) -> ToolchainRelease:
    asset_suffix, _ = expected_platform()
    with _request(RELEASE_API, timeout=timeout) as response:
        data = json.loads(response.read().decode("utf-8"))
    tag = str(data.get("tag_name", "")).strip()
    version = tag.lstrip("vV")
    if not version:
        raise ToolchainError("The latest RetComM release did not provide a version tag.")
    assets = data.get("assets") or []
    matches = [
        asset for asset in assets
        if str(asset.get("name", "")).lower().endswith(f"{asset_suffix}.zip")
        and str(asset.get("name", "")).startswith(PACK_ID)
    ]
    if not matches:
        raise ToolchainError(
            f"RetComM {tag} does not publish a {asset_suffix} asset. "
            "Check the upstream toolchain releases."
        )
    asset = matches[0]
    url = str(asset.get("browser_download_url", ""))
    if not url.startswith("https://"):
        raise ToolchainError("The selected toolchain asset has no HTTPS download URL.")
    return ToolchainRelease(
        version=version,
        tag=tag,
        asset_name=str(asset.get("name", "")),
        download_url=url,
        size=int(asset.get("size") or 0),
        published_at=str(data.get("published_at", "")),
    )


def _version_tuple(version: str) -> tuple[int, ...]:
    parts = []
    for part in version.split("."):
        digits = "".join(ch for ch in part if ch.isdigit())
        parts.append(int(digits or 0))
    return tuple(parts)


def _read_pack_manifest(root: Path) -> dict | None:
    manifest = root / "retcomm-toolchain.json"
    if not manifest.is_file():
        return None
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
        if data.get("id") != PACK_ID:
            return None
        return data
    except (OSError, json.JSONDecodeError, AttributeError):
        return None


def installed_packs() -> list[tuple[str, Path]]:
    root = pack_cache_root()
    if not root.is_dir():
        return []
    result = []
    for child in root.iterdir():
        if not child.is_dir():
            continue
        manifest = _read_pack_manifest(child)
        if manifest:
            result.append((str(manifest.get("version", child.name)), child))
    return sorted(result, key=lambda pair: _version_tuple(pair[0]))


def active_pack() -> Path | None:
    custom = os.environ.get("RETCOMM_TOOLCHAIN_DIR")
    if custom:
        path = Path(custom).expanduser()
        if _read_pack_manifest(path):
            return path
        raise ToolchainError(f"RETCOMM_TOOLCHAIN_DIR is not a valid {PACK_ID} pack: {path}")
    latest_pointer = pack_cache_root() / "latest"
    if latest_pointer.is_file():
        version = latest_pointer.read_text(encoding="utf-8").strip()
        candidate = pack_cache_root() / version
        if _read_pack_manifest(candidate):
            return candidate
    packs = installed_packs()
    return packs[-1][1] if packs else None


def _safe_extract(archive: zipfile.ZipFile, destination: Path) -> None:
    root = destination.resolve()
    for member in archive.infolist():
        target = (destination / member.filename).resolve()
        if target != root and root not in target.parents:
            raise ToolchainError(f"Unsafe path in toolchain ZIP: {member.filename}")
    archive.extractall(destination)


def _download(url: str, destination: Path, progress: Callable[[int, int], None] | None = None,
              timeout: int = 180) -> None:
    with _request(url, accept="application/octet-stream", timeout=timeout) as response:
        total = int(response.headers.get("Content-Length") or 0)
        done = 0
        with destination.open("wb") as stream:
            while True:
                block = response.read(1024 * 1024)
                if not block:
                    break
                stream.write(block)
                done += len(block)
                if progress:
                    progress(done, total)


def install_latest(progress: Callable[[int, int], None] | None = None,
                   status: Callable[[str], None] | None = None,
                   force: bool = False) -> Path:
    release = latest_release()
    cache = pack_cache_root()
    cache.mkdir(parents=True, exist_ok=True)
    target = cache / release.version
    manifest = _read_pack_manifest(target)
    if manifest and not force:
        (cache / "latest").write_text(release.version, encoding="utf-8")
        return target
    if status:
        status(f"Downloading {release.asset_name} ({release.size // (1024 * 1024)} MB)…")
    with tempfile.TemporaryDirectory(prefix="recompstudio-toolchain-") as temp_name:
        temp = Path(temp_name)
        archive_path = temp / release.asset_name
        _download(release.download_url, archive_path, progress)
        extract_dir = temp / "unpacked"
        extract_dir.mkdir()
        try:
            with zipfile.ZipFile(archive_path) as archive:
                _safe_extract(archive, extract_dir)
        except (zipfile.BadZipFile, OSError) as exc:
            raise ToolchainError(f"Downloaded toolchain archive is invalid: {exc}") from exc

        source = extract_dir
        if not (source / "retcomm-toolchain.json").is_file():
            nested = list(extract_dir.rglob("retcomm-toolchain.json"))
            if len(nested) != 1:
                raise ToolchainError("Toolchain ZIP did not contain one retcomm-toolchain.json manifest.")
            source = nested[0].parent

        extracted_manifest = _read_pack_manifest(source)
        if not extracted_manifest:
            raise ToolchainError("Toolchain pack manifest is invalid or has the wrong pack id.")
        expected_os, manifest_os = expected_platform()
        actual_os = str(extracted_manifest.get("os", ""))
        if actual_os and actual_os not in {manifest_os, expected_os}:
            raise ToolchainError(
                f"Downloaded toolchain is for {actual_os}, but this system requires {expected_os}."
            )

        # Preserve old versions side by side so projects pinned to an earlier
        # toolchain floor can keep building. A failed replacement never deletes
        # the currently active pack.
        staging = cache / (release.version + ".installing")
        if staging.exists():
            shutil.rmtree(staging)
        shutil.copytree(source, staging)
        if target.exists():
            backup = cache / (release.version + ".previous")
            if backup.exists():
                shutil.rmtree(backup)
            target.rename(backup)
            try:
                staging.rename(target)
            except Exception:
                backup.rename(target)
                raise
            shutil.rmtree(backup, ignore_errors=True)
        else:
            staging.rename(target)

    (cache / "latest").write_text(release.version, encoding="utf-8")
    if status:
        status(f"Installed shared RetComM toolchain {release.version}.")
    return target


def environment() -> dict[str, str]:
    """Return a child-process environment with the active pack preferred."""
    result = os.environ.copy()
    pack = active_pack()
    if not pack:
        return result
    paths = [pack / "bin", pack / "python" / "bin", pack / "python"]
    additions = [str(path) for path in paths if path.is_dir()]
    old_path = result.get("PATH", "")
    result["PATH"] = os.pathsep.join(additions + ([old_path] if old_path else []))
    result["RETCOMM_TOOLCHAIN_DIR"] = str(pack)
    return result


def status() -> dict:
    try:
        release = latest_release()
        current = active_pack()
        current_manifest = _read_pack_manifest(current) if current else None
        current_version = str(current_manifest.get("version")) if current_manifest else None
        return {
            "available": True,
            "latest_version": release.version,
            "latest_asset": release.asset_name,
            "latest_size": release.size,
            "installed_version": current_version,
            "installed_path": str(current) if current else None,
            "update_available": bool(current_version and _version_tuple(release.version) > _version_tuple(current_version)),
            "installed": current is not None,
        }
    except ToolchainError as exc:
        current = active_pack()
        current_manifest = _read_pack_manifest(current) if current else None
        return {
            "available": False,
            "error": str(exc),
            "installed": current is not None,
            "installed_version": str(current_manifest.get("version")) if current_manifest else None,
            "installed_path": str(current) if current else None,
        }
