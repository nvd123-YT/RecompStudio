import json
import tempfile
import unittest
from pathlib import Path

from recompstudio.integrations import _sanitize_psx_project_paths


class PsxPathSanitizationTests(unittest.TestCase):
    def test_disc_path_is_removed_but_other_game_and_runtime_fields_remain(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            game = root / "game.toml"
            game.write_text(
                '[game]\nname = "Example"\ndisc = "/Users/alice/ROMs/Game.cue"\n'
                'players = 1\n\n[runtime]\ndisc = "runtime-relative.cue"\n',
                encoding="utf-8",
            )
            _sanitize_psx_project_paths(root)
            text = game.read_text(encoding="utf-8")
            self.assertNotIn("/Users/alice/ROMs/Game.cue", text)
            self.assertNotIn('disc = "/Users/alice/ROMs/Game.cue"', text)
            self.assertIn('name = "Example"', text)
            self.assertIn('disc = "runtime-relative.cue"', text)

    def test_probe_json_keeps_identity_but_reduces_cue_path_to_filename(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            probe = root / "disc_probe.json"
            probe.write_text(json.dumps({
                "cue_path": "/Users/alice/ROMs/Game (USA).cue",
                "serial": "SLUS-12345",
                "data_track_sha1": "a" * 40,
            }), encoding="utf-8")
            _sanitize_psx_project_paths(root)
            data = json.loads(probe.read_text(encoding="utf-8"))
            self.assertEqual(data["cue_path"], "Game (USA).cue")
            self.assertEqual(data["serial"], "SLUS-12345")
            self.assertEqual(data["data_track_sha1"], "a" * 40)


if __name__ == "__main__":
    unittest.main()
