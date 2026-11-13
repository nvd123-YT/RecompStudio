"""On-demand, per-user installations of external development tools."""
from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
import zipfile
from pathlib import Path
from typing import Callable

RELEASE_APIS = {
    "git": "https://api.github.com/repos/git-for-windows/git/releases/latest",
    "github-cli": "https://api.github.com/repos/cli/cli/releases/latest",
    "java21": "https://api.github.com/repos/adoptium/temurin21-binaries/releases/latest",
    "ghidra": "https://api.github.com/repos/NationalSecurityAgency/ghidra/releases/latest",
}
TOOL_IDS = ("git", "github-cli", "java21", "ghidra")


class ManagedToolError(RuntimeError):
    """A recoverable installation or discovery error."""


def tools_home() -> Path:
    override = os.environ.get("RECOMPSTUDIO_TOOLS_HOME")
    if override:
        return Path(override).expanduser()
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local")))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local" / "share"))).expanduser()
    return base / "RecompStudio" / "tools"


def _request(url: str, accept: str = "application/vnd.github+json", timeout: int = 45):
    headers = {
        "User-Agent": "RecompStudio/0.1 (+managed-tools)",
        "Accept": accept,
        "X-GitHub-Api-Version": "2022-11-28",
    }
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        return urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=timeout)
    except Exception as exc:
        raise ManagedToolError(f"Could not reach the tool release service: {exc}") from exc


def _select_asset(
    tool_id: str,
    assets: list[dict],
    *,
    os_name: str | None = None,
    machine: str | None = None,
) -> dict:
    os_name = os_name or sys.platform
    machine = (machine or platform.machine()).lower()
    arm = machine in {"arm64", "aarch64"}
    if tool_id == "ghidra":
        pattern = r"ghidra_.*_PUBLIC_.*\.zip"
    elif tool_id == "github-cli":
        if os_name == "win32":
            suffix = "windows_amd64.zip"
        elif os_name == "darwin":
            suffix = "macOS_arm64.zip" if arm else "macOS_amd64.zip"
        elif str(os_name).startswith("linux"):
            suffix = "linux_amd64.tar.gz"
        else:
            suffix = ""
        match = next((a for a in assets if str(a.get("name", "")).endswith(suffix)), None)
        if not match:
            raise ManagedToolError(f"No compatible {tool_id} asset was found for {os_name}/{machine}.")
        return match
    elif tool_id == "git":
        pattern = r"MinGit-[0-9.]+-64-bit\.zip"
    elif tool_id == "java21":
        if os_name == "win32":
            pattern = r"OpenJDK21U-jdk_x64_windows_hotspot_.*\.zip"
        elif os_name == "darwin":
            arch = "aarch64" if arm else "x64"
            pattern = rf"OpenJDK21U-jdk_{arch}_mac_hotspot_.*\.tar\.gz"
        elif str(os_name).startswith("linux"):
            pattern = r"OpenJDK21U-jdk_x64_linux_hotspot_.*\.tar\.gz"
        else:
            pattern = r"$a"
    else:
        raise ManagedToolError(f"Unknown managed tool: {tool_id}")
    match = next((a for a in assets if re.fullmatch(pattern, str(a.get("name", "")))), None)
    if not match:
        raise ManagedToolError(f"No compatible {tool_id} asset was found for {os_name}/{machine}.")
    return match


def _release_asset(tool_id: str) -> tuple[str, dict]:
    api = RELEASE_APIS.get(tool_id)
    if not api:
        raise ManagedToolError(f"Unknown managed tool: {tool_id}")
    with _request(api) as response:
        release = json.loads(response.read().decode("utf-8"))
    tag = str(release.get("tag_name", "")).strip()
    if not tag:
        raise ManagedToolError(f"The latest {tool_id} release has no version tag.")
    asset = _select_asset(tool_id, release.get("assets") or [])
    url = str(asset.get("browser_download_url", ""))
    if not url.startswith("https://"):
        raise ManagedToolError(f"The selected {tool_id} asset has no HTTPS download URL.")
    return tag, asset


