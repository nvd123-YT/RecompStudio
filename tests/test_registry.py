import json
import unittest
from pathlib import Path

from recompstudio.registry import bundled_catalog_path, frameworks, validate_catalog


class RegistryTests(unittest.TestCase):
    def test_bundled_catalog_is_valid_json(self):
        data = json.loads(bundled_catalog_path().read_text(encoding="utf-8"))
        self.assertEqual(data["schema_version"], 1)
        self.assertGreaterEqual(len(data["frameworks"]), 15)

    def test_framework_ids_are_unique_and_repositories_are_https(self):
        self.assertEqual(validate_catalog(), [])
        ids = [item["id"] for item in frameworks()]
        self.assertEqual(len(ids), len(set(ids)))

    def test_categories_cover_engine_and_shared_component(self):
        categories = {item["category"] for item in frameworks()}
        self.assertIn("framework", categories)
        self.assertIn("shared-component", categories)


if __name__ == "__main__":
    unittest.main()
