"""Report generation: valid JSON/HTML, required fields, privacy (no user/computer names), safe writing."""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from html.parser import HTMLParser
from pathlib import Path

from helpers import IS_WINDOWS, core


def make_snapshot() -> core.HealthSnapshot:
    return core.HealthSnapshot(
        timestamp="2026-10-01T12:00:00+00:00", app_version=core.APP_VERSION, windows="Windows 11", build="26100", architecture="x64",
        support_tier="primary", support_note="Windows 11 x64 is the primary target.", cpu="Test CPU", logical_cpus=8, admin=False,
        total_ram=16 * 1024 ** 3, system_drive="C:", disk_total=500 * 1024 ** 3, disk_used=300 * 1024 ** 3, disk_free=200 * 1024 ** 3,
        drive_model="Test SSD", drive_media="SSD", drive_bus="NVMe", pending_restart=False, startup_items=5,
        recycle_bin_bytes=1024, recycle_bin_items=2, cleanable_bytes=2048, cleanable_files=3, tools={"defrag": True, "dism": True, "sfc": True})


def make_categories() -> list[core.CleanupCategory]:
    c = core.CleanupCategory("user_temp", "User temporary files", "d", [Path("/x")], 48)
    c.estimate_bytes, c.estimate_files = 2048, 3
    c.stats.deleted_bytes, c.stats.deleted_files, c.stats.skipped_recent, c.stats.skipped_locked = 1024, 2, 5, 1
    c.stats.errors = [r"C:\Users\Alice\AppData\Local\Temp\a.tmp: PermissionError"]
    return [c]


class Tags(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tags, self.scripts = [], 0

    def handle_starttag(self, tag, attrs):
        self.tags.append(tag)
        self.scripts += tag == "script"


class ReportTests(unittest.TestCase):
    def test_json_has_required_fields_and_roundtrips(self):
        ops = [core.OperationRecord("DISM component-store repair", "t0", "t1", True, "Completed successfully.", 0)]
        report = core.build_report(make_snapshot(), make_categories(), "cleanup", ops, 100, 200, (True, "Recycle Bin emptied."))
        data = json.loads(json.dumps(report))
        self.assertEqual(data["product"], "Odd$ Tune")
        self.assertEqual(data["version"], core.APP_VERSION)
        self.assertEqual(data["schema_version"], 1)
        for key in ("generated", "system", "cleanup", "operations", "privacy", "disk_free_before", "disk_free_after", "recycle_bin"):
            self.assertIn(key, data)
        for key in ("windows", "build", "timestamp", "disk_total", "disk_free", "drive_media"):
            self.assertIn(key, data["system"])
        row = data["cleanup"][0]
        self.assertEqual((row["found_bytes"], row["found_files"], row["recovered_bytes"], row["removed_files"]), (2048, 3, 1024, 2))
        self.assertEqual(row["skipped_total"], 6)
        self.assertEqual(data["operations"][0]["exit_code"], 0)

    def test_no_user_or_computer_identifiers(self):
        env = {"USERPROFILE": r"C:\Users\Alice", "LOCALAPPDATA": r"C:\Users\Alice\AppData\Local", "COMPUTERNAME": "ALICE-PC"}
        old = {k: os.environ.get(k) for k in env}
        os.environ.update(env)
        self.addCleanup(lambda: [os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v) for k, v in old.items()])
        report = core.build_report(make_snapshot(), make_categories(), "scan")
        blob = json.dumps(report) + core.render_html(report)
        self.assertNotIn("Alice", blob)
        self.assertNotIn("ALICE-PC", blob)
        self.assertNotIn("hostname", blob.lower())

    def test_html_is_wellformed_escaped_and_has_no_scripts_or_remote_resources(self):
        cats = make_categories()
        cats[0].name = '<script>alert("x")</script> & "quotes"'
        report = core.build_report(make_snapshot(), cats, "cleanup")
        html_text = core.render_html(report)
        parser = Tags()
        parser.feed(html_text)
        self.assertEqual(parser.scripts, 0)
        self.assertNotIn("<script>", html_text)
        self.assertIn("&lt;script&gt;", html_text)
        self.assertNotIn("http://", html_text.replace("&middot;", ""))
        self.assertNotIn('src="', html_text)
        self.assertIn(core.APP_VERSION, html_text)
        for needed in ("Cleanup categories", "Eligible found", "Recovered", "Skipped"):
            self.assertIn(needed, html_text)
        self.assertTrue(parser.tags.count("table") >= 1)

    def test_save_report_writes_json_and_html_without_overwriting(self):
        with tempfile.TemporaryDirectory() as td:
            report = core.build_report(make_snapshot(), make_categories(), "scan")
            j1, h1 = core.save_report(report, Path(td))
            j2, h2 = core.save_report(report, Path(td))
            self.assertEqual(len({j1, h1, j2, h2}), 4, "a second report must not overwrite the first")
            self.assertEqual(json.loads(j1.read_text(encoding="utf-8"))["action"], "scan")
            self.assertTrue(h1.read_text(encoding="utf-8").startswith("<!doctype html>"))
            self.assertEqual(len(core.list_reports(Path(td))), 4)

    @unittest.skipUnless(hasattr(os, "symlink"), "symlinks unsupported")
    def test_report_writing_refuses_to_follow_a_planted_link(self):
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as out:
            link = Path(td) / "Reports"
            try:
                os.symlink(out, link, target_is_directory=True)
            except (OSError, NotImplementedError):
                self.skipTest("symlink creation unavailable")
            with self.assertRaises(OSError):
                core.save_report(core.build_report(make_snapshot(), make_categories(), "scan"), link)
            self.assertEqual(os.listdir(out), [])
            log = core.LogWriter(link / "x.txt")
            log.write("hello")
            log.close()
            self.assertEqual(os.listdir(out), [], "the maintenance log was written through a link")

    def test_log_writer_never_overwrites_an_existing_file(self):
        with tempfile.TemporaryDirectory() as td:
            existing = Path(td) / "log.txt"
            existing.write_text("precious")
            log = core.LogWriter(existing)
            log.write("overwrite attempt")
            log.close()
            self.assertEqual(existing.read_text(), "precious")

    def test_reports_folder_is_not_created_until_saving(self):
        self.assertFalse(str(core.report_dir()).endswith("\\\\"))
        with tempfile.TemporaryDirectory() as home:
            from unittest import mock
            with mock.patch.object(Path, "home", return_value=Path(home)):
                p = core.report_dir(create=False)
                self.assertFalse(p.exists())


if __name__ == "__main__":
    unittest.main()
