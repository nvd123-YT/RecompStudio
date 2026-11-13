"""Cross-platform detection of development tools required by recomp frameworks."""
from __future__ import annotations

import json
import platform
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass


@dataclass
class ToolCheck:
    name: str
    found: bool
    path: str | None
    version: str = ""
    required_for: str = ""


TOOL_COMMANDS = {
    "git": ["git", "--version"],
    "python": [sys.executable, "--version"],
    "cmake": ["cmake", "--version"],
    "ninja": ["ninja", "--version"],
    "clang++": ["clang++", "--version"],
    "g++": ["g++", "--version"],
    "MSVC (cl)": ["cl"],
    "Java": ["java", "-version"],
    "GitHub CLI": ["gh", "--version"],
    "Ghidra headless": ["analyzeHeadless", "-help"],
}


def _version(command: list[str]) -> str:
    try:
        result = subprocess.run(
            command, capture_output=True, text=True, timeout=8,
            encoding="utf-8", errors="replace", check=False
        )
        lines = (result.stdout or result.stderr).strip().splitlines()
        return lines[0].strip()[:180] if lines else ""
    except (OSError, subprocess.TimeoutExpired):
        return ""


def check_tools() -> list[ToolCheck]:
    results: list[ToolCheck] = []
    for name, command in TOOL_COMMANDS.items():
        managed_env = toolchain_environment()
        path = shutil.which(command[0], path=managed_env.get("PATH"))
        results.append(ToolCheck(
            name=name,
            found=bool(path),
            path=path,
            version=_version(command) if path else "",
            required_for={
                "git": "Framework installation, submodules, and GitHub publishing",
                "python": "RecompStudio and many framework analyzers",
                "cmake": "Most native framework and game builds",
                "ninja": "Recommended generator for framework builds",
                "clang++": "macOS/Linux native C++ compiler",
                "g++": "Linux/MinGW native C++ compiler",
                "MSVC (cl)": "Windows native C++ compiler",
                "Java": "Ghidra-based reverse engineering workflows",
                "GitHub CLI": "Creating and pushing GitHub repositories from the CLI",
                "Ghidra headless": "Frameworks and game workflows that use Ghidra analysis",
            }.get(name, "")
        ))
    return results


def doctor_report() -> dict:
    results = check_tools()
    platform_name = platform.system()
    pack = active_pack()
    pack_manifest = None
    if pack and (pack / "retcomm-toolchain.json").is_file():
        try:
            pack_manifest = json.loads((pack / "retcomm-toolchain.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            pack_manifest = None
    return {
        "platform": platform_name,
        "python": sys.version.split()[0],
        "shared_toolchain": {
            "installed": pack is not None,
            "version": pack_manifest.get("version") if pack_manifest else None,
            "path": str(pack) if pack else None,
        },
        "checks": [asdict(item) for item in results],
        "missing": [item.name for item in results if not item.found],
        "guidance": {
            "Windows": "Install Git for Windows, Python 3, CMake, Ninja, and Visual Studio Build Tools (C++ workload). The optional RetComM toolchain bundle can provide a preconfigured compiler toolchain.",
            "Darwin": "Install the Xcode Command Line Tools for Apple Clang, plus Git, CMake, and Ninja. Check that your Python build includes Tkinter for the GUI.",
            "Linux": "Install Git, Python 3 with Tk support, CMake, Ninja, and your distribution's C/C++ compiler packages.",
        }.get(platform_name, "Install Git, Python 3, CMake, Ninja, and a C/C++ compiler."),
        "note": "Tool needs vary by framework. Missing optional tools do not prevent browsing or updating framework sources.",
    }


def print_report(as_json: bool = False) -> int:
    report = doctor_report()
    if as_json:
        print(json.dumps(report, indent=2))
        return 0
    print(f"RecompStudio environment check — {report['platform']} / Python {report['python']}")
    print()
    for item in report["checks"]:
        state = "FOUND" if item["found"] else "MISSING"
        version = f" — {item['version']}" if item["version"] else ""
        print(f"[{state:7}] {item['name']}{version}")
    print()
    print(report["guidance"])
    print(report["note"])
    return 0
