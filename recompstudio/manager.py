"""Safe Git-based framework installation and update operations."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .registry import app_data_dir, get_framework, frameworks


class FrameworkError(RuntimeError):
    """A user-facing framework operation error."""


@dataclass
class FrameworkStatus:
    framework_id: str
    name: str
    installed: bool
    path: Path
    commit: str = ""
    branch: str = ""
    dirty: bool = False
    behind: int | None = None
    error: str = ""

    @property
    def summary(self) -> str:
        if self.error:
            return "Error"
        if not self.installed:
            return "Not installed"
        if self.dirty:
            return "Local changes — update blocked"
        if self.behind is not None and self.behind > 0:
            return f"{self.behind} update(s) available"
        return "Up to date"


class FrameworkManager:
    def __init__(self, root: Path | None = None):
        self.root = (root or (app_data_dir() / "frameworks")).expanduser()
        self.root.mkdir(parents=True, exist_ok=True)

    def path_for(self, framework_id: str) -> Path:
        get_framework(framework_id)  # Fail early for unknown IDs.
        return self.root / framework_id

    @staticmethod
    def _git(path: Path | None, *args: str, timeout: int = 180) -> str:
        command = ["git"]
        if path is not None:
            command.extend(["-C", str(path)])
        command.extend(args)
        try:
            result = subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
            )
        except FileNotFoundError as exc:
            raise FrameworkError("Git was not found. Install Git and reopen RecompStudio.") from exc
        except subprocess.TimeoutExpired as exc:
            raise FrameworkError(f"Git command timed out: {' '.join(command)}") from exc
        if result.returncode != 0:
            detail = result.stderr.strip() or result.stdout.strip()
            raise FrameworkError(detail or f"Git exited with code {result.returncode}.")
        return result.stdout.strip()

    def install(self, framework_id: str) -> Path:
        item = get_framework(framework_id)
        destination = self.path_for(framework_id)
        if destination.exists():
            if (destination / ".git").exists():
                raise FrameworkError(
                    f"{item['name']} is already installed at {destination}. "
                    "Use update instead."
                )
            raise FrameworkError(
                f"Refusing to replace the existing non-Git directory: {destination}"
            )
        destination.parent.mkdir(parents=True, exist_ok=True)
        command = ["clone", "--recurse-submodules"]
        ref = item.get("ref")
        if ref:
            command.extend(["--branch", str(ref)])
        command.extend([str(item["repository"]), str(destination)])
        self._git(None, *command, timeout=900)
        # A clone is not considered installed until all declared submodules are ready.
        self._git(destination, "submodule", "update", "--init", "--recursive", timeout=900)
        return destination

    def update(self, framework_id: str) -> FrameworkStatus:
        item = get_framework(framework_id)
        path = self.path_for(framework_id)
        if not (path / ".git").exists():
            raise FrameworkError(f"{item['name']} is not installed. Install it first.")
        dirty = bool(self._git(path, "status", "--porcelain"))
        if dirty:
            raise FrameworkError(
                f"{item['name']} has local changes. Commit or stash them before updating; "
                "RecompStudio will not discard your work."
            )
        self._git(path, "fetch", "--all", "--prune", timeout=900)
        ref = item.get("ref")
        if ref:
            self._git(path, "checkout", str(ref))
            self._git(path, "pull", "--ff-only", "origin", str(ref), timeout=900)
        else:
            branch = self._git(path, "branch", "--show-current")
            upstream = self._git(path, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}")
            if not upstream:
                raise FrameworkError(
                    f"{item['name']} has no upstream branch configured; refusing an unsafe update."
                )
            self._git(path, "pull", "--ff-only", timeout=900)
        self._git(path, "submodule", "update", "--init", "--recursive", timeout=900)
        return self.status_one(framework_id, fetch=False)

    def status_one(self, framework_id: str, fetch: bool = False) -> FrameworkStatus:
        item = get_framework(framework_id)
        path = self.path_for(framework_id)
        status = FrameworkStatus(
            framework_id=framework_id,
            name=str(item["name"]),
            installed=(path / ".git").exists(),
            path=path,
        )
        if not status.installed:
            return status
        try:
            if fetch:
                self._git(path, "fetch", "--all", "--prune", timeout=180)
            status.commit = self._git(path, "rev-parse", "--short", "HEAD")
            status.branch = self._git(path, "branch", "--show-current") or "detached"
            status.dirty = bool(self._git(path, "status", "--porcelain"))
            if status.dirty:
                return status
            try:
                upstream = self._git(
                    path, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"
                )
                if upstream:
                    count = self._git(path, "rev-list", "--count", f"HEAD..{upstream}")
                    status.behind = int(count)
            except (FrameworkError, ValueError):
                # No upstream is common for explicitly pinned detached checkouts.
                status.behind = None
        except FrameworkError as exc:
            status.error = str(exc)
        return status

    def statuses(self, fetch: bool = False) -> list[FrameworkStatus]:
        results = []
        for item in frameworks():
            results.append(self.status_one(str(item["id"]), fetch=fetch))
        return results

    def update_all(self) -> tuple[list[FrameworkStatus], list[tuple[str, str]]]:
        updated: list[FrameworkStatus] = []
        failures: list[tuple[str, str]] = []
        for item in frameworks():
            framework_id = str(item["id"])
            path = self.path_for(framework_id)
            if not (path / ".git").exists():
                continue
            try:
                updated.append(self.update(framework_id))
            except FrameworkError as exc:
                failures.append((framework_id, str(exc)))
        return updated, failures

    def open_folder(self, framework_id: str) -> Path:
        path = self.path_for(framework_id)
        if not path.exists():
            raise FrameworkError(f"{framework_id} is not installed.")
        return path
