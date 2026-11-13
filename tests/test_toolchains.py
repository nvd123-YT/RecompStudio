import tempfile
import unittest
import zipfile
from pathlib import Path

from recompstudio.toolchains import ToolchainError, _safe_extract


class ToolchainArchiveTests(unittest.TestCase):
    def test_safe_zip_extract(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive_path = Path(tmp) / "pack.zip"
            with zipfile.ZipFile(archive_path, "w") as archive:
                archive.writestr("bin/cmake", "test")
            target = Path(tmp) / "extract"
            target.mkdir()
            with zipfile.ZipFile(archive_path) as archive:
                _safe_extract(archive, target)
            self.assertEqual((target / "bin" / "cmake").read_text(), "test")

    def test_zip_path_traversal_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive_path = Path(tmp) / "bad.zip"
            with zipfile.ZipFile(archive_path, "w") as archive:
                archive.writestr("../outside.txt", "bad")
            target = Path(tmp) / "extract"
            target.mkdir()
            with zipfile.ZipFile(archive_path) as archive:
                with self.assertRaises(ToolchainError):
                    _safe_extract(archive, target)

    def test_install_bundled_pack_archive_offline(self):
        import json
        from unittest.mock import patch
        from recompstudio.toolchains import _install_archive

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            archive_path = root / "pack.zip"
            manifest = {
                "id": "cmake-clang-v1",
                "version": "1.0.14",
                "os": "linux-x64",
            }
            with zipfile.ZipFile(archive_path, "w") as archive:
                archive.writestr("retcomm-toolchain.json", json.dumps(manifest))
                archive.writestr("bin/cmake", "cmake stub")
            cache = root / "toolchains"
            with patch.dict("os.environ", {"RETCOMM_TOOLCHAIN_CACHE": str(cache)}):
                with patch("recompstudio.toolchains.expected_platform", return_value=("linux-x64", "linux-x64")):
                    installed = _install_archive(archive_path, "1.0.14")
            self.assertEqual(installed, cache / "1.0.14")
            self.assertTrue((installed / "bin" / "cmake").is_file())
            self.assertEqual((cache / "latest").read_text(encoding="utf-8"), "1.0.14")


if __name__ == "__main__":
    unittest.main()
