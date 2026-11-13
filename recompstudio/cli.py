"""Command-line interface for RecompStudio."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .doctor import print_report
from .manager import FrameworkError, FrameworkManager
from .projects import (
    build_project, create_project, publish_project, push_project,
    update_project_framework,
)
from .registry import frameworks, refresh_catalog


def _print_frameworks() -> None:
    manager = FrameworkManager()
    print(f"{'ID':30} {'CATEGORY':18} {'STATUS':14} NAME")
    print("-" * 100)
    for item in frameworks():
        state = manager.status_one(str(item["id"]))
        print(f"{item['id']:30} {item.get('category', ''):18} {item.get('status', ''):14} {item['name']} — {state.summary}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="recompstudio",
        description="Manage static recompilation frameworks and game projects."
    )
    parser.add_argument("--version", action="version", version=f"RecompStudio {__version__}")
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser("gui", help="Launch the RecompStudio desktop GUI")

    fw = commands.add_parser("frameworks", help="Manage upstream frameworks and shared components")
    fw_commands = fw.add_subparsers(dest="framework_command", required=True)
    fw_commands.add_parser("list", help="List all frameworks and components")
    install = fw_commands.add_parser("install", help="Clone one framework")
    install.add_argument("framework_id")
    update = fw_commands.add_parser("update", help="Fast-forward one framework")
    update.add_argument("framework_id")
    fw_commands.add_parser("update-all", help="Update every installed framework")
    status = fw_commands.add_parser("status", help="Show local versions and pending updates")
    status.add_argument("--fetch", action="store_true", help="Fetch upstream to check for new commits")
    fw_commands.add_parser("refresh-catalog", help="Download the latest framework registry")

    doctor = commands.add_parser("doctor", help="Detect the local build toolchain")
    doctor.add_argument("--json", action="store_true", help="Print machine-readable JSON")

    project = commands.add_parser("project", help="Create, build, and publish game projects")
    project_commands = project.add_subparsers(dest="project_command", required=True)
    new = project_commands.add_parser("new", help="Create a Git-ready project with a pinned framework")
    new.add_argument("--name", required=True)
    new.add_argument("--framework", required=True)
    new.add_argument("--workspace", type=Path, default=Path.home() / "RecompProjects")
    new.add_argument("--input", type=Path, help="Path to a user-supplied ROM/disc image; not copied into the project")
    new.add_argument("--bios", type=Path, help="Path to a user-supplied BIOS image; not copied into the project")
    for action, help_text in (
        ("build", "Run the project's build script or CMake build"),
        ("update-framework", "Advance the project's pinned framework submodule"),
    ):
        sub = project_commands.add_parser(action, help=help_text)
        sub.add_argument("path", type=Path)
    push = project_commands.add_parser("push", help="Commit local changes and push to origin")
    push.add_argument("path", type=Path)
    push.add_argument("--message", required=True)
    publish = project_commands.add_parser("publish", help="Create a GitHub repository with gh and push it")
    publish.add_argument("path", type=Path)
    publish.add_argument("--repo", required=True, help="GitHub repository name, such as nvd123-YT/MyGame")
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
        if args.command == "doctor":
            return print_report(args.json)
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
                for status in updated:
                    print(f"UPDATED  {status.name} — {status.commit}")
                for framework_id, reason in failures:
                    print(f"SKIPPED  {framework_id} — {reason}")
                print(f"Finished: {len(updated)} updated, {len(failures)} skipped/failed.")
                return 1 if failures else 0
            elif args.framework_command == "status":
                statuses = manager.statuses(fetch=args.fetch)
                for item in statuses:
                    detail = f" ({item.commit})" if item.commit else ""
                    print(f"{item.framework_id:30} {item.summary}{detail}")
            elif args.framework_command == "refresh-catalog":
                catalog = refresh_catalog()
                print(f"Catalog refreshed: {len(catalog['frameworks'])} entries, version {catalog.get('catalog_version', 'unknown')}.")
            return 0
        if args.command == "project":
            if args.project_command == "new":
                path = create_project(args.name, args.framework, args.workspace, args.input, args.bios)
                print(f"Created project: {path}")
                print("Next: follow the upstream game-project guide, then add build.sh, build.ps1, or CMakeLists.txt.")
            elif args.project_command == "build":
                output = build_project(args.path)
                print(output or "Build completed.")
            elif args.project_command == "update-framework":
                commit = update_project_framework(args.path)
                print(f"Framework pin advanced to {commit}. Commit the updated submodule pointer to your game repository.")
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
