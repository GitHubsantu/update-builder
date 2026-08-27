import hashlib
import json
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path

from app.git_manager import Change
from app.update_builder import BuildPlan, ClassifiedFile, build_update_zip


def _hash(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _classified(status: str, path: str, old_path: str | None = None) -> ClassifiedFile:
    return ClassifiedFile(change=Change(status=status, path=path, old_path=old_path), excluded=False)


class SfDeltaV1BuildTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        for name, contents in {
            "modified.txt": b"old modified\n",
            "deleted.txt": b"old deleted\n",
            "old-name.txt": b"old rename\n",
        }.items():
            (self.root / name).write_bytes(contents)
        self._git("init")
        self._git("add", ".")
        self._git("-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-m", "baseline")

        (self.root / "modified.txt").write_bytes(b"new modified\n")
        (self.root / "deleted.txt").unlink()
        (self.root / "old-name.txt").rename(self.root / "new-name.txt")
        (self.root / "added.txt").write_bytes(b"new file\n")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _git(self, *args: str) -> None:
        subprocess.run(["git", *args], cwd=self.root, check=True, capture_output=True)

    def test_package_contains_add_modify_delete_and_rename_as_delete_add(self) -> None:
        result = build_update_zip(
            self.root,
            BuildPlan(
                from_version="2.4.1",
                to_version="2.4.2",
                included=[
                    _classified("M", "modified.txt"),
                    _classified("A", "added.txt"),
                    _classified("R", "new-name.txt", "old-name.txt"),
                ],
                deleted=[_classified("D", "deleted.txt")],
                renamed=[_classified("R", "new-name.txt", "old-name.txt")],
                output_zip_path=self.root / "update.zip",
                baseline_ref="HEAD",
            ),
        )

        manifest = result.manifest
        self.assertEqual(set(manifest), {"format", "package_type", "from_version", "to_version", "generated_at", "entries"})
        self.assertEqual(manifest["format"], "sfdelta-v1")
        self.assertEqual(manifest["package_type"], "delta")
        self.assertEqual(
            manifest["entries"],
            {
                "modified.txt": {
                    "action": "modify",
                    "before_sha256": _hash(b"old modified\n"),
                    "after_sha256": _hash(b"new modified\n"),
                },
                "added.txt": {"action": "add", "after_sha256": _hash(b"new file\n")},
                "new-name.txt": {"action": "add", "after_sha256": _hash(b"old rename\n")},
                "deleted.txt": {"action": "delete", "before_sha256": _hash(b"old deleted\n")},
                "old-name.txt": {"action": "delete", "before_sha256": _hash(b"old rename\n")},
            },
        )

        with zipfile.ZipFile(result.zip_path) as package:
            self.assertEqual(
                set(package.namelist()),
                {"manifest.json", "files/modified.txt", "files/added.txt", "files/new-name.txt"},
            )
            self.assertEqual(json.loads(package.read("manifest.json")), manifest)
            self.assertEqual(package.read("files/modified.txt"), b"new modified\n")

    def test_full_release_is_self_describing_and_uses_files_prefix(self) -> None:
        (self.root / "app").mkdir()
        (self.root / "app" / "Example.php").write_text("<?php // release", encoding="utf-8")
        result = build_update_zip(
            self.root,
            BuildPlan(
                from_version=None, to_version="2.5.0", included=[], deleted=[], renamed=[],
                output_zip_path=self.root / "full.zip", package_type="full",
            ),
        )
        self.assertEqual(result.manifest["format"], "sfpackage-v1")
        self.assertEqual(result.manifest["package_type"], "full")
        self.assertIn("app/Example.php", result.manifest["entries"])
        with zipfile.ZipFile(result.zip_path) as package:
            self.assertIn("files/app/Example.php", package.namelist())


if __name__ == "__main__":
    unittest.main()
