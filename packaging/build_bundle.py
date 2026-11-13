"""Assemble redistributable upstream checkouts and the host toolchain for releases."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "recompstudio" / "data" / "frameworks.json"
BUNDLE = ROOT / "recompstudio" / "bundled"
TOOLCHAIN_API = "https://api.github.com/repos/RetroPortingToolKit/RetroPorting-Toolchains/releases/latest"


def run(command: list[str], cwd: Path | None = None, timeout: int = 1800) -> str:
    try:
        result = subprocess.run(command, cwd=cwd, capture_output=True, text=True,
                                encoding="utf-8", errors="replace", check=False,
                                timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(f"Could not run {' '.join(command)}: {exc}") from exc
    if result.returncode:
        raise RuntimeError(f"Command failed: {' '.join(command)}\n"
                           + (result.stderr or result.stdout)[-12000:])
    return result.stdout.strip()


def request(url: str, accept: str = "application/vnd.github+json"):
    headers = {
        "User-Agent": "RecompStudio-BundleBuilder/0.1",
        "Accept": accept,
        "X-GitHub-Api-Version": "2022-11-28",
    }
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=headers)
    return urllib.request.urlopen(req, timeout=60)


def download(url: str, dest: Path) -> str:
    dest.parent.mkdir(parents=True, exist_ok=True)
    sha, total = hashlib.sha256(), 0
    with request(url, "application/octet-stream") as response, dest.open("wb") as output:
        while True:
            block = response.read(1024 * 1024)
            if not block:
                break
            output.write(block)
            sha.update(block)
            total += len(block)
            print(f"Downloaded {dest.name}: {total // (1024 * 1024)} MiB", end="\r", flush=True)
    print()
    return sha.hexdigest()


def clone_frameworks() -> list[dict]:
    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    framework_root = BUNDLE / "frameworks"
    framework_root.mkdir(parents=True, exist_ok=True)
    eligible = [
        item for item in catalog["frameworks"]
        if item.get("redistributable")
        and item.get("bundle", True)
        and item.get("category") in {"framework", "integration-fork", "shared-component"}
    ]
    output = []
    for index, item in enumerate(eligible, 1):
        framework_id = str(item["id"])
        destination = framework_root / framework_id
        if destination.exists():
            shutil.rmtree(destination)
        command = ["git", "clone", "--recurse-submodules", "--jobs", "8"]
        if item.get("ref"):
            command.extend(["--branch", str(item["ref"])])
        command.extend([str(item["repository"]), str(destination)])
        print(f"[{index}/{len(eligible)}] Cloning {framework_id} ({item.get('redistribution_license')})")
        run(command, timeout=3600)
        run(["git", "-C", str(destination), "submodule", "update", "--init",
             "--recursive", "--jobs", "8"], timeout=3600)
        commit = run(["git", "-C", str(destination), "rev-parse", "HEAD"])
        branch = run(["git", "-C", str(destination), "branch", "--show-current"])
        marker = destination / ".git"
        if not (marker.exists() or marker.is_file()):
            raise RuntimeError(f"{framework_id} clone is missing Git metadata; cannot support updates.")
        output.append({
            "id": framework_id,
            "name": item["name"],
            "repository": item["repository"],
            "ref": item.get("ref"),
            "branch": branch,
            "commit": commit,
            "license": item.get("redistribution_license", "see upstream"),
            "license_path": "LICENSE plus any upstream THIRD_PARTY_ATTRIBUTION or NOTICE files",
        })
    return output


def bundle_toolchain(platform_id: str) -> dict:
    with request(TOOLCHAIN_API) as response:
        release = json.loads(response.read().decode("utf-8"))
    tag = str(release.get("tag_name", ""))
    version = tag.lstrip("vV")
    suffix = {
        "windows-x64": "windows-x64",
        "macos-universal": "macos-universal",
        "linux-x64": "linux-x64",
    }.get(platform_id)
    if not suffix:
        raise RuntimeError(f"Unsupported toolchain target: {platform_id}")
    assets = [item for item in release.get("assets", [])
              if item.get("name") == f"cmake-clang-v1-{suffix}.zip"]
    if not assets:
        raise RuntimeError(f"RetComM {tag} has no {suffix} pack.")
    asset = assets[0]
    asset_name = str(asset["name"])
    dest = BUNDLE / "toolchains" / asset_name
    digest = download(str(asset["browser_download_url"]), dest)
    expected = str(asset.get("digest", ""))
    if expected.startswith("sha256:") and digest.lower() != expected.split(":", 1)[1].lower():
        raise RuntimeError(f"Toolchain SHA-256 mismatch for {asset_name}.")
    for filename in ("LICENSE", "NOTICE"):
        raw_url = ("https://raw.githubusercontent.com/RetroPortingToolKit/"
                   f"RetroPorting-Toolchains/main/{filename}")
        with request(raw_url, "text/plain") as response:
            (BUNDLE / "toolchains" / filename).write_bytes(response.read())
    return {
        "id": "cmake-clang-v1", "version": version, "tag": tag,
        "asset": asset_name, "sha256": digest,
        "size": int(asset.get("size") or 0),
        "upstream": "https://github.com/RetroPortingToolKit/RetroPorting-Toolchains",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--platform", required=True,
                        choices=["windows-x64", "macos-universal", "linux-x64"])
    args = parser.parse_args()
    if BUNDLE.exists():
        shutil.rmtree(BUNDLE)
    BUNDLE.mkdir(parents=True)
    framework_entries = clone_frameworks()
    toolchain = bundle_toolchain(args.platform)
    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    included = {item["id"] for item in framework_entries}
    excluded = [{
        "id": item["id"], "name": item["name"],
        "reason": item.get("bundle_exclusion_reason") or item.get("redistribution_license", "No upstream licence reviewed"),
        "repository": item["repository"],
    } for item in catalog["frameworks"]
      if item.get("category") in {"framework", "integration-fork", "shared-component"}
      and item["id"] not in included]
    manifest = {
        "format_version": 1,
        "built_for": args.platform,
        "catalog_version": catalog.get("catalog_version"),
        "frameworks": framework_entries,
        "excluded_from_embedded_copy": excluded,
        "toolchain": toolchain,
        "source_policy": (
            "Embedded source checkouts retain upstream Git history, recursive submodules, "
            "licences and notices. Frameworks without clear redistribution permission are "
            "not embedded; users may explicitly clone them from upstream."
        ),
    }
    (BUNDLE / "bundle.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    license_lines = [
        "# Embedded upstream components and licences", "",
        "RecompStudio preserves each upstream repository's own licence and notices in its checkout.",
        "", "| Component | Upstream | Licence | Pinned commit |",
        "|---|---|---|---|",
    ]
    for item in framework_entries:
        license_lines.append(
            f"| {item['name']} | {item['repository']} | {item['license']} | {item['commit'][:12]} |"
        )
    license_lines += [
        "",
        "The following catalog entries are not embedded because they do not currently expose a clear top-level redistribution licence:",
        "",
    ]
    for item in excluded:
        license_lines.append(f"- {item['name']}: {item['reason']} ({item['repository']})")
    license_lines += [
        "",
        "RetComM compiler toolchain licence and third-party notices are in toolchains/LICENSE and toolchains/NOTICE.",
        "ROMs, disc images, BIOS dumps, firmware and copyrighted game data are never included.",
        "",
    ]
    (BUNDLE / "UPSTREAM_LICENSES.md").write_text("\n".join(license_lines), encoding="utf-8")
    print(f"Bundle ready: {len(framework_entries)} checkouts, {len(excluded)} not embedded, "
          f"RetComM {toolchain['version']} ({args.platform}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
