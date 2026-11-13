"""Framework-aware project creation and native recompiler dispatch.

The upstreams do not share one project generator. This module calls PSXRecomp
and SNESRecomp's real wizards and creates pinned starter workspaces for engines
that still require per-game reverse engineering and integration.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Sequence

from .manager import FrameworkError, FrameworkManager
from .registry import get_framework
from .toolchains import environment as toolchain_environment

WORKFLOW = """name: RecompStudio build
on:
  workflow_dispatch:
  push:
    branches: [main, master]
  pull_request:
permissions:
  contents: read
jobs:
  build:
    strategy:
      fail-fast: false
      matrix:
        os: [windows-2022, macos-15, ubuntu-24.04]
    runs-on: ${{ matrix.os }}
    steps:
      - uses: actions/checkout@v4
        with:
          submodules: recursive
      - name: Install CMake and Ninja
        uses: lukka/get-cmake@v3
        with:
          cmakeVersion: '~3.30.0'
          ninjaVersion: latest
      - name: Build on Windows
        if: runner.os == 'Windows'
        shell: pwsh
        run: |
          if (Test-Path build.ps1) {
            ./build.ps1
          } elseif (Test-Path CMakeLists.txt) {
            cmake -S . -B build
            cmake --build build --config Release --parallel
          } else {
            Write-Host 'Setup-only project: game host/build files are not configured yet; build skipped.'
          }
      - name: Build on macOS and Linux
        if: runner.os != 'Windows'
        shell: bash
        run: |
          if [ -f build.sh ]; then
            bash ./build.sh
          elif [ -f CMakeLists.txt ]; then
            cmake -S . -B build
            cmake --build build --config Release --parallel
          else
            echo 'Setup-only project: game host/build files are not configured yet; build skipped.'
          fi
"""

GITIGNORE = """# RecompStudio local-only settings and build output
.recompstudio/local.json
.recompstudio/cache/
.recompstudio/setup.log
build/
build-*/
out/
dist/
*.log
*.tmp

