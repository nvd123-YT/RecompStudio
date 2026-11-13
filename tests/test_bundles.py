import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from recompstudio.bundles import bundle_manifest, bundle_root, bundled_framework_path, bundled_toolchain


class BundledResourceTests(unittest.TestCase):
    def test_environment_override_finds_frameworks_and_toolchain(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            framework = root / "frameworks" / "nesrecomp"
            framework.mkdir(parents=True)
            (framework / ".git").mkdir()
            toolchains = root / "toolchains"
            toolchains.mkdir()
            archive = toolchains / "cmake-clang-v1-linux-x64.zip"
            archive.write_bytes(b"zip placeholder")
            (root / "bundle.json").write_text(json.dumps({
                "toolchain": {
                    "asset": archive.name,
                    "version": "1.0.14",
                    "sha256": "abc",
                },
                "frameworks": [{"id": "nesrecomp"}],
            }), encoding="utf-8")
            with patch.dict(os.environ, {"RECOMPSTUDIO_BUNDLED_ROOT": str(root)}):
                self.assertEqual(bundle_root(), root)
                self.assertEqual(bundle_manifest()["frameworks"][0]["id"], "nesrecomp")
                self.assertEqual(bundled_framework_path("nesrecomp"), framework)
                self.assertEqual(bundled_toolchain()[0], archive)
                self.assertIsNone(bundled_framework_path("psxrecomp"))

    def test_missing_bundle_is_supported_for_source_development(self):
        with patch.dict(os.environ, {"RECOMPSTUDIO_BUNDLED_ROOT": "/path/that/does/not/exist"}):
            self.assertIsNone(bundle_root())
            self.assertEqual(bundle_manifest(), {})
            self.assertIsNone(bundled_toolchain())


if __name__ == "__main__":
    unittest.main()
