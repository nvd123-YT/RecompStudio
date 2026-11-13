import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from recompstudio.manager import FrameworkManager


class FrameworkBundleManagerTests(unittest.TestCase):
    def test_bundle_is_visible_as_installed_and_is_copied_before_update(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            user_root = base / "user-frameworks"
            bundled = base / "resources" / "frameworks" / "nesrecomp"
            bundled.mkdir(parents=True)
            (bundled / ".git").mkdir()
            (bundled / "README.md").write_text("bundled upstream", encoding="utf-8")
            manager = FrameworkManager(user_root)

            with patch("recompstudio.manager.bundled_framework_path", return_value=bundled):
                self.assertEqual(manager.path_for("nesrecomp"), bundled)
                self.assertTrue(manager.status_one("nesrecomp").installed)
                writable = manager._ensure_writable_checkout("nesrecomp")

            self.assertEqual(writable, user_root / "nesrecomp")
            self.assertTrue((writable / ".git").is_dir())
            self.assertEqual((writable / "README.md").read_text(encoding="utf-8"), "bundled upstream")
            self.assertEqual(manager.path_for("nesrecomp"), writable)

    def test_install_returns_packaged_checkout_without_cloning(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            bundled = base / "bundle" / "frameworks" / "nesrecomp"
            bundled.mkdir(parents=True)
            (bundled / ".git").mkdir()
            manager = FrameworkManager(base / "user-frameworks")
            with patch("recompstudio.manager.bundled_framework_path", return_value=bundled):
                self.assertEqual(manager.install("nesrecomp"), bundled)


if __name__ == "__main__":
    unittest.main()