# Never commit user-supplied ROMs, disc images, BIOS or firmware
inputs/
roms/
discs/
bios/
firmware/
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
*.sms
*.gg
*.vb
*.vboy
*.bin
*.gen
*.rom
*.fds
*.v64
*.z64
*.n64
*.cdi
*.xbe
*.xiso
*.dol
*.wad
*.sav
*.srm
*.state
*.mcs
"""


def _run(command: Sequence[str], cwd: Path, timeout: int = 1800,
         env: dict | None = None) -> str:
    try:
        child_env = toolchain_environment()
        if env:
            supplied_path = env.get("PATH", "")
            child_env.update(env)
            pack = toolchain_environment().get("RETCOMM_TOOLCHAIN_DIR")
            if pack:
                pack_bins = [str(Path(pack) / "bin"), str(Path(pack) / "python" / "bin"), str(Path(pack) / "python")]
                child_env["PATH"] = os.pathsep.join([p for p in pack_bins if Path(p).is_dir()] + ([supplied_path] if supplied_path else []))
        proc = subprocess.run(
            list(map(str, command)), cwd=cwd, env=child_env,
            capture_output=True, text=True, encoding="utf-8",
            errors="replace", check=False, timeout=timeout
        )
    except FileNotFoundError as exc:
        raise FrameworkError(
            f"Required command not found: {command[0]}. Check the Toolchain tab."
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise FrameworkError(
            f"Command timed out after {timeout}s: {' '.join(map(str, command))}"
        ) from exc
    output = (proc.stdout or "") + (("\n" + proc.stderr) if proc.stderr else "")
    if proc.returncode:
        detail = "\n".join(output.splitlines()[-100:])
        raise FrameworkError(
            f"Command failed (exit {proc.returncode}): "
            f"{' '.join(map(str, command))}\n{detail}"
        )
    return output.strip()


def _slug(name: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", name.strip()).strip("-.")
    if not slug or slug in {".", ".."}:
        raise FrameworkError("Project name must contain at least one letter or number.")
    return slug


def _git(root: Path, *args: str, timeout: int = 900) -> str:
    return _run(["git", "-C", root, *args], root, timeout=timeout)


def _write_local_settings(root: Path, input_path: Path | None,
                          bios_path: Path | None) -> None:
    meta = root / ".recompstudio"
    meta.mkdir(parents=True, exist_ok=True)
    local = {
        "schema_version": 1,
        "input_image": str(input_path.expanduser().resolve()) if input_path else None,
        "bios_image": str(bios_path.expanduser().resolve()) if bios_path else None,
    }
    (meta / "local.json").write_text(
        json.dumps(local, indent=2) + "\n", encoding="utf-8"
    )


def _write_manifest(root: Path, item: dict, name: str,
                    submodule_path: str) -> None:
    module = root / submodule_path
    git_marker = module / ".git"
    commit = ""
    if git_marker.exists() or git_marker.is_file():
        commit = _git(root, "-C", module, "rev-parse", "HEAD")
    manifest = {
        "schema_version": 1,
        "name": name,
        "framework": {
            "id": item["id"],
            "name": item["name"],
            "repository": item["repository"],
            "ref": item.get("ref"),
            "pinned_commit": commit,
            "submodule_path": submodule_path,
            "status": item.get("status", "unknown"),
        },
    }
    meta = root / ".recompstudio"
    meta.mkdir(parents=True, exist_ok=True)
    (meta / "project.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )


def load_local_settings(root: Path) -> dict:
    path = root / ".recompstudio" / "local.json"
    if not path.exists():
        return {"input_image": None, "bios_image": None}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FrameworkError(f"Cannot read local project settings: {exc}") from exc
    if not isinstance(data, dict):
        raise FrameworkError("Local project settings have an invalid format.")
    return data


def load_project_manifest(root: Path) -> dict:
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


def set_project_inputs(root: Path, input_path: Path | None = None,
                       bios_path: Path | None = None) -> None:
    root = root.expanduser().resolve()
    load_project_manifest(root)
    current = load_local_settings(root)
    if input_path is not None:
        if not input_path.expanduser().is_file():
            raise FrameworkError(f"Game input file not found: {input_path}")
        current["input_image"] = str(input_path.expanduser().resolve())
    if bios_path is not None:
        if not bios_path.expanduser().is_file():
            raise FrameworkError(f"BIOS/firmware image not found: {bios_path}")
        current["bios_image"] = str(bios_path.expanduser().resolve())
    meta = root / ".recompstudio"
    meta.mkdir(exist_ok=True)
    (meta / "local.json").write_text(
        json.dumps(current, indent=2) + "\n", encoding="utf-8"
    )


def _install_for_wizard(framework_id: str) -> Path:
    manager = FrameworkManager()
    path = manager.path_for(framework_id)
    if not ((path / ".git").exists() or (path / ".git").is_file()):
        manager.install(framework_id)
    return path


def _discover_created_project(workspace: Path, before: set[Path],
                              preferred: Path | None = None) -> Path:
    if preferred and preferred.exists() and (preferred / ".git").exists():
        return preferred
    created = [
        p for p in workspace.iterdir()
        if p.is_dir() and p not in before and (p / ".git").exists()
    ]
    if len(created) == 1:
        return created[0]
    candidates = [p for p in created if (p / "CMakeLists.txt").exists()]
    if len(candidates) == 1:
        return candidates[0]
    raise FrameworkError(
        "The upstream setup script finished, but RecompStudio could not identify "
        "the project folder. Inspect the workspace and Activity log."
    )


def _sanitize_psx_project_paths(root: Path) -> None:
    """Remove host-specific disc paths from Git-tracked PSX wizard output.

    The actual disc is kept in .recompstudio/local.json (gitignored). The
    framework generator is invoked with --disc explicitly, and the runtime
    can ask the user to select a disc on first launch.
    """
    game_toml = root / "game.toml"
    if game_toml.is_file():
        lines = game_toml.read_text(encoding="utf-8").splitlines()
        safe_lines: list[str] = []
        in_game_section = False
        for line in lines:
            section = re.match(r"^\s*\[([^]]+)\]\s*(?:#.*)?$", line)
            if section:
                in_game_section = section.group(1).strip() == "game"
            if in_game_section and re.match(r"^\s*disc\s*=", line):
                # 'disc' is a machine-local image path. Do not remove 'discs'
                # arrays should an upstream template start supporting them.
                continue
            safe_lines.append(line)
        game_toml.write_text("\n".join(safe_lines) + "\n", encoding="utf-8")

    probe_json = root / "disc_probe.json"
    if probe_json.is_file():
        try:
            data = json.loads(probe_json.read_text(encoding="utf-8"))
            cue_path = data.get("cue_path")
            if isinstance(cue_path, str):
                data["cue_path"] = re.split(r"[/\\]", cue_path)[-1]
                probe_json.write_text(
                    json.dumps(data, indent=2) + "\n", encoding="utf-8"
                )
        except (OSError, json.JSONDecodeError, AttributeError):
            # A malformed upstream diagnostic file should not prevent setup;
            # the app's own local input path remains safely ignored.
            pass


def _append_setup_log(root: Path, output: str) -> None:
    meta = root / ".recompstudio"
    meta.mkdir(exist_ok=True)
    (meta / "setup.log").write_text(output[-50000:], encoding="utf-8")
    with (root / ".gitignore").open("a", encoding="utf-8") as stream:
        stream.write("\n# Local diagnostics\n.recompstudio/setup.log\n")


def _ensure_ci(root: Path) -> None:
    folder = root / ".github" / "workflows"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "recompstudio-build.yml"
    if not path.exists():
        path.write_text(WORKFLOW, encoding="utf-8")


def _run_psx_wizard(item: dict, name: str, workspace: Path, disc: Path,
                    bios: Path | None, players: int) -> Path:
    checkout = _install_for_wizard(str(item["id"]))
    workspace.mkdir(parents=True, exist_ok=True)
    before = set(workspace.iterdir())
    slug = _slug(name)
    env = os.environ.copy()
    env["PSXRECOMP_URL"] = str(item["repository"])
    env["RECOMP_UI_URL"] = "https://github.com/RetroPortingToolKit/recomp-ui.git"

    if os.name == "nt":
        script = checkout / "tools" / "new_project_layout" / "setup_project.ps1"
        command = [
            "powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", script,
            "-Disc", disc.resolve(), "-Dir", workspace.resolve(),
            "-Name", name, "-GithubRepo", slug, "-Players", str(players), "-Yes",
            "-EnableRecompUi", "-NoNetplay", "-NoFetchBoxart", "-Generate",
            "-EnableBuild", "-NoGithub", "-PsxrecompUrl", item["repository"],
            "-RecompUiUrl", env["RECOMP_UI_URL"],
        ]
        if bios:
            command.extend(["-Bios", bios.resolve()])
    else:
        script = checkout / "tools" / "new_project_layout" / "setup_project.sh"
        command = [
            "bash", script, "--disc", disc.resolve(), "--dir", workspace.resolve(),
            "--name", name, "--github-repo", slug, "--players", str(players),
            "--enable-recomp-ui", "--no-netplay", "--no-fetch-boxart",
            "--generate", "--enable-build", "--no-github", "--yes",
        ]
        if bios:
            command.extend(["--bios", bios.resolve()])

    output = _run(command, checkout, timeout=7200, env=env)
    root = _discover_created_project(workspace, before, workspace / slug)
    _sanitize_psx_project_paths(root)
    _write_manifest(root, item, name, "psxrecomp")
    _write_local_settings(root, disc, bios)
    with (root / ".gitignore").open("a", encoding="utf-8") as stream:
        stream.write("\n# RecompStudio host-local paths\n.recompstudio/local.json\n")
    _ensure_ci(root)
    _append_setup_log(root, output)
    return root


def _run_snes_wizard(item: dict, name: str, workspace: Path,
                     rom: Path, players: int) -> Path:
    checkout = _install_for_wizard(str(item["id"]))
    workspace.mkdir(parents=True, exist_ok=True)
    before = set(workspace.iterdir())
    if os.name == "nt":
        script = checkout / "tools" / "new_project" / "setup_project.ps1"
        command = [
            "powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", script,
            "-Rom", rom.resolve(), "-Dir", workspace.resolve(), "-Name", name,
            "-Players", str(players), "-Yes", "--recomp-ui", "--no-netplay",
            "--no-fetch-boxart", "--no-github", "--generate", "--build",
            "--snesrecomp-url", item["repository"],
            "--recomp-ui-url", "https://github.com/RetroPortingToolKit/recomp-ui.git",
        ]
    else:
        script = checkout / "tools" / "new_project" / "setup_project.sh"
        command = [
            "bash", script, "--rom", rom.resolve(), "--dir", workspace.resolve(),
            "--name", name, "--players", str(players), "--yes", "--recomp-ui",
            "--no-netplay", "--no-fetch-boxart", "--no-github", "--generate", "--build",
            "--snesrecomp-url", item["repository"],
            "--recomp-ui-url", "https://github.com/RetroPortingToolKit/recomp-ui.git",
        ]
    output = _run(command, checkout, timeout=7200)
    root = _discover_created_project(workspace, before)
    _write_manifest(root, item, name, "snesrecomp")
    _write_local_settings(root, rom, None)
    with (root / ".gitignore").open("a", encoding="utf-8") as stream:
        stream.write("\n# RecompStudio host-local paths\n.recompstudio/local.json\n")
    _ensure_ci(root)
    _append_setup_log(root, output)
    return root


def _framework_docs(item: dict, input_path: Path | None) -> str:
    fw_id = item["id"]
    docs = item.get("project_docs") or item["repository"]
    rom = str(input_path) if input_path else "<path to your ROM/disc>"
    if fw_id == "nesrecomp":
        details = """The NES cycle backend generates code during CMake configure. It can build a headless host before a custom window or title-specific hooks are added."""
        commands = f"""cmake -S frameworks/nesrecomp/runner/cyc/project -B build -DNESRECOMP_ROM="{rom}" -DNESRECOMP_HEADLESS=ON
