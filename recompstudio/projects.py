"""Portable project scaffolding and Git/GitHub helpers."""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Sequence

from .manager import FrameworkError
from .registry import get_framework

GITHUB_WORKFLOW = """name: Build recompiled game
on:
  push:
    branches: [main, master]
  pull_request:
  workflow_dispatch:
permissions:
  contents: read
jobs:
  build:
    name: Build on ${{ matrix.os }}
    strategy:
      fail-fast: false
      matrix:
        os: [ubuntu-24.04, macos-14, windows-2022]
    runs-on: ${{ matrix.os }}
    steps:
      - name: Check out project and pinned framework
        uses: actions/checkout@v4
        with:
          submodules: recursive
      - name: Set up CMake and Ninja
        uses: lukka/get-cmake@latest
        with:
          cmakeVersion: '~3.30.0'
          ninjaVersion: latest
      - name: Build game project
        shell: pwsh
        run: |
          if ($IsWindows -and (Test-Path 'build.ps1')) {
            ./build.ps1
          } elseif (-not $IsWindows -and (Test-Path 'build.sh')) {
            bash ./build.sh
          } elseif (Test-Path 'CMakeLists.txt') {
            cmake -S . -B build -G Ninja -DCMAKE_BUILD_TYPE=Release
            cmake --build build --config Release --parallel
          } else {
            Write-Error 'No game build entry point yet. Complete the framework-specific setup and add build.ps1, build.sh, or CMakeLists.txt.'
          }
"""

GITIGNORE = """# Local build output
.recompstudio/cache/
build/
build-*/
out/
dist/
.cache/
*.log

# User-supplied game images and firmware; never commit these
inputs/
roms/
discs/
bios/
*.iso
*.chd
*.cue
*.gcm
*.gcz
*.wbfs
*.wud
*.wux
*.3ds
*.cia
*.nds
*.gba
*.gbc
*.gb
*.nes
*.sfc
*.smc
*.vb
*.vboy
"""


def _run(command: Sequence[str], cwd: Path, timeout: int = 900) -> str:
    try:
        result = subprocess.run(
            list(command), cwd=cwd, check=False, capture_output=True,
            text=True, encoding="utf-8", errors="replace", timeout=timeout
        )
    except FileNotFoundError as exc:
        raise FrameworkError(f"Required command not found: {command[0]}") from exc
    except subprocess.TimeoutExpired as exc:
        raise FrameworkError(f"Command timed out: {' '.join(command)}") from exc
    if result.returncode:
        detail = result.stderr.strip() or result.stdout.strip()
        raise FrameworkError(detail or f"Command failed ({result.returncode}): {' '.join(command)}")
    return result.stdout.strip()


def _slug(name: str) -> str:
    value = re.sub(r"[^A-Za-z0-9._-]+", "-", name.strip()).strip("-.")
    if not value or value in {".", ".."}:
        raise ValueError("Choose a project name containing letters or numbers.")
    return value


def create_project(name: str, framework_id: str, workspace: Path,
                  input_path: Path | None = None, bios_path: Path | None = None) -> Path:
    """Create a Git-ready project with its framework pinned as a Git submodule."""
    item = get_framework(framework_id)
    workspace = workspace.expanduser().resolve()
    workspace.mkdir(parents=True, exist_ok=True)
    root = workspace / _slug(name)
    if root.exists():
        raise FrameworkError(f"Project already exists: {root}")
    root.mkdir(parents=True)
    try:
        _run(["git", "init", "-b", "main"], root)
        rel = Path("frameworks") / framework_id
        rel.parent.mkdir(parents=True, exist_ok=True)
        ref = item.get("ref")
        command = ["git", "submodule", "add"]
        if ref:
            command.extend(["--branch", str(ref)])
        command.extend(["--", str(item["repository"]), rel.as_posix()])
        _run(command, root, timeout=900)
        commit = _run(["git", "-C", str(root / rel), "rev-parse", "HEAD"], root)

        meta = root / ".recompstudio"
        meta.mkdir()
        config = {
            "schema_version": 1,
            "name": name,
            "framework": {
                "id": framework_id, "name": item["name"],
                "repository": item["repository"], "ref": ref,
                "pinned_commit": commit, "submodule_path": rel.as_posix()
            },
            "input_image": str(input_path.expanduser().resolve()) if input_path else None,
            "bios_image": str(bios_path.expanduser().resolve()) if bios_path else None,
            "build": {"strategy": "auto"}
        }
        (meta / "project.json").write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
        (root / ".gitignore").write_text(GITIGNORE, encoding="utf-8")
        workflow = root / ".github" / "workflows"
        workflow.mkdir(parents=True)
        (workflow / "build.yml").write_text(GITHUB_WORKFLOW, encoding="utf-8")
        readme = f"""# {name}

A game project based on {item['name']}.

## Framework pin
- Framework: {item['name']}
- Upstream: {item['repository']}
- Pinned commit: {commit}
- Local checkout: {rel.as_posix()}

The framework is a Git submodule, keeping upstream history separate. Use RecompStudio's Update Project Framework command to deliberately move this project to a newer revision.

## Next steps
1. Read the upstream project-creation guide: {item.get('project_docs', item['repository'])}
2. Supply your own legally obtained game image and any required BIOS/firmware.
3. Complete the framework-specific game setup; add generated project code and assets here.
4. Add build.sh, build.ps1, or a root CMakeLists.txt for the game's actual build.
5. Push with: recompstudio project push . --message "Initial game project"

The starter GitHub Actions workflow checks out submodules and is configured for Windows, macOS, and Linux. RecompStudio does not package ROMs, disc images, BIOS dumps, or proprietary game assets.
"""
        (root / "README.md").write_text(readme, encoding="utf-8")
        return root
    except Exception:
        if not (root / ".git").exists():
            shutil.rmtree(root, ignore_errors=True)
        raise


