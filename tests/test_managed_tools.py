import os
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from recompstudio.managed_tools import ManagedToolError, _safe_extract, _select_asset, environment


class ManagedToolTests(unittest.TestCase):
    def test_selects_correct_github_cli_asset_for_apple_silicon(self):
        assets = [
            {"name": "gh_2.0_linux_amd64.tar.gz"},
            {"name": "gh_2.0_macOS_arm64.zip"},
            {"name": "gh_2.0_windows_amd64.zip"},
        ]
        selected = _select_asset("github-cli", assets, os_name="darwin", machine="arm64")
        self.assertEqual(selected["name"], "gh_2.0_macOS_arm64.zip")

    def test_selects_java_21_for_intel_macos(self):
        assets = [
            {"name": "OpenJDK21U-jdk_aarch64_mac_hotspot_21.0.1.tar.gz"},
            {"name": "OpenJDK21U-jdk_x64_mac_hotspot_21.0.1.tar.gz"},
        ]
        selected = _select_asset("java21", assets, os_name="darwin", machine="x86_64")
        self.assertIn("x64_mac", selected["name"])

    def test_rejects_zip_path_traversal(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            archive_path = root / "unsafe.zip"
            with zipfile.ZipFile(archive_path, "w") as archive:
                archive.writestr("../escape.txt", "bad")
            destination = root / "extract"
            destination.mkdir()
            with self.assertRaises(ManagedToolError):
                _safe_extract(archive_path, destination)

    def test_managed_java_and_ghidra_paths_enter_child_environment(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            java_home = root / "java21" / "21" / "jdk"
            java_bin = java_home / "bin"
            ghidra_home = root / "ghidra" / "12" / "ghidra"
            support = ghidra_home / "support"
            java_bin.mkdir(parents=True)
            support.mkdir(parents=True)
            (java_bin / "java").write_text("stub", encoding="utf-8")
            (support / "analyzeHeadless").write_text("stub", encoding="utf-8")
            for tool_id, version, executable, path, home in (
                ("java21", "21", "jdk/bin/java", "jdk/bin", "jdk"),
                ("ghidra", "12", "ghidra/support/analyzeHeadless", "ghidra/support", "ghidra"),
            ):
                install = root / tool_id / version
                install.mkdir(parents=True)
                import json
                (install / "managed-tool.json").write_text(
                    json.dumps({
                        "id": tool_id, "version": version,
                        "executable": executable, "path": path, "home": home,
                    }), encoding="utf-8",
                )
                (root / tool_id / "latest").write_text(version, encoding="utf-8")
            with patch.dict(os.environ, {"RECOMPSTUDIO_TOOLS_HOME": str(root)}):
                env = environment({"PATH": ""})
            self.assertEqual(env["JAVA_HOME"], str(java_home))
            self.assertEqual(env["GHIDRA_HOME"], str(ghidra_home))
            self.assertIn(str(java_bin), env["PATH"])
            self.assertIn(str(support), env["PATH"])


if __name__ == "__main__":
    unittest.main()