cmake --build build --config Release --parallel"""
    elif fw_id == "gbarecomp":
        details = """GBARecomp emits a generated static library and build glue, not a complete game host. A playable title still needs host/runtime integration; a successful generation is not a finished port."""
        commands = f"""cmake -S frameworks/gbarecomp -B build/gbarecomp-core
cmake --build build/gbarecomp-core --config Release --target gba_recompile --parallel
GBARECOMP_CORE="<path-to-gba_recompile>" python frameworks/gbarecomp/tools/cli.py build --rom "{rom}" --output gba-generated"""
    elif fw_id == "segagenesisrecomp":
        details = """A verified title-specific game.toml is required. Generated C must be connected to a game-specific host/runtime adapter."""
        commands = f"""cmake -S frameworks/segagenesisrecomp/recompiler -B build/genesis-recompiler
cmake --build build/genesis-recompiler --config Release --parallel
build/genesis-recompiler/GenesisRecomp "{rom}" --game game.toml --output-dir generated"""
    elif fw_id == "smsggrecomp":
        details = """A title-specific game.toml and companion host project are required. Each game runner is maintained separately."""
        commands = f"""cmake -S frameworks/smsggrecomp/recompiler -B build/smsgg-recompiler
cmake --build build/smsgg-recompiler --config Release --parallel
build/smsgg-recompiler/SmsRecomp "{rom}" --game game.toml"""
    elif fw_id == "cdirecomp":
        details = """CD-i titles require a CD-RTOS system ROM and a Mode-2 CUE/BIN disc. Module seeds and title-specific OS-9 export layouts may be required; RecompStudio does not guess them."""
        commands = """cmake -S frameworks/cdirecomp/recompiler -B build/cdi-recompiler
