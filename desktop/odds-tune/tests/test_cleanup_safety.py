"""Cleanup safety: age protection, links and junctions, missing/empty folders, locked files, permission failures,
root validation and path safety. Every test works inside a TemporaryDirectory."""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from helpers import HOUR, IS_WINDOWS, core, make_old, write

ROOT = Path("C:\\") if IS_WINDOWS else Path("/")          # a valid absolute anchor on this OS (fake paths, never touched)


def P(*parts: str) -> str:
    return str(ROOT.joinpath(*parts))


class AgeProtection(unittest.TestCase):
    def test_old_deleted_recent_preserved(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            old = write(root / "old.tmp", b"a" * 100, age_hours=72)
            recent = write(root / "recent.tmp", b"b" * 200)
            sub_old = write(root / "sub" / "deep" / "old2.tmp", b"c" * 50, age_hours=100)
            sub_recent = write(root / "sub" / "recent2.tmp", b"d" * 10)
            preview = core.scan_root(root, 48)
            self.assertEqual((preview.found_bytes, preview.found_files), (150, 2))
            result = core.clean_root(root, 48)
            self.assertEqual((result.deleted_bytes, result.deleted_files), (150, 2))
            self.assertFalse(old.exists() or sub_old.exists())
            self.assertTrue(recent.exists() and sub_recent.exists())
            self.assertEqual(result.skipped_recent, 2)
            self.assertEqual(result.errors, [])

    def test_threshold_boundaries(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            just_under = write(root / "47h.tmp", age_hours=47)
            just_over = write(root / "49h.tmp", age_hours=49)
            core.clean_root(root, 48)
            self.assertTrue(just_under.exists())
            self.assertFalse(just_over.exists())

    def test_every_category_uses_its_documented_age(self):
        env = {"LOCALAPPDATA": P("u", "AppData", "Local"), "WINDIR": P("c", "Windows"), "PROGRAMDATA": P("c", "ProgramData")}
        cats = {c.key: c for c in core.build_categories(env, Path(P("u")), P("u", "AppData", "Local", "Temp"))}
        self.assertEqual({k: c.min_age_hours for k, c in cats.items()},
                         {"user_temp": 48, "crash_dumps": 168, "shader_cache": 168, "windows_temp": 72, "error_reports": 168})
        self.assertEqual({k: c.requires_admin for k, c in cats.items()},
                         {"user_temp": False, "crash_dumps": False, "shader_cache": False, "windows_temp": True, "error_reports": True})

    def test_old_modified_time_but_new_creation_time_is_kept(self):
        """Installers extract files that keep an old modified time but get a brand-new creation time."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            f = write(root / "installer-payload.dat")
            t = f.stat().st_mtime - 100 * HOUR
            os.utime(f, (t, t))                          # old mtime, fresh ctime/creation
            with mock.patch.object(core, "is_windows", return_value=True):   # age rule = max(mtime, creation)
                result = core.clean_root(root, 48)
            self.assertTrue(f.exists())
            self.assertEqual(result.deleted_files, 0)
            self.assertEqual(result.skipped_recent, 1)

    @unittest.skipUnless(IS_WINDOWS, "needs real Windows creation times")
    def test_windows_real_creation_time_rules(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            old_both = write(root / "old_both.tmp", age_hours=100)
            old_mtime_new_created = write(root / "new_created.tmp")
            t = old_mtime_new_created.stat().st_mtime - 100 * HOUR
            os.utime(old_mtime_new_created, (t, t))
            core.clean_root(root, 48)
            self.assertFalse(old_both.exists())
            self.assertTrue(old_mtime_new_created.exists())


class LinkProtection(unittest.TestCase):
    def _outside(self, td_out: str) -> Path:
        return write(Path(td_out) / "important.txt", b"keep me", age_hours=500)

    @unittest.skipUnless(hasattr(os, "symlink"), "symlinks unsupported")
    def test_directory_symlink_is_not_followed(self):
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as out:
            root, target = Path(td), self._outside(out)
            try:
                os.symlink(out, root / "redirect", target_is_directory=True)
            except (OSError, NotImplementedError):
                self.skipTest("symlink creation unavailable")
            write(root / "old.tmp", age_hours=100)
            result = core.clean_root(root, 48)
            self.assertTrue(target.exists())
            self.assertGreaterEqual(result.skipped_links, 1)
            self.assertFalse((root / "old.tmp").exists())          # the legitimate old file still goes

    @unittest.skipUnless(hasattr(os, "symlink"), "symlinks unsupported")
    def test_file_symlink_is_removed_not_followed(self):
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as out:
            root, target = Path(td), self._outside(out)
            try:
                os.symlink(target, root / "link.tmp")
            except (OSError, NotImplementedError):
                self.skipTest("symlink creation unavailable")
            core.clean_root(root, 48)
            self.assertTrue(target.exists())

    @unittest.skipUnless(hasattr(os, "symlink"), "symlinks unsupported")
    def test_root_that_is_a_link_is_skipped_entirely(self):
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as out:
            target = self._outside(out)
            link = Path(td) / "Temp"
            try:
                os.symlink(out, link, target_is_directory=True)
            except (OSError, NotImplementedError):
                self.skipTest("symlink creation unavailable")
            for fn in (core.scan_root, core.clean_root):
                result = fn(link, 48)
                self.assertEqual((result.found_files, result.deleted_files), (0, 0))
                self.assertEqual(result.skipped_links, 1)
            self.assertTrue(target.exists())

    @unittest.skipUnless(IS_WINDOWS, "NTFS junctions are Windows only")
    def test_junction_is_not_followed(self):
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as out:
            root, target = Path(td), self._outside(out)
            junction = root / "junction"
            subprocess.run(["cmd", "/c", "mklink", "/J", str(junction), out], check=True, capture_output=True)
            self.assertTrue(core.path_is_link_like(junction))
            result = core.clean_root(root, 48)
            self.assertTrue(target.exists(), "a file outside the cleanup root was deleted through a junction")
            self.assertGreaterEqual(result.skipped_links, 1)

    @unittest.skipUnless(IS_WINDOWS, "NTFS junctions are Windows only")
    def test_root_that_is_a_junction_is_skipped(self):
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as out:
            target = self._outside(out)
            junction = Path(td) / "Temp"
            subprocess.run(["cmd", "/c", "mklink", "/J", str(junction), out], check=True, capture_output=True)
            result = core.clean_root(junction, 48)
            self.assertTrue(target.exists())
            self.assertEqual(result.skipped_links, 1)

    def test_any_reparse_point_is_skipped(self):
        """Simulates a junction/placeholder on any OS: the entry carries the reparse attribute but is a plain dir."""
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as out:
            root, target = Path(td), self._outside(out)
            fake = root / "fakejunction"
            fake.mkdir()
            write(fake / "victim.tmp", age_hours=500)
            fake_ino = os.lstat(fake).st_ino
            real = core.stat_is_link_like
            with mock.patch.object(core, "stat_is_link_like", side_effect=lambda st: st.st_ino == fake_ino or real(st)):
                result = core.clean_root(root, 48)
            self.assertTrue((fake / "victim.tmp").exists())
            self.assertGreaterEqual(result.skipped_links, 1)
            self.assertTrue(target.exists())

    def test_directory_redirected_outside_root_is_not_entered(self):
        """Containment guard: if a directory resolves outside the root (race or redirect), it is skipped."""
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as out:
            root, target = Path(td), self._outside(out)
            sub = root / "looks_normal"
            write(sub / "victim.tmp", age_hours=500)
            real_realpath = os.path.realpath
            with mock.patch.object(core.os.path, "realpath",
                                   side_effect=lambda p, *a, **k: out if os.path.basename(str(p)) == "looks_normal" else real_realpath(p, *a, **k)):
                result = core.clean_root(root, 48)
            self.assertTrue((sub / "victim.tmp").exists())
            self.assertGreaterEqual(result.skipped_links, 1)
            self.assertTrue(target.exists())

    def test_own_pyinstaller_extraction_folder_is_protected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            mei = root / "_MEI12345"
            keep = write(mei / "tcl" / "init.tcl", age_hours=500)
            gone = write(root / "other.tmp", age_hours=500)
            with mock.patch.object(sys, "_MEIPASS", str(mei), create=True):
                core.clean_root(root, 48)
            self.assertTrue(keep.exists())
            self.assertFalse(gone.exists())


class MissingEmptyAndFailures(unittest.TestCase):
    def test_missing_folder_does_not_crash(self):
        with tempfile.TemporaryDirectory() as td:
            missing = Path(td) / "does" / "not" / "exist"
            for fn in (core.scan_root, core.clean_root):
                result = fn(missing, 48)
                self.assertEqual((result.found_files, result.deleted_files, result.skipped_total), (0, 0, 0))
                self.assertEqual(result.errors, [])

    def test_root_that_is_a_file_is_ignored(self):
        with tempfile.TemporaryDirectory() as td:
            f = write(Path(td) / "iamafile", age_hours=500)
            self.assertEqual(core.clean_root(f, 48).deleted_files, 0)
            self.assertTrue(f.exists())

    def test_empty_root_and_empty_folders(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self.assertEqual(core.clean_root(root, 48).deleted_files, 0)          # empty root is fine
            old_empty = root / "old_empty"
            old_empty.mkdir()
            make_old(old_empty, 100)
            recent_empty = root / "recent_empty"
            recent_empty.mkdir()
            old_but_has_recent_file = root / "busy"
            write(old_but_has_recent_file / "fresh.tmp")
            make_old(old_but_has_recent_file, 100)
            emptied = root / "emptied"
            write(emptied / "old.tmp", age_hours=100)
            make_old(emptied, 100)
            result = core.clean_root(root, 48)
            self.assertTrue(root.exists(), "the allowlisted root itself must never be removed")
            self.assertFalse(old_empty.exists())
            self.assertFalse(emptied.exists())                                    # old dir emptied by this run
            self.assertTrue(recent_empty.exists())                                # recent dir: an app may be about to use it
            self.assertTrue((old_but_has_recent_file / "fresh.tmp").exists())
            self.assertGreaterEqual(result.removed_empty_dirs, 2)

    def test_root_is_never_removed_even_if_old_and_empty(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "Temp"
            root.mkdir()
            make_old(root, 1000)
            core.clean_root(root, 48)
            self.assertTrue(root.exists())

    def test_locked_file_is_skipped_safely(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            locked = write(root / "locked.tmp", b"L" * 10, age_hours=100)
            free = write(root / "free.tmp", b"F" * 20, age_hours=100)
            if IS_WINDOWS:
                handle = open(locked, "rb")          # Python opens without FILE_SHARE_DELETE, so Windows refuses deletion
                self.addCleanup(handle.close)
                result = core.clean_root(root, 48)
            else:
                real_unlink = os.unlink

                def fake(path, *a, **k):
                    if os.path.basename(str(path)) == "locked.tmp":
                        raise PermissionError(13, "in use")
                    return real_unlink(path, *a, **k)

                with mock.patch.object(core.os, "unlink", side_effect=fake):
                    result = core.clean_root(root, 48)
            self.assertTrue(locked.exists())
            self.assertFalse(free.exists())
            self.assertEqual(result.skipped_locked, 1)
            self.assertEqual(result.deleted_files, 1)

    def test_file_vanishing_mid_clean_is_not_an_error(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            write(root / "a.tmp", age_hours=100)
            with mock.patch.object(core.os, "unlink", side_effect=FileNotFoundError):
                result = core.clean_root(root, 48)
            self.assertEqual((result.deleted_files, result.errors), (0, []))

    def test_unreadable_folder_does_not_stop_the_rest(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            blocked = root / "blocked"
            write(blocked / "x.tmp", age_hours=100)
            ok = write(root / "ok.tmp", age_hours=100)
            real_scandir = os.scandir

            def fake_scandir(path):
                if os.path.basename(str(path)) == "blocked":
                    raise PermissionError(13, "denied")
                return real_scandir(path)

            with mock.patch.object(core.os, "scandir", side_effect=fake_scandir):
                result = core.clean_root(root, 48)
            self.assertFalse(ok.exists())
            self.assertTrue((blocked / "x.tmp").exists())
            self.assertEqual(result.skipped_locked, 1)
            self.assertEqual(len(result.errors), 1)

    def test_error_list_is_capped_and_redacted(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            for i in range(40):
                write(root / f"f{i}.tmp", age_hours=100)
            with mock.patch.object(core.os, "unlink", side_effect=PermissionError(13, "denied")):
                result = core.clean_root(root, 48)
            self.assertEqual(result.skipped_locked, 40)
            self.assertEqual(len(result.errors), core.MAX_ERRORS_PER_CATEGORY)

    @unittest.skipUnless(IS_WINDOWS, "read-only deletion semantics are Windows specific")
    def test_old_read_only_file_is_removed(self):
        with tempfile.TemporaryDirectory() as td:
            f = write(Path(td) / "ro.tmp", age_hours=100)
            os.chmod(f, 0o444)
            core.clean_root(Path(td), 48)
            self.assertFalse(f.exists())

    def test_scan_matches_clean(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            for i in range(5):
                write(root / f"d{i}" / "old.tmp", b"z" * (i + 1), age_hours=100)
                write(root / f"d{i}" / "new.tmp")
            preview = core.scan_root(root, 48)
            actual = core.clean_root(root, 48)
            self.assertEqual((preview.found_bytes, preview.found_files), (actual.deleted_bytes, actual.deleted_files))


class PathSafety(unittest.TestCase):
    def test_is_within(self):
        w = core._is_within
        self.assertTrue(w("/a/b/c", "/a/b"))
        self.assertTrue(w("/a/b", "/a/b"))
        self.assertFalse(w("/a/bc", "/a/b"))               # prefix trick
        self.assertFalse(w("/a/b/../x", "/a/b"))           # traversal
        self.assertFalse(w("/a", "/a/b"))

    def test_cleanup_never_leaves_root(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            root = base / "Temp"
            neighbour = write(base / "Temp2" / "keep.tmp", age_hours=500)       # shares a name prefix with the root
            parent_file = write(base / "parent.tmp", age_hours=500)
            write(root / "old.tmp", age_hours=500)
            core.clean_root(root, 48)
            self.assertTrue(neighbour.exists() and parent_file.exists())

    def test_unique_roots_dedupes_equivalent_paths(self):
        with tempfile.TemporaryDirectory() as td:
            a = Path(td) / "Temp"
            a.mkdir()
            cat = core.CleanupCategory("k", "n", "d", [a, Path(str(a) + os.sep), a / "." / ""], 48)
            self.assertEqual(len(core.unique_roots(cat)), 1)


class RootValidation(unittest.TestCase):
    HOME = Path(P("home", "u"))
    ENV = {"LOCALAPPDATA": P("home", "u", "AppData", "Local"), "WINDIR": P("c", "Windows"), "PROGRAMDATA": P("c", "ProgramData"),
           "PROGRAMFILES": P("c", "Program Files"), "ONEDRIVE": P("home", "u", "OneDrive")}
    DEFAULT_TEMP = P("home", "u", "AppData", "Local", "Temp")

    def cats(self, temp, env=None):
        return {c.key: c for c in core.build_categories(env or self.ENV, self.HOME, temp)}

    def test_allowlist_is_exactly_the_documented_set(self):
        cats = self.cats(self.DEFAULT_TEMP)
        roots = {k: [str(r) for r in c.roots] for k, c in cats.items()}
        pd = ["c", "ProgramData", "Microsoft", "Windows", "WER"]
        self.assertEqual(roots, {
            "user_temp": [self.DEFAULT_TEMP],
            "crash_dumps": [P("home", "u", "AppData", "Local", "CrashDumps")],
            "shader_cache": [P("home", "u", "AppData", "Local", "D3DSCache")],
            "windows_temp": [P("c", "Windows", "Temp")],
            "error_reports": [P(*pd, "ReportQueue"), P(*pd, "ReportArchive")]})

    def test_hostile_temp_values_are_refused(self):
        hostile = [str(ROOT), P("home", "u"), P("home", "u", "Documents"), P("home", "u", "Documents", "Temp"),
                   P("home", "u", "Desktop", "Temp"), P("home", "u", "OneDrive", "Temp"), P("c", "Program Files", "Temp"),
                   P("c", "Windows", "Temp"), P("c", "Windows"), P("home", "u", "Stuff"), "relative/Temp", "", P("home")]
        for temp in hostile:
            user = self.cats(temp)["user_temp"]
            self.assertEqual([str(r) for r in user.roots], [self.DEFAULT_TEMP], temp)
            self.assertTrue(user.notes, f"no explanation for ignored TEMP {temp!r}")

    def test_sane_custom_temp_is_accepted(self):
        custom = P("data", "Temp")
        user = self.cats(custom)["user_temp"]
        self.assertEqual([str(r) for r in user.roots], [self.DEFAULT_TEMP, custom])

    def test_untrusted_bases_make_categories_unavailable_instead_of_guessing(self):
        env = {"LOCALAPPDATA": P("home", "u", "Documents"), "WINDIR": str(ROOT), "PROGRAMDATA": P("home", "u", "Documents")}
        cats = {c.key: c for c in core.build_categories(env, Path(P("nonexistent-home")), P("nonexistent-home", "x", "Temp"))}
        for key in ("windows_temp", "error_reports"):
            self.assertFalse(cats[key].available, key)
            self.assertTrue(cats[key].unavailable_reason)
            self.assertEqual(cats[key].roots, [])

    def test_no_root_is_ever_a_drive_root_or_inside_personal_folders(self):
        envs = [self.ENV, {"LOCALAPPDATA": str(ROOT), "WINDIR": str(ROOT), "PROGRAMDATA": str(ROOT)}, {},
                {"LOCALAPPDATA": P("home", "u", "Documents", "AppData", "Local"), "WINDIR": P("c", "Windows"), "PROGRAMDATA": P("c", "ProgramData")}]
        personal = [self.HOME / n for n in core.USER_FOLDERS]
        for env in envs:
            for temp in (str(ROOT), P("home", "u"), P("home", "u", "Documents"), P("tmp"), self.DEFAULT_TEMP):
                for c in core.build_categories(env, self.HOME, temp):
                    for r in c.roots:
                        # a custom TEMP such as D:\Temp (two components) is a legitimate setup; a bare drive root never is
                        self.assertGreater(len(r.parts), 1, f"{r} is a drive root ({env}, {temp})")
                        for p in personal:
                            self.assertFalse(core._is_within(r, p), f"{r} is inside {p}")

    def test_system_drive_comes_from_the_os_and_is_validated(self):
        self.assertEqual(core.system_drive({"SystemDrive": "D:"}), "D:")
        self.assertEqual(core.system_drive({"SystemRoot": "e:\\Windows"}), "E:")
        self.assertEqual(core.system_drive({"SystemDrive": "C:; calc"}), "C:")
        self.assertEqual(core.system_drive({}), "C:")


class Redaction(unittest.TestCase):
    def test_user_names_and_profile_paths_are_removed(self):
        env = {"LOCALAPPDATA": r"C:\Users\Alice Smith\AppData\Local", "USERPROFILE": r"C:\Users\Alice Smith"}
        out = core.redact(r"C:\Users\Alice Smith\AppData\Local\Temp\x.tmp: PermissionError", env, Path(r"C:\Users\Alice Smith"))
        self.assertNotIn("Alice", out)
        self.assertIn("%LOCALAPPDATA%", out)
        self.assertNotIn("Bob", core.redact(r"D:\Users\Bob\file.txt", {}, Path("/nowhere")))


if __name__ == "__main__":
    unittest.main()
