"""Command-line interface for RecompStudio."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from .doctor import print_report
from .manager import FrameworkError, FrameworkManager
from .projects import (
    build_project, create_project, publish_project, push_project,
    recompile_project, set_project_inputs, update_project_framework,
)
from .registry import frameworks, refresh_catalog
from .toolchains import install_latest, status as toolchain_status
from .managed_tools import install_latest as install_managed_tool, status as managed_tool_status


def _print_frameworks() -> None:
    manager = FrameworkManager()
    print(f"{'ID':30} {'CATEGORY':18} {'STATUS':22} NAME")
    print("-" * 112)
    for item in frameworks():
        status = manager.status_one(str(item["id"]))
        print(f"{item['id']:30} {item.get('category', ''):18} {item.get('status', ''):22} {item['name']} — {status.summary}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="recompstudio",
        description="Manage static recompilation frameworks and native game projects."
    )
    parser.add_argument("--version", action="version", version=f"RecompStudio {__version__}")
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser("gui", help="Launch the RecompStudio desktop GUI")

    fw = commands.add_parser("frameworks", help="Manage independent upstream frameworks and shared components")
    fw_commands = fw.add_subparsers(dest="framework_command", required=True)
    fw_commands.add_parser("list", help="List the framework catalog and local install status")
    install = fw_commands.add_parser("install", help="Clone one framework and its recursive dependencies")
    install.add_argument("framework_id")
    update = fw_commands.add_parser("update", help="Fetch and fast-forward one framework")
    update.add_argument("framework_id")
    fw_commands.add_parser("update-all", help="Update every installed framework independently")
    status = fw_commands.add_parser("status", help="Show installed commits and pending updates")
    status.add_argument("--fetch", action="store_true", help="Fetch upstream before checking for updates")
    fw_commands.add_parser("refresh-catalog", help="Download the latest RecompStudio framework registry")

    tc = commands.add_parser("toolchains", help="Install and update the shared RetComM compiler toolchain")
    tc_commands = tc.add_subparsers(dest="toolchain_command", required=True)
    tc_commands.add_parser("status", help="Check the latest pack and local installation")
    tc_commands.add_parser("install", help="Download and install the latest host-compatible pack")
    tc_commands.add_parser("update", help="Update the shared pack while keeping older versions")

    tools = commands.add_parser("tools", help="Install optional GitHub and reverse-engineering tools")
    tools_commands = tools.add_subparsers(dest="tools_command", required=True)
    tools_commands.add_parser("status", help="Show managed-tool availability")
    tool_install = tools_commands.add_parser("install", help="Install or update a managed tool")
    tool_install.add_argument("tool", choices=("git", "github-cli", "java21", "ghidra", "reverse-engineering"))

    doctor = commands.add_parser("doctor", help="Detect the local build toolchain")
    doctor.add_argument("--json", action="store_true", help="Print machine-readable JSON")

    project = commands.add_parser("project", help="Create, recompile, build and publish game projects")
    project_commands = project.add_subparsers(dest="project_command", required=True)
    new = project_commands.add_parser("new", help="Create a framework-aware Git-ready game project")
    new.add_argument("--name", required=True)
    new.add_argument("--framework", required=True)
    new.add_argument("--workspace", type=Path, default=Path.home() / "RecompProjects")
    new.add_argument("--input", type=Path, help="Path to your ROM/disc image; it is never copied into the repository")
    new.add_argument("--bios", type=Path, help="Optional user-supplied BIOS/firmware path; never copied")
    new.add_argument("--players", type=int, default=1, choices=range(1, 9))

    for action, help_text in (
        ("recompile", "Run the selected framework's real code-generation pipeline"),
        ("build", "Build the generated project/host where an adapter is available"),
        ("update-framework", "Advance the project-pinned framework submodule"),
    ):
        sub = project_commands.add_parser(action, help=help_text)
        sub.add_argument("path", type=Path)
        if action == "recompile":
            sub.add_argument("--verbose", action="store_true", help="Show detailed generator output")

    inputs = project_commands.add_parser("set-input", help="Set local-only ROM and BIOS paths for an existing project")
    inputs.add_argument("path", type=Path)
    inputs.add_argument("--input", type=Path, help="ROM, cartridge, or disc image")
    inputs.add_argument("--bios", type=Path, help="BIOS or firmware image")

    push = project_commands.add_parser("push", help="Commit changes and push to the configured GitHub origin")
    push.add_argument("path", type=Path)
    push.add_argument("--message", required=True)

    publish = project_commands.add_parser("publish", help="Create a GitHub repository with gh and push it")
    publish.add_argument("path", type=Path)
    publish.add_argument("--repo", required=True, help="GitHub repository name, e.g. nvd123-YT/MyGame")
    publish.add_argument("--visibility", choices=("private", "public"), default="private")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "gui":
            from .gui import launch
            launch()
            return 0
        if args.command == "tools":
            if args.tools_command == "status":
                for tool_id, info in managed_tool_status().items():
                    state = "FOUND" if info.get("installed") else "MISSING"
                    origin = "managed" if info.get("managed") else "system"
                    print(f"[{state}] {tool_id}: {info.get('version') or info.get('path') or 'not installed'} ({origin})")
                return 0
            installed = install_managed_tool(
                args.tool,
                status=lambda message: print(message, flush=True),
                progress=lambda done, total: print(
                    f"Downloaded {done // (1024 * 1024)} / {total // (1024 * 1024)} MB",
                    flush=True,
                ) if total and done == total else None,
            )
            if isinstance(installed, dict):
                for tool_id, path in installed.items():
                    print(f"{tool_id}: {path}")
            else:
                print(f"{args.tool}: {installed}")
            return 0
        if args.command == "doctor":
            return print_report(args.json)
        if args.command == "toolchains":
            if args.toolchain_command == "status":
                info = toolchain_status()
                for key, value in info.items():
                    print(f"{key}: {value}")
                return 0 if info.get("installed") else 1
            installed = install_latest(status=lambda msg: print(msg, flush=True))
            print(f"Shared toolchain installed at {installed}")
            return 0
        if args.command == "frameworks":
            manager = FrameworkManager()
            if args.framework_command == "list":
                _print_frameworks()
            elif args.framework_command == "install":
                location = manager.install(args.framework_id)
                print(f"Installed {args.framework_id} at {location}")
            elif args.framework_command == "update":
                status = manager.update(args.framework_id)
                print(f"Updated {status.name}: {status.commit} ({status.branch})")
            elif args.framework_command == "update-all":
                updated, failures = manager.update_all()
                for item in updated:
                    print(f"UPDATED  {item.name} — {item.commit}")
                for framework_id, reason in failures:
                    print(f"SKIPPED  {framework_id} — {reason}")
                print(f"Finished: {len(updated)} updated, {len(failures)} skipped/failed.")
                return 1 if failures else 0
            elif args.framework_command == "status":
                for item in manager.statuses(fetch=args.fetch):
                    commit = f" ({item.commit})" if item.commit else ""
                    print(f"{item.framework_id:30} {item.summary}{commit}")
            elif args.framework_command == "refresh-catalog":
                catalog = refresh_catalog()
                print(f"Catalog refreshed: {len(catalog['frameworks'])} entries, version {catalog.get('catalog_version', 'unknown')}.")
            return 0

        if args.command == "project":
            if args.project_command == "new":
                path = create_project(
                    args.name, args.framework, args.workspace,
                    args.input, args.bios, args.players,
                )
                print(f"Created project: {path}")
                print("Project setup uses the selected framework's upstream wizard where one exists.")
                print("Use 'recompstudio project recompile' to run its native generation pipeline.")
            elif args.project_command == "recompile":
                output = recompile_project(args.path, args.verbose)
                print(output or "Recompilation completed.")
            elif args.project_command == "build":
                output = build_project(args.path)
                print(output or "Build completed.")
            elif args.project_command == "update-framework":
                commit = update_project_framework(args.path)
                print(f"Framework pin advanced to {commit}. Commit the updated submodule pointer to your game repository.")
            elif args.project_command == "set-input":
                set_project_inputs(args.path, args.input, args.bios)
                print("Local-only ROM/BIOS settings saved. These paths are excluded from Git.")
            elif args.project_command == "push":
                print(push_project(args.path, args.message))
            elif args.project_command == "publish":
                print(publish_project(args.path, args.repo, args.visibility))
            return 0
    except (FrameworkError, KeyError, ValueError, OSError) as exc:
        print(f"RecompStudio: {exc}", file=sys.stderr)
        return 1
    parser.error("Unknown command.")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