cmake --build build/cdi-recompiler --config Release --parallel
cmake -S frameworks/cdirecomp/runner -B build/cdi-runtime
cmake --build build/cdi-runtime --config Release --parallel"""
    elif fw_id == "vbrecomp":
        details = """This builds the generic runtime/debug host. A playable cartridge requires a separate per-game host and generated V810 code; upstream does not expose a turnkey generic new-game wizard."""
        commands = """git -C frameworks/vbrecomp submodule update --init --recursive
cmake -S frameworks/vbrecomp -B build/vbrecomp
cmake --build build/vbrecomp --target vb-runtime --parallel"""
    elif fw_id == "ndsrecomp":
        details = """NDSRecomp is pre-alpha. Its demo workflow requires verified BIOS/firmware/game inputs and generated ARM9/ARM7 banks. A clean-clone game wizard is not currently available."""
        commands = """cmake -G Ninja -B build/nds-recompiler frameworks/ndsrecomp/recompiler
cmake --build build/nds-recompiler --parallel"""
    elif fw_id == "xboxllr":
        details = """Windows-only developer beta. Requires MSVC, Windows SDK, CMake, dependency toolchains, title metadata, and prepared local inputs."""
        commands = """xboxllr.exe --help
xboxllr.exe --framework <path-to-xboxllr> title --help
xboxllr.exe --framework <path-to-xboxllr> prepare --help"""
    elif fw_id == "gcnlle":
        details = """Early Windows-oriented research for GameCube IPL/firmware, not a general GameCube game compiler."""
        commands = """Follow the gcnlle README; its tested build currently uses MSYS2/MinGW64, CMake, and Ninja."""
    elif fw_id.startswith("dolrecomp"):
        details = """The mstan gcnrecomp branch is an IPL integration fork. Use the ExpansionPak repository for general-purpose DolRecomp development."""
        commands = """Initialize recursive submodules, then follow the upstream CMake and game-integration docs."""
    elif fw_id.startswith("n64recomp"):
        details = """The mstan fork is tied to Pokémon Stadium work. A generic N64 port requires its own ROM-specific configuration and game host."""
        commands = """Build N64Recomp using its CMake project and follow the upstream title configuration guide."""
    else:
        details = """This is an experimental or development-fork integration. Review upstream status, license, and supported-host notes before starting a port."""
        commands = "Follow the upstream getting-started guide and companion game-project documentation."
    return f"""# {item['name']} project

