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


if __name__ == "__main__":
    unittest.main()
