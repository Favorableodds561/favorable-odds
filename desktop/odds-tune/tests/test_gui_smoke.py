"""GUI smoke tests. Skipped automatically where Tk or a display is not available (e.g. headless Linux CI)."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from helpers import core, make_old, write
from test_reports import make_snapshot

try:
    import tkinter
    from tkinter import BooleanVar, Tk
    import odds_tune as gui
    _root = Tk()
    _root.destroy()
    TK_OK = True
except Exception:  # no tkinter, or no display
    TK_OK = False


@unittest.skipUnless(TK_OK, "Tk or a display is not available")
class GuiFlow(unittest.TestCase):
    def setUp(self):
        self.root = Tk()
        self.root.withdraw()
        self.addCleanup(self.root.destroy)
        self.app = gui.OddTuneApp(self.root)

    def pump(self):
        self.root.update_idletasks()
        self.root.update()

    def test_initial_state_is_scan_first(self):
        self.assertEqual(self.app.scan_btn.cget("text"), "SCAN MY PC")
        self.assertEqual(str(self.app.clean_btn.cget("state")), "disabled")
        self.assertEqual(str(self.app.save_scan_btn.cget("state")), "disabled")
        self.assertIn("Scanning does not change anything", self.app.status_var.get())
        self.assertFalse(self.app.recycle_var.get(), "Recycle Bin must be opt-in")
        self.assertEqual(self.app.root.title(), f"Odd$ Tune v{core.APP_VERSION}")

    def test_cleanup_cannot_run_before_a_scan(self):
        with mock.patch.object(core, "clean_categories", side_effect=AssertionError("cleaned without a scan")), \
             mock.patch.object(gui.messagebox, "askyesno", return_value=True):
            self.app.confirm_clean()
            self.pump()

    def test_scan_result_unlocks_cleanup_and_shows_facts(self):
        snap = make_snapshot()
        self.app.events.put(("scan_done", snap))
        self.root.after(250, self.root.quit)
        self.root.mainloop()
        self.assertTrue(self.app.scan_complete)
        self.assertEqual(str(self.app.clean_btn.cget("state")), "normal")
        self.assertEqual(str(self.app.save_scan_btn.cget("state")), "normal")
        self.assertIn("Windows 11", self.app.metric_vars["windows"].get())
        self.assertIn("SSD", self.app.metric_vars["drive"].get())

    def test_declining_the_confirmation_deletes_nothing(self):
        with tempfile.TemporaryDirectory() as td:
            f = write(Path(td) / "old.tmp", age_hours=500)
            cat = core.CleanupCategory("user_temp", "User temp", "d", [Path(td)], 48)
            self.app.categories = [cat]
            self.app.category_vars = {"user_temp": BooleanVar(value=True)}
            self.app.snapshot, self.app.scan_complete = make_snapshot(), True
            with mock.patch.object(gui.messagebox, "askyesno", return_value=False):
                self.app.confirm_clean()
            self.pump()
            self.assertTrue(f.exists())

    def test_confirmed_cleanup_runs_selected_only_and_reports(self):
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as td2, tempfile.TemporaryDirectory() as reports:
            chosen = write(Path(td) / "old.tmp", b"1234", age_hours=500)
            fresh = write(Path(td) / "fresh.tmp")
            other = write(Path(td2) / "old.tmp", age_hours=500)
            a = core.CleanupCategory("a", "A", "d", [Path(td)], 48)
            b = core.CleanupCategory("b", "B", "d", [Path(td2)], 48)
            self.app.categories = [a, b]
            self.app.category_vars = {"a": BooleanVar(value=True), "b": BooleanVar(value=False)}
            self.app.snapshot, self.app.scan_complete = make_snapshot(), True
            seen = {}
            with mock.patch.object(gui.messagebox, "askyesno", return_value=True), \
                 mock.patch.object(gui.messagebox, "showinfo", side_effect=lambda t, m: seen.update(title=t, msg=m)), \
                 mock.patch.object(core, "save_report", side_effect=lambda r, d=None: (Path(reports) / "r.json", Path(reports) / "r.html")):
                self.app.confirm_clean()
                self.root.after(1500, self.root.quit)
                self.root.mainloop()
            self.assertFalse(chosen.exists())
            self.assertTrue(fresh.exists())
            self.assertTrue(other.exists(), "an unselected category was cleaned")
            self.assertEqual(seen.get("title"), "Cleanup Complete")
            self.assertIn("Removed", seen["msg"])


if __name__ == "__main__":
    unittest.main()