Upstream: {item['repository']}

Framework guide: {docs}

Current upstream status: {item.get('status', 'unknown')}

## What RecompStudio can automate

{details}

## First commands

    {commands.replace(chr(10), chr(10) + '    ')}

## Local inputs and privacy

RecompStudio keeps absolute ROM and BIOS paths in the ignored .recompstudio/local.json file on this computer only. The paths are not committed or copied. Set them again on another machine.

## GitHub

This project includes a pinned Git submodule, project manifest, .gitignore, and a Windows/macOS/Linux workflow starter. Commit configuration and original project source. Never commit user ROMs, BIOS dumps, game-derived generated code, or personal save data.
"""


def _create_generic_workspace(name: str, framework_id: str, workspace: Path,
                              input_path: Path | None,
                              bios_path: Path | None) -> Path:
    item = get_framework(framework_id)
    workspace = workspace.expanduser().resolve()
    workspace.mkdir(parents=True, exist_ok=True)
    root = workspace / _slug(name)
    if root.exists():
        raise FrameworkError(f"Project already exists: {root}")
    root.mkdir(parents=True)
    try:
        _run(["git", "init", "-b", "main"], root)
        submodule = Path("frameworks") / framework_id
        command = ["git", "submodule", "add"]
        if item.get("ref"):
            command.extend(["--branch", str(item["ref"])])
        command.extend(["--", str(item["repository"]), submodule.as_posix()])
        _run(command, root, timeout=1800)
        _run(["git", "-C", root / submodule, "submodule", "update", "--init", "--recursive"], root, timeout=1800)
        (root / ".gitignore").write_text(GITIGNORE, encoding="utf-8")
        _write_manifest(root, item, name, submodule.as_posix())
        _write_local_settings(root, input_path, bios_path)
        _ensure_ci(root)
        (root / "README.md").write_text(
            _framework_docs(item, input_path), encoding="utf-8"
        )
        return root
    except Exception:
        shutil.rmtree(root, ignore_errors=True)
        raise


def create_framework_project(name: str, framework_id: str, workspace: Path,
                              input_path: Path | None = None,
                              bios_path: Path | None = None,
                              players: int = 1) -> Path:
    item = get_framework(framework_id)
    if input_path is not None and not input_path.expanduser().is_file():
        raise FrameworkError(f"Game ROM/disc not found: {input_path}")
    if bios_path is not None and not bios_path.expanduser().is_file():
        raise FrameworkError(f"BIOS/firmware image not found: {bios_path}")
    if framework_id == "psxrecomp":
        if input_path is None:
            raise FrameworkError("PSXRecomp's upstream wizard requires a .cue disc image.")
        return _run_psx_wizard(item, name, workspace.expanduser().resolve(), input_path, bios_path, players)
    if framework_id == "snesrecomp":
        if input_path is None:
            raise FrameworkError("SNESRecomp's upstream wizard requires an .sfc/.smc ROM.")
        return _run_snes_wizard(item, name, workspace.expanduser().resolve(), input_path, players)
    return _create_generic_workspace(name, framework_id, workspace, input_path, bios_path)


def _find_executable(root: Path, names: tuple[str, ...]) -> Path:
    candidates: list[Path] = []
    for name in names:
        candidates.extend(root.rglob(name))
        candidates.extend(root.rglob(name + ".exe"))
    candidates = [path for path in candidates if path.is_file()]
    if not candidates:
        raise FrameworkError(
            f"Could not find built tool {', '.join(names)}. Check the framework build output."
        )
    return candidates[0]


def recompile_project(project_path: Path, verbose: bool = False) -> str:
    root = project_path.expanduser().resolve()
    manifest = load_project_manifest(root)
    item = get_framework(manifest["framework"]["id"])
    fw = root / manifest["framework"].get("submodule_path", "frameworks/" + item["id"])
    local = load_local_settings(root)
    input_value = local.get("input_image")
    bios_value = local.get("bios_image")
    rom = Path(input_value).expanduser() if input_value else None
    bios = Path(bios_value).expanduser() if bios_value else None
    if rom is not None and not rom.is_file():
        raise FrameworkError(f"Saved ROM/disc path no longer exists: {rom}. Choose it again in Project settings.")
    if bios is not None and not bios.is_file():
        raise FrameworkError(f"Saved BIOS path no longer exists: {bios}. Choose it again in Project settings.")

    if item["id"] == "psxrecomp":
        if not rom:
            raise FrameworkError("Set a PS1 .cue file in Project settings first.")
        command = [sys.executable, "psxrecomp/psxrecomp_cli.py", "generate",
                   "--config", "game.toml", "--project-root", ".", "--disc", rom.resolve()]
        if bios:
            command.extend(["--bios", bios.resolve()])
        return _run(command, root, timeout=7200)

    if item["id"] == "snesrecomp":
        if not rom:
            raise FrameworkError("Set a SNES .sfc/.smc file in Project settings first.")
        return _run(["bash", "tools/regen.sh", "--rom", rom.resolve()], root, timeout=7200)

    if item["id"] == "nesrecomp":
        if not rom:
            raise FrameworkError("Set a NES .nes file in Project settings first.")
        build = root / "build" / "nes-cycle"
        command = ["cmake", "-S", fw / "runner" / "cyc" / "project", "-B", build,
                   f"-DNESRECOMP_ROM={rom.resolve()}", "-DNESRECOMP_HEADLESS=ON"]
        config = root / "game.toml"
        if config.is_file():
            command.append(f"-DNESRECOMP_GAME_CONFIG={config.resolve()}")
        output = _run(command, root, timeout=3600)
        output += "\n" + _run(["cmake", "--build", build, "--config", "Release", "--parallel"], root, timeout=7200)
        return output

    if item["id"] == "gbarecomp":
        if not rom:
            raise FrameworkError("Set a GBA .gba ROM in Project settings first.")
        build = root / "build" / "gbarecomp-core"
        configure = ["cmake", "-S", fw, "-B", build]
        if shutil.which("ninja"):
            configure.extend(["-G", "Ninja"])
        output = _run(configure, root, timeout=3600)
        output += "\n" + _run(["cmake", "--build", build, "--config", "Release",
                                "--target", "gba_recompile", "--parallel"], root, timeout=7200)
        core = _find_executable(build, ("gba_recompile",))
        generated = root / "gba-generated"
        generated.mkdir(exist_ok=True)
        env = os.environ.copy()
        env["GBARECOMP_CORE"] = str(core)
        command = [sys.executable, fw / "tools" / "cli.py", "build", "--rom",
                   rom.resolve(), "--output", generated, "--force"]
        if verbose:
            command.append("--verbose")
        output += "\n" + _run(command, root, timeout=7200, env=env)
        return output

    if item["id"] == "segagenesisrecomp":
        if not rom:
            raise FrameworkError("Set a Genesis .bin/.gen cartridge file first.")
        config = root / "game.toml"
        if not config.is_file():
            raise FrameworkError("GenesisRecomp needs a verified game.toml before generation. See the framework guide.")
        build = root / "build" / "genesis-recompiler"
        configure = ["cmake", "-S", fw / "recompiler", "-B", build]
        if shutil.which("ninja"):
            configure.extend(["-G", "Ninja"])
        output = _run(configure, root, timeout=3600)
        output += "\n" + _run(["cmake", "--build", build, "--config", "Release", "--parallel"], root, timeout=7200)
        exe = _find_executable(build, ("GenesisRecomp",))
        output += "\n" + _run([exe, rom.resolve(), "--game", config,
                                "--output-dir", root / "generated"], root, timeout=7200)
        return output

    if item["id"] == "smsggrecomp":
        if not rom:
            raise FrameworkError("Set an .sms or .gg ROM in Project settings first.")
        config = root / "game.toml"
        if not config.is_file():
            raise FrameworkError("SMS/GG Recomp needs a title-specific game.toml before generation. See the framework guide.")
        build = root / "build" / "smsgg-recompiler"
        configure = ["cmake", "-S", fw / "recompiler", "-B", build]
        if shutil.which("ninja"):
            configure.extend(["-G", "Ninja"])
        output = _run(configure, root, timeout=3600)
        output += "\n" + _run(["cmake", "--build", build, "--config", "Release", "--parallel"], root, timeout=7200)
        exe = _find_executable(build, ("SmsRecomp",))
        output += "\n" + _run([exe, rom.resolve(), "--game", config], root, timeout=7200)
        return output

    if item["id"] == "cdirecomp":
        if not rom:
            raise FrameworkError("Set a CD-i Mode-2 .cue file first.")
        if not bios:
            raise FrameworkError("CD-i recompile requires a user-supplied CD-RTOS system ROM. Set it in Project settings.")
        build = root / "build" / "cdi-recompiler"
        configure = ["cmake", "-S", fw / "recompiler", "-B", build]
        if shutil.which("ninja"):
            configure.extend(["-G", "Ninja"])
        output = _run(configure, root, timeout=3600)
        output += "\n" + _run(["cmake", "--build", build, "--config", "Release", "--parallel"], root, timeout=7200)
        bios_tool = _find_executable(build, ("CdiRecompBios",))
        disc_tool = _find_executable(build, ("CdiRecomp",))
        output += "\n" + _run([bios_tool, bios.resolve(), "--emit"], root, timeout=7200)
        output += "\n" + _run([disc_tool, rom.resolve(), "--emit", "--out",
                                root / "generated" / "cdi"], root, timeout=7200)
        return output

    if item["id"] == "vbrecomp":
        raise FrameworkError(
            "VBRecomp does not yet expose a general-purpose new-cartridge generation command. "
            "A separate per-game host and integration are still required."
        )
    if item["id"] == "ndsrecomp":
        raise FrameworkError(
            "NDSRecomp is pre-alpha and has no turnkey clean-clone game generation workflow. "
            "Its BIOS/firmware bank configuration and ARM9/ARM7 dispatch must be prepared manually."
        )
    if item["id"] == "xboxllr":
        if os.name != "nt":
            raise FrameworkError("XboxLLR's current developer toolkit is Windows x64 only.")
        raise FrameworkError(
            "XboxLLR requires a prepared title repository and private local/paths.json inputs. "
            "Use the upstream xboxllr.exe prepare/title workflow documented in docs/BUILD-TOOL.md."
        )
    if item["id"] == "gcnlle":
        raise FrameworkError(
            "gcnlle currently targets the GameCube IPL/firmware, not arbitrary retail game images."
        )
    if item["id"].startswith("n64recomp"):
        raise FrameworkError(
            "This N64Recomp checkout is tied to title-specific Pokémon Stadium work. "
            "Prepare a game-specific config and host before code generation."
        )
    if item["id"].startswith("dolrecomp"):
        raise FrameworkError(
            "DolRecomp needs a game-specific loader/runtime project. The mstan fork is an IPL integration."
        )
    if item["id"] == "gbrecompiled-mstan-fork":
        raise FrameworkError(
            "mstan/gbrecompiled is a development fork with per-game build glue. Follow its README and companion project instructions."
        )
    raise FrameworkError(f"No recompile adapter is registered for {item['name']} yet.")


def build_project(project_path: Path) -> str:
    root = project_path.expanduser().resolve()
    manifest = load_project_manifest(root)
    item = get_framework(manifest["framework"]["id"])
    if item["id"] == "nesrecomp":
        build = root / "build" / "nes-cycle"
        if not build.exists():
            return recompile_project(root)
        return _run(["cmake", "--build", build, "--config", "Release", "--parallel"], root, timeout=7200)
    if item["id"] == "gbarecomp":
        generated = root / "gba-generated"
        if not generated.exists():
            return recompile_project(root)
        build = generated / "build"
        output = _run(["cmake", "-S", generated, "-B", build], root, timeout=3600)
        output += "\n" + _run(["cmake", "--build", build, "--config", "Release", "--parallel"], root, timeout=7200)
        return output
    if item["id"] in {"psxrecomp", "snesrecomp"}:
        candidates = [root / "build-release", root / "build"] if item["id"] == "psxrecomp" else [root / "build", root / "build-release"]
        build = next((path for path in candidates if path.exists()), None)
        if build is None:
            raise FrameworkError("No configured build directory found. Run Recompile first.")
        return _run(["cmake", "--build", build, "--config", "Release", "--parallel"], root, timeout=7200)
    raise FrameworkError(
        f"{item['name']} does not yet have a complete game-host build configured. "
        "Build the title-specific runner described in the README before packaging."
    )


def update_project_framework(project_path: Path) -> str:
    root = project_path.expanduser().resolve()
    manifest = load_project_manifest(root)
    rel = manifest["framework"].get("submodule_path")
    if not rel:
        raise FrameworkError("Project manifest has no framework submodule path.")
    submodule = root / rel
    if not submodule.exists():
        raise FrameworkError(f"Framework submodule is missing: {submodule}")
    if _git(root, "-C", submodule, "status", "--porcelain"):
        raise FrameworkError("Framework submodule has local changes; commit or stash them before updating.")
    _run(["git", "-C", submodule, "fetch", "--all", "--prune"], root, timeout=900)
    ref = manifest["framework"].get("ref")
    if ref:
        # Explicit catalog branches (for example the mstan GCN IPL branch).
        _run(["git", "-C", submodule, "checkout", str(ref)], root)
        _run(["git", "-C", submodule, "pull", "--ff-only", "origin", str(ref)], root, timeout=900)
    else:
        # A freshly initialized submodule is normally detached at its pinned
        # commit. Resolve the upstream default branch and reattach before pull;
        # plain "git pull" in detached HEAD fails on a clean clone.
        symref = _run(
            ["git", "-C", submodule, "ls-remote", "--symref", "origin", "HEAD"],
            root, timeout=300,
        )
        branch = next(
            (line.split()[1].removeprefix("refs/heads/")
             for line in symref.splitlines()
             if line.startswith("ref: refs/heads/") and len(line.split()) >= 2),
            "",
        )
        if not branch:
            raise FrameworkError(
                "Could not determine the framework's upstream default branch. "
                "The pinned revision was left unchanged."
            )
        _run(
            ["git", "-C", submodule, "checkout", "-B", branch, f"origin/{branch}"],
            root,
        )
        _run(
            ["git", "-C", submodule, "pull", "--ff-only", "origin", branch],
            root, timeout=900,
        )
    _run(["git", "-C", submodule, "submodule", "update", "--init", "--recursive"], root, timeout=900)
    commit = _git(root, "-C", submodule, "rev-parse", "HEAD")
    manifest["framework"]["pinned_commit"] = commit
    (root / ".recompstudio" / "project.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    return commit


def push_project(project_path: Path, message: str) -> str:
    root = project_path.expanduser().resolve()
    load_project_manifest(root)
    if not message.strip():
        raise FrameworkError("A commit message is required.")
    _git(root, "add", "-A")
    staged = _git(root, "diff", "--cached", "--name-only")
    if staged:
        _git(root, "commit", "-m", message)
    remotes = _git(root, "remote").splitlines()
    if "origin" not in remotes:
        raise FrameworkError(
            "No origin remote configured. Use project publish or add a GitHub remote first."
        )
    branch = _git(root, "branch", "--show-current") or "main"
    _git(root, "push", "-u", "origin", branch, timeout=900)
    return "Project committed and pushed to origin."


def publish_project(project_path: Path, repository: str,
                    visibility: str = "private") -> str:
    root = project_path.expanduser().resolve()
    load_project_manifest(root)
    if visibility not in {"private", "public"}:
        raise FrameworkError("Visibility must be private or public.")
    if not shutil.which("gh"):
        raise FrameworkError("GitHub CLI (gh) is required. Install it and run gh auth login.")
    _git(root, "add", "-A")
    if _git(root, "diff", "--cached", "--name-only"):
        _git(root, "commit", "-m", "Initial RecompStudio project")
    _run([
        "gh", "repo", "create", repository, "--source", root,
        "--remote", "origin", f"--{visibility}", "--push"
    ], root, timeout=900)
    return f"Created and pushed {repository} ({visibility})."
