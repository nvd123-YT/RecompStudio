import json
import tempfile
import unittest
from pathlib import Path

from recompstudio.integrations import set_project_inputs


class ProjectSettingsTests(unittest.TestCase):
    def test_game_and_bios_paths_are_local_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "Sample"
            meta = root / ".recompstudio"
            meta.mkdir(parents=True)
            (meta / "project.json").write_text(json.dumps({
                "schema_version": 1,
                "framework": {"id": "nesrecomp", "submodule_path": "frameworks/nesrecomp"}
            }), encoding="utf-8")
            rom = Path(tmp) / "game.nes"
            bios = Path(tmp) / "system.rom"
            rom.write_bytes(b"rom")
            bios.write_bytes(b"bios")

            set_project_inputs(root, rom, bios)

            local = json.loads((meta / "local.json").read_text(encoding="utf-8"))
            manifest = json.loads((meta / "project.json").read_text(encoding="utf-8"))
            self.assertEqual(local["input_image"], str(rom.resolve()))
            self.assertEqual(local["bios_image"], str(bios.resolve()))
            self.assertNotIn(str(rom.resolve()), json.dumps(manifest))
            self.assertNotIn(str(bios.resolve()), json.dumps(manifest))


if __name__ == "__main__":
    unittest.main()