def _safe_extract(archive_path: Path, destination: Path) -> None:
    root = destination.resolve()
    if zipfile.is_zipfile(archive_path):
        with zipfile.ZipFile(archive_path) as archive:
            for item in archive.infolist():
                target = (destination / item.filename).resolve()
                if target != root and root not in target.parents:
                    raise ManagedToolError(f"Unsafe ZIP path: {item.filename}")
            archive.extractall(destination)
        return
    try:
        archive = tarfile.open(archive_path, "r:*")
    except (tarfile.TarError, OSError) as exc:
        raise ManagedToolError(f"Unsupported or invalid tool archive: {exc}") from exc
    with archive:
        for item in archive.getmembers():
            target = (destination / item.name).resolve()
            if target != root and root not in target.parents:
                raise ManagedToolError(f"Unsafe TAR path: {item.name}")
            if item.issym() or item.islnk():
                link = Path(item.linkname)
                if link.is_absolute():
                    raise ManagedToolError(f"Unsafe TAR link: {item.name}")
                link_target = ((target.parent / link) if item.issym() else (root / link)).resolve()
                if link_target != root and root not in link_target.parents:
                    raise ManagedToolError(f"Unsafe TAR link: {item.name} -> {item.linkname}")
        archive.extractall(destination)


def _download(
    asset: dict,
    destination: Path,
    progress: Callable[[int, int], None] | None = None,
) -> None:
    digest = hashlib.sha256()
    total_expected = int(asset.get("size") or 0)
    done = 0
    with _request(str(asset["browser_download_url"]), "application/octet-stream", timeout=300) as response:
        total_expected = int(response.headers.get("Content-Length") or total_expected)
        with destination.open("wb") as output:
            while True:
                block = response.read(1024 * 1024)
                if not block:
                    break
                output.write(block)
                digest.update(block)
                done += len(block)
                if progress:
                    progress(done, total_expected)
    expected = str(asset.get("digest") or "")
    if expected.startswith("sha256:") and digest.hexdigest().lower() != expected.split(":", 1)[1].lower():
        destination.unlink(missing_ok=True)
        raise ManagedToolError(f"SHA-256 verification failed for {asset.get('name')}; file discarded.")


def _find_path(root: Path, names: set[str]) -> Path | None:
    for path in root.rglob("*"):
        if path.is_file() and path.name.lower() in names:
            return path
    return None


def _layout(tool_id: str, root: Path) -> dict[str, str]:
    if tool_id == "git":
        executable = _find_path(root, {"git.exe"})
        if executable is None:
            raise ManagedToolError("MinGit archive did not contain git.exe.")
        paths = [executable.parent]
        mingw_bin = root / "mingw64" / "bin"
        if mingw_bin.is_dir():
            paths.insert(0, mingw_bin)
        return {"executable": executable.relative_to(root).as_posix(),
                "path": os.pathsep.join(p.relative_to(root).as_posix() for p in paths)}
    if tool_id == "github-cli":
        names = {"gh.exe"} if sys.platform == "win32" else {"gh"}
        executable = _find_path(root, names)
        if executable is None:
            raise ManagedToolError("GitHub CLI archive did not contain its gh executable.")
        return {"executable": executable.relative_to(root).as_posix(),
                "path": executable.parent.relative_to(root).as_posix()}
    if tool_id == "java21":
        names = {"java.exe"} if sys.platform == "win32" else {"java"}
        executable = _find_path(root, names)
        if executable is None or executable.parent.name.lower() != "bin":
            raise ManagedToolError("Temurin archive did not contain a JDK bin/java executable.")
        home = executable.parent.parent
        return {"executable": executable.relative_to(root).as_posix(),
                "home": home.relative_to(root).as_posix(),
                "path": executable.parent.relative_to(root).as_posix()}
    if tool_id == "ghidra":
        names = {"analyzeheadless.bat"} if sys.platform == "win32" else {"analyzeheadless"}
        executable = _find_path(root, names)
        if executable is None:
            raise ManagedToolError("Ghidra archive did not contain support/analyzeHeadless.")
        home = executable.parent.parent
        return {"executable": executable.relative_to(root).as_posix(),
                "home": home.relative_to(root).as_posix(),
                "path": executable.parent.relative_to(root).as_posix()}
    raise ManagedToolError(f"Unknown managed tool: {tool_id}")


def _tool_root(tool_id: str) -> Path:
    return tools_home() / tool_id


def _active_install(tool_id: str) -> tuple[Path, dict] | None:
    root = _tool_root(tool_id)
    pointer = root / "latest"
    if not pointer.is_file():
        return None
    version = pointer.read_text(encoding="utf-8").strip()
    if not version or Path(version).name != version:
        return None
    install = root / version
    marker = install / "managed-tool.json"
    if not marker.is_file():
        return None
    try:
        info = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if info.get("id") != tool_id:
        return None
    if not (install / info.get("executable", "__missing__")).is_file():
        return None
    return install, info


