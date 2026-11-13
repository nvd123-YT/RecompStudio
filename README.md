# RecompStudio

**One workspace for static game recompilation.** RecompStudio is a cross-platform desktop GUI and CLI for discovering, installing, updating, and using independent recompilation frameworks.

> Frameworks are kept as separate Git checkouts. RecompStudio never merges their source trees or silently rewrites local changes.

## Current scope

- Framework catalog for PSX, SNES, NES, GBA, Genesis/Mega Drive, Virtual Boy, Nintendo DS (experimental), Nintendo 64, and GameCube (experimental).
- Shared components including the common recompilation UI, networking support, CPU backends, and toolchain bundles.
- Per-framework install, status, update, and update-all operations.
- Project scaffolding with a pinned framework Git submodule, a portable project manifest, Git ignore rules, and a cross-platform GitHub Actions starter workflow.
- GUI and scriptable CLI use the same backend.

The catalog is data-driven in `catalog/frameworks.json`. New frameworks and upstream changes can be added without changing the app's core.

## Requirements

- Python 3.10+
- Git 2.30+
- Tkinter for the desktop GUI (usually included with Python)
- CMake, Ninja, and a C/C++ toolchain for frameworks that use CMake

RecompStudio detects tools; it does not silently install system packages or elevated drivers. Framework-specific requirements are shown by `doctor`.

## Run from source

```bash
python -m recompstudio gui
```

Install as a Python command:

```bash
python -m pip install .
recompstudio gui
```

## CLI

```bash
recompstudio frameworks list
recompstudio frameworks install psxrecomp
recompstudio frameworks update psxrecomp
recompstudio frameworks update-all
recompstudio frameworks status
recompstudio doctor
recompstudio project new --name MyGame --framework psxrecomp --workspace ~/RecompProjects
recompstudio project build /path/to/MyGame
```

Use `python -m recompstudio` instead of `recompstudio` when running from a source checkout.

## Framework update model

Each framework lives in its own checkout under the RecompStudio data directory:

- macOS: `~/Library/Application Support/RecompStudio/frameworks`
- Windows: `%LOCALAPPDATA%\\RecompStudio\\frameworks`
- Linux: `~/.local/share/RecompStudio/frameworks`

Install uses `git clone --recurse-submodules`. Update fetches the upstream remote, checks for local modifications, and performs a fast-forward-only update. It refuses to overwrite local changes. Each game project pins its framework as a Git submodule, so projects remain reproducible and can choose when to advance to a newer framework commit.

The catalog itself can be refreshed from this repository's `main` branch. Catalog updates do not force framework updates; those are separate, explicit actions.

## Project portability

A project stores its framework ID, remote URL, and pinned commit in `.recompstudio/project.json`. The framework is a normal Git submodule, not an absolute path into the user's machine. The generated GitHub Actions workflow checks out submodules and provides Windows, macOS, and Linux build jobs. Actual game generation/build commands remain framework-specific; RecompStudio invokes a detected project build script or CMake project rather than pretending every console uses the same recompiler CLI.

## Legal and source-image policy

RecompStudio does not bundle game ROMs, disc images, BIOS dumps, copyrighted game assets, or generated game code. Users provide their own legally obtained inputs. Frameworks and toolchains retain their respective upstream licenses; see the catalog and each upstream repository before redistributing a build.

## Development

```bash
python -m unittest discover -s tests -v
python -m recompstudio doctor --json
```
