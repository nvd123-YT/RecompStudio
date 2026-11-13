import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from recompstudio.integrations import update_project_framework


def git(cwd: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(cwd), *args],
        check=True, capture_output=True, text=True,
        encoding="utf-8", errors="replace",
    )
    return result.stdout.strip()


class ProjectFrameworkUpdateTests(unittest.TestCase):
    def test_detached_project_submodule_advances_on_upstream_default_branch(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            remote = base / "framework.git"
            seed = base / "seed"
            project = base / "game"
            submodule = project / "frameworks" / "sample"
            remote.parent.mkdir(parents=True, exist_ok=True)
            subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True)
            subprocess.run(["git", "init", "-b", "main", str(seed)], check=True, capture_output=True)
            git(seed, "config", "user.name", "RecompStudio Tests")
            git(seed, "config", "user.email", "tests@example.invalid")
            (seed / "README.md").write_text("framework revision one\n", encoding="utf-8")
            git(seed, "add", "README.md")
            git(seed, "commit", "-m", "first framework revision")
            git(seed, "remote", "add", "origin", str(remote))
            git(seed, "push", "-u", "origin", "main")
            subprocess.run(
                ["git", "--git-dir", str(remote), "symbolic-ref", "HEAD", "refs/heads/main"],
                check=True, capture_output=True,
            )
            first = git(seed, "rev-parse", "HEAD")

            project.mkdir()
            submodule.parent.mkdir(parents=True)
            subprocess.run(["git", "clone", str(remote), str(submodule)], check=True, capture_output=True)
            git(submodule, "checkout", "--detach", first)
            meta = project / ".recompstudio"
            meta.mkdir()
            (meta / "project.json").write_text(json.dumps({
                "schema_version": 1,
                "name": "Sample Game",
                "framework": {
                    "id": "sample",
                    "name": "Sample Framework",
                    "repository": str(remote),
                    "ref": None,
                    "pinned_commit": first,
                    "submodule_path": "frameworks/sample",
                },
            }), encoding="utf-8")

            (seed / "README.md").write_text("framework revision two\n", encoding="utf-8")
            git(seed, "add", "README.md")
            git(seed, "commit", "-m", "second framework revision")
            git(seed, "push", "origin", "main")
            second = git(seed, "rev-parse", "HEAD")

            updated = update_project_framework(project)

            self.assertEqual(updated, second)
            self.assertEqual(git(submodule, "branch", "--show-current"), "main")
            self.assertEqual(git(submodule, "rev-parse", "HEAD"), second)
            manifest = json.loads((meta / "project.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["framework"]["pinned_commit"], second)

    def test_dirty_submodule_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            remote = base / "framework.git"
            seed = base / "seed"
            project = base / "game"
            submodule = project / "frameworks" / "sample"
            subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True)
            subprocess.run(["git", "init", "-b", "main", str(seed)], check=True, capture_output=True)
            git(seed, "config", "user.name", "RecompStudio Tests")
            git(seed, "config", "user.email", "tests@example.invalid")
            (seed / "README.md").write_text("upstream\n", encoding="utf-8")
            git(seed, "add", "README.md")
            git(seed, "commit", "-m", "initial")
            git(seed, "remote", "add", "origin", str(remote))
            git(seed, "push", "-u", "origin", "main")
            subprocess.run(
                ["git", "--git-dir", str(remote), "symbolic-ref", "HEAD", "refs/heads/main"],
                check=True, capture_output=True,
            )
            project.mkdir()
            submodule.parent.mkdir(parents=True)
            subprocess.run(["git", "clone", str(remote), str(submodule)], check=True, capture_output=True)
            meta = project / ".recompstudio"
            meta.mkdir()
            (meta / "project.json").write_text(json.dumps({
                "schema_version": 1,
                "framework": {
                    "id": "sample", "submodule_path": "frameworks/sample",
                    "ref": None, "pinned_commit": git(submodule, "rev-parse", "HEAD"),
                },
            }), encoding="utf-8")
            (submodule / "local-change.txt").write_text("keep me\n", encoding="utf-8")

            with self.assertRaisesRegex(RuntimeError, "local changes"):
                update_project_framework(project)
            self.assertTrue((submodule / "local-change.txt").exists())


if __name__ == "__main__":
    unittest.main()