def load_project(project_path: Path) -> dict:
    root = project_path.expanduser().resolve()
    path = root / ".recompstudio" / "project.json"
    if not path.is_file():
        raise FrameworkError(f"No RecompStudio project manifest found under {root}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FrameworkError(f"Cannot read project manifest: {exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("framework"), dict):
        raise FrameworkError("Project manifest has an unsupported format.")
    return data


def build_project(project_path: Path) -> str:
    """Invoke a project's build script or CMake entry point."""
    root = project_path.expanduser().resolve()
    load_project(root)
    if sys.platform == "win32":
        script = root / "build.ps1"
        if script.is_file():
            shell = "pwsh" if shutil.which("pwsh") else "powershell"
            return _run([shell, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script)], root)
    else:
        script = root / "build.sh"
        if script.is_file():
            return _run(["bash", str(script)], root)
    if (root / "CMakeLists.txt").is_file():
        build_dir = root / "build"
        _run(["cmake", "-S", str(root), "-B", str(build_dir)], root)
        return _run(["cmake", "--build", str(build_dir), "--parallel"], root, timeout=1800)
    raise FrameworkError(
        "The framework is pinned, but game-specific setup has not created a build entry point. "
        "Follow the upstream guide, then add build.sh, build.ps1, or CMakeLists.txt."
    )


def update_project_framework(project_path: Path) -> str:
    """Advance a project's framework submodule without force or data loss."""
    root = project_path.expanduser().resolve()
    config = load_project(root)
    rel = config["framework"].get("submodule_path", "frameworks/" + config["framework"]["id"])
    submodule = root / rel
    if not submodule.exists():
        raise FrameworkError(f"Framework submodule is missing: {submodule}")
    if _run(["git", "-C", str(submodule), "status", "--porcelain"], root):
        raise FrameworkError("Framework submodule has local changes; commit or stash them first.")
    _run(["git", "submodule", "update", "--init", "--recursive"], root, timeout=900)
    _run(["git", "-C", str(submodule), "fetch", "--all", "--prune"], root, timeout=900)
    ref = config["framework"].get("ref")
    if ref:
        _run(["git", "-C", str(submodule), "checkout", str(ref)], root)
        _run(["git", "-C", str(submodule), "pull", "--ff-only", "origin", str(ref)], root, timeout=900)
    else:
        _run(["git", "-C", str(submodule), "pull", "--ff-only"], root, timeout=900)
    _run(["git", "-C", str(submodule), "submodule", "update", "--init", "--recursive"], root, timeout=900)
    commit = _run(["git", "-C", str(submodule), "rev-parse", "HEAD"], root)
    config["framework"]["pinned_commit"] = commit
    (root / ".recompstudio" / "project.json").write_text(
        json.dumps(config, indent=2) + "\n", encoding="utf-8"
    )
    return commit


def push_project(project_path: Path, message: str) -> str:
    """Stage and commit project changes, then push to the configured origin."""
    root = project_path.expanduser().resolve()
    load_project(root)
    if not message.strip():
        raise FrameworkError("A non-empty commit message is required.")
    _run(["git", "add", "-A"], root)
    changed = _run(["git", "diff", "--cached", "--name-only"], root)
    if changed:
        _run(["git", "commit", "-m", message], root)
    remotes = _run(["git", "remote"], root).splitlines()
    if "origin" not in remotes:
        raise FrameworkError(
            "No origin remote is configured. Create a repository with gh repo create "
            "or add one with git remote add origin URL."
        )
    branch = _run(["git", "branch", "--show-current"], root) or "main"
    _run(["git", "push", "-u", "origin", branch], root, timeout=900)
    return "Project pushed successfully."


def publish_project(project_path: Path, repository: str, visibility: str = "private") -> str:
    """Create a GitHub repository with GitHub CLI and push the project."""
    root = project_path.expanduser().resolve()
    load_project(root)
    if visibility not in {"private", "public"}:
        raise FrameworkError("Visibility must be private or public.")
    if not shutil.which("gh"):
        raise FrameworkError("GitHub CLI (gh) is required. Install it and run gh auth login.")
    _run(["git", "add", "-A"], root)
    staged = _run(["git", "diff", "--cached", "--name-only"], root)
    if staged:
        _run(["git", "commit", "-m", "Initial RecompStudio project"], root)
    _run([
        "gh", "repo", "create", repository, "--source", str(root),
        "--remote", "origin", f"--{visibility}", "--push"
    ], root, timeout=900)
    return f"Created and pushed {repository} ({visibility})."