def _install_one(
    tool_id: str,
    *,
    progress: Callable[[int, int], None] | None = None,
    status: Callable[[str], None] | None = None,
    force: bool = False,
) -> Path:
    tag, asset = _release_asset(tool_id)
    version = re.sub(r"[^A-Za-z0-9._+-]+", "_", tag)
    tool_root = _tool_root(tool_id)
    target = tool_root / version
    if not force:
        existing = _active_install(tool_id)
        if existing and existing[1].get("version") == tag:
            return existing[0]
    tool_root.mkdir(parents=True, exist_ok=True)
    if status:
        size_mb = int(asset.get("size") or 0) // (1024 * 1024)
        status(f"Downloading {asset.get('name')} ({size_mb} MB)…")
    with tempfile.TemporaryDirectory(prefix=f"recompstudio-{tool_id}-") as temp_name:
        temp = Path(temp_name)
        archive_path = temp / str(asset["name"])
        _download(asset, archive_path, progress)
        extract = temp / "extracted"
        extract.mkdir()
        _safe_extract(archive_path, extract)
        layout = _layout(tool_id, extract)
        staging = tool_root / (version + ".installing")
        if staging.exists():
            shutil.rmtree(staging)
        shutil.copytree(extract, staging, symlinks=True)
        marker = {
            "id": tool_id, "version": tag, "asset": str(asset["name"]),
            "sha256": str(asset.get("digest") or ""), **layout,
        }
        (staging / "managed-tool.json").write_text(
            json.dumps(marker, indent=2) + "\n", encoding="utf-8"
        )
        if target.exists():
            shutil.rmtree(target)
        staging.rename(target)
    pointer_tmp = tool_root / "latest.tmp"
    pointer_tmp.write_text(version, encoding="utf-8")
    pointer_tmp.replace(tool_root / "latest")
    if status:
        status(f"Installed {tool_id} {tag}.")
    return target


def install_latest(
    tool_id: str,
    *,
    progress: Callable[[int, int], None] | None = None,
    status: Callable[[str], None] | None = None,
    force: bool = False,
) -> Path | dict[str, Path]:
    """Install/update one tool, or both Java 21 and Ghidra."""
    if tool_id == "reverse-engineering":
        java = _install_one("java21", progress=progress, status=status, force=force)
        ghidra = _install_one("ghidra", progress=progress, status=status, force=force)
        return {"java21": java, "ghidra": ghidra}
    if tool_id == "git" and sys.platform != "win32":
        existing = shutil.which("git")
        if existing:
            if status:
                status(f"Using system Git: {existing}")
            return Path(existing)
        raise ManagedToolError(
            "This platform uses its native Git package. Install Git through Xcode Command Line Tools "
            "(macOS) or your Linux distribution, then reopen RecompStudio."
        )
    if tool_id not in TOOL_IDS:
        raise ManagedToolError(f"Unknown tool '{tool_id}'.")
    return _install_one(tool_id, progress=progress, status=status, force=force)


def environment(base: dict[str, str] | None = None) -> dict[str, str]:
    """Return a child environment with managed Git, gh, Java and Ghidra preferred."""
    result = dict(os.environ if base is None else base)
    additions: list[str] = []
    for tool_id in TOOL_IDS:
        active = _active_install(tool_id)
        if not active:
            continue
        install, info = active
        for relative in str(info.get("path", "")).split(os.pathsep):
            if relative:
                directory = install / relative
                if directory.is_dir():
                    additions.append(str(directory))
        if tool_id == "java21":
            result["JAVA_HOME"] = str(install / str(info["home"]))
        elif tool_id == "ghidra":
            home = install / str(info["home"])
            result["GHIDRA_HOME"] = str(home)
            result.setdefault("GHIDRA_INSTALL_DIR", str(home))
    old_path = result.get("PATH", "")
    result["PATH"] = os.pathsep.join(additions + ([old_path] if old_path else []))
    return result


def status() -> dict[str, dict]:
    managed_env = environment()
    report: dict[str, dict] = {}
    for tool_id in TOOL_IDS:
        active = _active_install(tool_id)
        command = ("git" if tool_id == "git" else "gh" if tool_id == "github-cli"
                   else "java" if tool_id == "java21"
                   else "analyzeHeadless.bat" if sys.platform == "win32" else "analyzeHeadless")
        found = shutil.which(command, path=managed_env.get("PATH"))
        info = active[1] if active else {}
        report[tool_id] = {
            "installed": bool(found), "managed": active is not None,
            "version": str(info.get("version") or ""), "path": str(found or ""),
        }
    return report
