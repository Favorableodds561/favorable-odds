"""Scan-only mode must perform no deletions and no system modifications of any kind."""
from __future__ import annotations

import builtins
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from helpers import core, tree_fingerprint, write


def _forbidden(name):
    def boom(*a, **k):
        raise AssertionError(f"scan attempted a modifying call: {name}{a[:1]}")
    return boom


class ScanIsReadOnly(unittest.TestCase):
    def build_tree(self, root: Path) -> None:
        for i in range(4):
            write(root / f"d{i}" / "old.tmp", b"o" * (i + 5), age_hours=300)
            write(root / f"d{i}" / "new.tmp", b"n" * 7)
        (root / "emptydir").mkdir()

    def test_scan_changes_nothing_and_calls_no_modifying_api(self):
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as home:
            root = Path(td) / "AppData" / "Local" / "Temp"
            self.build_tree(root)
            env = {"LOCALAPPDATA": str(Path(td) / "AppData" / "Local"), "WINDIR": str(Path(td) / "Windows"),
                   "PROGRAMDATA": str(Path(td) / "ProgramData")}
            cats = core.build_categories(env, Path(td), str(root))
            before = tree_fingerprint(Path(td))
            real_open = builtins.open

            def guarded_open(file, mode="r", *a, **k):
                if any(c in str(mode) for c in "wax+"):
                    raise AssertionError(f"scan opened a file for writing: {file}")
                return real_open(file, mode, *a, **k)

            patches = [mock.patch.object(os, n, side_effect=_forbidden(n)) for n in
                       ("unlink", "remove", "rmdir", "rename", "replace", "chmod", "mkdir", "makedirs", "utime", "symlink", "link")]
            patches += [mock.patch.object(shutil, "rmtree", side_effect=_forbidden("rmtree")),
                        mock.patch.object(shutil, "move", side_effect=_forbidden("move")),
                        mock.patch.object(builtins, "open", guarded_open)]
            for p in patches:
                p.start()
                self.addCleanup(p.stop)
            snapshot = core.collect_snapshot(cats)
            for p in patches:
                p.stop()
            self.assertEqual(tree_fingerprint(Path(td)), before, "scan altered the file system")
            user = next(c for c in cats if c.key == "user_temp")
            self.assertEqual(user.estimate_files, 4)
            self.assertEqual(snapshot.cleanable_files, 4)
            self.assertEqual(snapshot.cleanable_bytes, sum(range(5, 9)))

    def test_scan_does_not_create_the_reports_folder(self):
        with tempfile.TemporaryDirectory() as home:
            with mock.patch.dict(os.environ, {"HOME": home, "USERPROFILE": home}), mock.patch.object(Path, "home", return_value=Path(home)):
                core.collect_snapshot(core.build_categories({}, Path(home), str(Path(home) / "Temp")))
                self.assertEqual(os.listdir(home), [], "scan created files or folders in the user's profile")

    def test_scan_preview_equals_what_cleanup_removes(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "Temp"
            self.build_tree(root)
            cat = core.CleanupCategory("user_temp", "t", "d", [root], 48)
            core.scan_categories([cat])
            estimate = (cat.estimate_bytes, cat.estimate_files)
            core.clean_categories([cat], {"user_temp"})
            self.assertEqual((cat.stats.deleted_bytes, cat.stats.deleted_files), estimate)
            self.assertEqual((cat.estimate_bytes, cat.estimate_files), estimate, "the scan estimate must survive cleaning for before/after reports")

    def test_unselected_and_unavailable_categories_are_never_cleaned(self):
        with tempfile.TemporaryDirectory() as td:
            a, b = Path(td) / "A", Path(td) / "B"
            fa, fb = write(a / "x.tmp", age_hours=300), write(b / "y.tmp", age_hours=300)
            ca = core.CleanupCategory("a", "A", "d", [a], 48)
            cb = core.CleanupCategory("b", "B", "d", [b], 48)
            cu = core.CleanupCategory("u", "U", "d", [], 48, unavailable_reason="nope")
            core.clean_categories([ca, cb, cu], {"a", "u"})
            self.assertFalse(fa.exists())
            self.assertTrue(fb.exists())


if __name__ == "__main__":
    unittest.main()
