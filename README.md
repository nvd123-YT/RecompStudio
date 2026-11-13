# RecompStudio

**One desktop studio for static recompilation.** RecompStudio combines a graphical project manager with a scriptable CLI for managing independent upstream frameworks, setting up game projects, running the real framework tools, and preparing projects for GitHub.

The desktop GUI is the primary workspace; every core operation is also available from the CLI. Frameworks stay as separate Git checkouts rather than being merged into one unstable source tree.

**Repository:** https://github.com/nvd123-YT/RecompStudio

## What is included

The framework catalog is data-driven in `recompstudio/data/frameworks.json`. The GUI reads the same registry as the CLI, and catalog refreshes do not require an application update.

**Packaged builds embed 18 licensed framework/component Git checkouts and a platform-specific RetComM compiler pack.** The source checkouts retain their Git metadata, recursive submodules, licences, and notices. On first launch, RecompStudio installs the bundled compiler pack locally. Frameworks are ready to use without a separate clone step; their writable copies are created only when the user chooses to update them.

### mstan and RetroPortingToolKit framework families

| System | Framework | Upstream status / limitations |
|---|---|---|
| PlayStation 1 | [PSXRecomp](https://github.com/RetroPortingToolKit/psxrecomp) | Beta; upstream project wizard integrated |
| Super Nintendo | [SNESRecomp](https://github.com/RetroPortingToolKit/snesrecomp) | Beta; upstream project wizard integrated |
| NES / Famicom | [NESRecomp](https://github.com/mstan/nesrecomp) | Beta; cycle-backend generation/build adapter |
| Game Boy Advance | [GBARecomp](https://github.com/mstan/gbarecomp) | Beta; native generator adapter; playable title still needs a host |
| Genesis / Mega Drive / Sega CD | [Genesis Recomp](https://github.com/mstan/segagenesisrecomp) | Beta; title config and host integration required; Sega CD is a separate development branch |
| Virtual Boy | [VBRecomp](https://github.com/mstan/vbrecomp) | Runtime/build support; per-game host and integration are still required |
| Nintendo DS | [NDSRecomp](https://github.com/RetroPortingToolKit/ndsrecomp) | Pre-alpha research; no turnkey clean-clone game wizard |
| Nintendo 64 | [N64Recomp (mstan project)](https://github.com/mstan/N64Recomp) | Pokémon Stadium-oriented; title-specific, not a generic turnkey scaffold |
| GameCube / Wii / Wii U | [DolRecomp](https://github.com/ExpansionPak/DolRecomp) | Experimental ecosystem; a title-specific loader/host is still required |
| GameCube IPL | [mstan DolRecomp integration](https://github.com/mstan/DolRecomp/tree/gcnrecomp) and [gcnrecomp](https://github.com/mstan/gcnlle) | Early IPL/firmware research, not a general retail-game recompiler |
| Game Boy / Game Boy Color | [GB Recompiled (mstan development fork)](https://github.com/mstan/gbrecompiled) | Development fork; canonical project is [arcanite24/gb-recompiled](https://github.com/arcanite24/gb-recompiled) |
| Master System / Game Gear | [SMS/GG Recomp](https://github.com/mstan/smsggrecomp) | Early pre-release; title-specific game configuration/runner required |
| Philips CD-i | [CD-i Recomp](https://github.com/mstan/cdirecomp) | Very early development; CD-RTOS ROM, disc, and module-specific configuration required |
| Original Xbox | [XboxLLR](https://github.com/mstan/xboxllr) | Early beta; developer toolchain is currently Windows x64-only and title preparation is required |

Catalog entries distinguish general frameworks, forks, integration experiments, shared components, and toolchain bundles. Experimental and title-specific entries are visible, but are not presented as production-ready or as generic one-click game converters.

Three repositories are deliberately not embedded in the public packages because they currently have no clear top-level redistribution licence: GenesisRecomp, mstan's GB Recompiled development fork, and SMS/GG Recomp. The mstan N64Recomp fork is also deferred because one of its recursive submodules points to an unavailable commit; the separately maintained N64Recomp upstream checkout is bundled. These entries remain in the catalog for upstream tracking, but RecompStudio does not package unlicensed or incomplete source snapshots. The embedded-source licence summary is shipped as `UPSTREAM_LICENSES.md` and is also inside each app bundle.

### Shared components and toolchains

RecompStudio also manages the shared pieces used by those engines:

- [recomp-ui](https://github.com/RetroPortingToolKit/recomp-ui): shared launcher and in-game settings UI.
- [recomp-net](https://github.com/RetroPortingToolKit/recomp-net): networking components for compatible projects.
- m68k, Z80, ARM, and PowerPC recompilation cores.
- [RetComM Toolchains](https://github.com/RetroPortingToolKit/RetroPorting-Toolchains): shared versioned compiler/CMake/Ninja packs for Windows, macOS, and Linux.

## Framework updates

Each packaged release includes a snapshot of every redistributable framework at the commit recorded in its bundle manifest. That gives a fresh install an offline-ready framework catalog. The embedded checkout itself is read-only; when a framework is updated, RecompStudio copies only that framework into the per-user data directory and updates the writable copy. Its source path is:

- Windows: `%LOCALAPPDATA%\RecompStudio\frameworks`
- macOS: `~/Library/Application Support/RecompStudio/frameworks`
- Linux: `~/.local/share/RecompStudio/frameworks`

Install clones the upstream repository and recursive submodules. Update fetches that framework alone and performs a fast-forward-only update. RecompStudio checks for uncommitted local changes and refuses to overwrite them. `update-all` processes each installed framework independently and reports any that could not be advanced.

Game projects pin a specific framework commit as a Git submodule. They move to newer framework revisions only when the project owner chooses **Update Project Framework** and commits the updated submodule pointer. This keeps an existing game project reproducible even as upstream frameworks change frequently.

The desktop launcher now records fatal startup errors to a per-user log and shows a native system alert even when Tk cannot initialize. The alert asks the user to try reopening once and gives the exact log path. Packaged release jobs also launch the built app in a hidden-window smoke test on each platform before publishing.\n\nThe app's framework registry is separate from the framework checkouts. **Refresh catalog** updates the list without forcing source updates or requiring a RecompStudio reinstall. Updating the app refreshes its embedded snapshot, while framework updates remain independent after installation.

## Shared compiler/toolchain packs

Use the **Toolchain** tab or:

```bash
recompstudio toolchains status
recompstudio toolchains install
recompstudio toolchains update
```

Packaged builds include the compatible RetComM `cmake-clang-v1` archive and its licence/third-party notices. First launch installs this archive from the local app resources, so initial toolchain setup does not require a separate download. The Toolchain tab and CLI can then check for a newer upstream release and update it while retaining older version folders. The user PATH is never permanently rewritten.

The pack provides CMake, Ninja, Clang/LLVM where published, embeddable CPython, zlib, and SDL3 support. It targets Windows x64, macOS universal (Intel and Apple Silicon), and Linux x86_64. macOS still requires Apple's Xcode Command Line Tools/SDK. XboxLLR currently requires Microsoft's MSVC and Windows SDK; those proprietary platform tools are not redistributed. Git is needed for framework updates and source control, and GitHub CLI is used to create repositories with `project publish`. Ghidra/Java are not yet included in the package; the Toolchain tab reports detected optional tools.

## Install and launch from source

To run from source: Python 3.10+, Git, and Tkinter for the GUI. Packaged releases include their Python runtime, framework snapshot, and compatible RetComM compiler bundle; Git remains required for framework updates and Git/GitHub operations.

```bash
git clone https://github.com/nvd123-YT/RecompStudio.git
cd RecompStudio
python -m pip install .
recompstudio gui
```

Or run without installing:

```bash
python -m recompstudio gui
```

## CLI

```bash
# Framework catalog and independent updates
recompstudio frameworks list
recompstudio frameworks install psxrecomp
recompstudio frameworks update psxrecomp
recompstudio frameworks update-all
recompstudio frameworks status --fetch
recompstudio frameworks refresh-catalog

# Shared compiler bundle
recompstudio toolchains status
recompstudio toolchains install

# Toolchain diagnostics
recompstudio doctor
recompstudio doctor --json

# Create a project; the ROM/disc is referenced locally and never copied into Git
recompstudio project new --name MyGame --framework psxrecomp \
  --workspace ~/RecompProjects --input /path/to/game.cue

# Run the selected framework's generator, then build where supported
recompstudio project recompile ~/RecompProjects/MyGame
recompstudio project build ~/RecompProjects/MyGame

# Update a project's pinned framework deliberately
recompstudio project update-framework ~/RecompProjects/MyGame

# Set machine-local inputs on another computer (ignored by Git)
recompstudio project set-input ~/RecompProjects/MyGame --input /path/to/game.cue

# Create a private GitHub repository and push, or push to an existing origin
recompstudio project publish ~/RecompProjects/MyGame --repo your-user/MyGame
recompstudio project push ~/RecompProjects/MyGame --message "Update game project"
```

Use `python -m recompstudio` if running directly from the source checkout. GitHub publishing uses the locally installed [GitHub CLI](https://cli.github.com/) and its authenticated user session; RecompStudio does not need a GitHub token saved in its own config.

## How project creation works

PSXRecomp and SNESRecomp have upstream game-project setup wizards. RecompStudio invokes those actual scripts rather than attempting to reimplement their complex templates.

Other frameworks receive a Git-ready workspace with:
- the framework checked out as a pinned Git submodule;
- `.recompstudio/project.json` with the framework ID, upstream URL and pinned revision;
- `.recompstudio/local.json` with machine-local ROM/BIOS paths (excluded from Git);
- a framework-specific README with the real upstream commands and known limitations;
- a `.gitignore` and a Windows/macOS/Linux GitHub Actions starter workflow.

The project adapters invoke the framework's current generation/build interfaces where those are sufficiently documented. Some families still need reverse-engineered function maps, title-specific TOML/configuration, generated-code analysis, and a game host. RecompStudio does not invent these missing pieces or claim a successful generator run is a playable port.

## Three-platform releases

The release workflow builds a platform-specific self-contained app bundle, framework snapshot, and compiler pack:
- Windows x64: GUI app directory plus CLI executable in a ZIP.
- macOS: DMGs containing a real `RecompStudio.app` bundle and CLI binary (Intel and Apple Silicon builds).
- Linux x86_64: AppImage containing the GUI, CLI, frameworks, and compiler archive. Run `RecompStudio.AppImage --cli --version` (or replace `--version` with a CLI command) to use the embedded CLI directly.

Push a `v*` tag to publish GitHub Release assets. `workflow_dispatch` also creates downloadable Actions artifacts for packaging verification. The Linux asset is substantially larger because the bundled Linux compiler/sysroot pack is roughly 833 MB compressed.

## Legal and source-image policy

RecompStudio does not distribute commercial ROMs, disc images, BIOS dumps, copyrighted assets, or game-derived generated code. Users provide their own lawfully obtained inputs. Absolute input paths are stored only in ignored local settings. Each upstream project retains its own license and redistribution rules; inspect its license and third-party notices before distributing framework code or a game build.

## Development and tests

```bash
python -m unittest discover -s tests -v
python -m recompstudio --version
python -m recompstudio frameworks list
python -m recompstudio doctor --json
```

The CI workflow runs the test suite and CLI smoke checks on Windows, macOS, and Linux.
