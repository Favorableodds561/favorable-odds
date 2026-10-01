"""Drive optimization and Windows repair: exact commands, ordering, output decoding, exit-code handling, elevation."""
from __future__ import annotations

import io
import sys
import unittest
from unittest import mock

from helpers import core


class FakeProc:
    def __init__(self, data: bytes, code: int):
        self.stdout = io.BytesIO(data)
        self._code = code

    def wait(self):
        return self._code


def popen_for(table):
    """table maps the executable's lower-case file name to (bytes, exit_code)."""
    calls = []

    def popen(argv, **kwargs):
        calls.append((argv, kwargs))
        name = argv[0].replace("\\", "/").rsplit("/", 1)[-1].lower()
        data, code = table[name]
        return FakeProc(data, code)

    popen.calls = calls
    return popen


class CommandConstruction(unittest.TestCase):
    ENV = {"SystemDrive": "D:", "SystemRoot": "D:\\Windows"}

    def test_drive_optimization_uses_media_aware_defrag_on_the_detected_system_drive(self):
        (spec,) = core.maintenance_commands("optimize", self.ENV)
        self.assertEqual(spec.argv[1:], ["D:", "/O", "/U", "/V"])
        self.assertTrue(spec.argv[0].lower().endswith("system32\\defrag.exe") or spec.argv[0].lower().endswith("system32/defrag.exe"))
        self.assertNotIn("/D", spec.argv)          # never a blind traditional defrag switch set
        self.assertNotIn("/X", spec.argv)

    def test_repair_runs_dism_then_sfc_with_the_documented_arguments(self):
        dism, sfc = core.maintenance_commands("repair", self.ENV)
        self.assertEqual(dism.argv[1:], ["/Online", "/Cleanup-Image", "/RestoreHealth"])
        self.assertEqual(sfc.argv[1:], ["/scannow"])
        self.assertIn("dism.exe", dism.argv[0].lower())
        self.assertIn("sfc.exe", sfc.argv[0].lower())

    def test_unknown_task_is_rejected(self):
        with self.assertRaises(ValueError):
            core.maintenance_commands("format-c")

    def test_cleanup_never_runs_repair_or_optimization(self):
        with mock.patch.object(core.subprocess, "Popen", side_effect=AssertionError("cleanup must not launch processes")), \
             mock.patch.object(core.subprocess, "run", side_effect=AssertionError("cleanup must not launch processes")):
            import tempfile
            from pathlib import Path
            with tempfile.TemporaryDirectory() as td:
                core.clean_root(Path(td), 48)
                cat = core.CleanupCategory("k", "n", "d", [Path(td)], 48)
                core.scan_categories([cat])
                core.clean_categories([cat], {"k"})


class OutputAndExitCodes(unittest.TestCase):
    def run_task(self, task, table):
        lines = []
        popen = popen_for(table)
        records = core.run_maintenance_task(task, lambda text, prog: lines.append((text, prog)), None, popen)
        return records, lines, popen

    def test_both_repair_steps_run_in_order_and_results_are_captured(self):
        dism_out = b"Deployment Image Servicing and Management tool\r\n[==========================100.0%==========================]\r\nThe restore operation completed successfully.\r\n"
        sfc_out = ("Beginning system scan.  This process will take some time.\r\nVerification 100% complete.\r\n"
                   "Windows Resource Protection did not find any integrity violations.\r\n").encode("utf-16-le")
        records, lines, popen = self.run_task("repair", {"dism.exe": (dism_out, 0), "sfc.exe": (sfc_out, 0)})
        self.assertEqual([r.name for r in records], ["DISM component-store repair", "System File Checker"])
        self.assertEqual([c[0][0].replace("\\", "/").rsplit("/", 1)[-1].lower() for c in popen.calls], ["dism.exe", "sfc.exe"])
        self.assertTrue(all(r.ok for r in records))
        self.assertEqual([r.exit_code for r in records], [0, 0])
        self.assertIn("No integrity violations", records[1].detail)
        texts = [t for t, _ in lines]
        self.assertIn("Windows Resource Protection did not find any integrity violations.", texts)   # UTF-16 decoded, no NULs
        self.assertFalse(any("\x00" in t for t in texts))
        self.assertTrue(any(p for _, p in lines), "progress lines should be flagged so the UI can show them as status")

    def test_sfc_still_runs_when_dism_fails(self):
        records, _lines, popen = self.run_task("repair", {"dism.exe": (b"Error: 0x800f0950\r\n", 87),
                                                           "sfc.exe": (b"Verification 100% complete.\r\n", 0)})
        self.assertEqual(len(popen.calls), 2)
        self.assertFalse(records[0].ok)
        self.assertEqual(records[0].exit_code, 87)
        self.assertIn("87", records[0].detail)

    def test_dism_restart_required_is_success(self):
        records, *_ = self.run_task("repair", {"dism.exe": (b"done\r\n", 3010), "sfc.exe": (b"x\r\n", 0)})
        self.assertTrue(records[0].ok)
        self.assertIn("Restart", records[0].detail)

    def test_sfc_unrepairable_is_reported_as_a_problem(self):
        out = b"Windows Resource Protection found corrupt files but was unable to fix some of them.\r\n"
        records, *_ = self.run_task("repair", {"dism.exe": (b"ok\r\n", 0), "sfc.exe": (out, 1)})
        self.assertFalse(records[1].ok)
        self.assertIn("could not be repaired", records[1].detail)

    def test_optimize_result(self):
        records, _l, popen = self.run_task("optimize", {"defrag.exe": (b"Pre-Optimization... 50% complete\r\nThe operation completed successfully.\r\n", 0)})
        self.assertEqual(len(records), 1)
        self.assertTrue(records[0].ok)
        kwargs = popen.calls[0][1]
        self.assertFalse(kwargs.get("shell", False))

    def test_unlaunchable_tool_is_reported_not_raised(self):
        def popen(*a, **k):
            raise FileNotFoundError("defrag.exe")
        records = core.run_maintenance_task("optimize", lambda *_: None, None, popen)
        self.assertFalse(records[0].ok)
        self.assertIsNone(records[0].exit_code)

    def test_commands_never_use_a_shell(self):
        _r, _l, popen = self.run_task("repair", {"dism.exe": (b"", 0), "sfc.exe": (b"", 0)})
        for argv, kwargs in popen.calls:
            self.assertIsInstance(argv, list)
            self.assertFalse(kwargs.get("shell", False))


class Elevation(unittest.TestCase):
    def test_only_fixed_task_names_cross_the_uac_boundary(self):
        with mock.patch.object(core, "_shell_execute_runas", return_value="started") as run:
            for bad in ("x", "repair; calc", "", "../repair", "--task"):
                self.assertEqual(core.launch_elevated_task(bad), "failed")
            run.assert_not_called()
            with mock.patch.object(sys, "frozen", True, create=True), mock.patch.object(sys, "executable", r"C:\Apps\OddsTune.exe"):
                self.assertEqual(core.launch_elevated_task("repair"), "started")
            run.assert_called_once_with(r"C:\Apps\OddsTune.exe", "--task repair")

    def test_no_script_file_or_encoded_command_is_used_for_elevation(self):
        text = open(core.__file__, encoding="utf-8").read()
        for needle in (".ps1", "EncodedCommand", "-enc ", "ExecutionPolicy", "Set-Content", "Out-File"):
            self.assertNotIn(needle, text, f"{needle!r} would reintroduce an elevated-script risk")

    def test_denied_uac_is_reported_cleanly(self):
        with mock.patch.object(core, "is_windows", return_value=True), mock.patch.object(core.ctypes, "windll", create=True) as w:
            w.shell32.ShellExecuteW.return_value = 5       # SE_ERR_ACCESSDENIED: the user pressed No
            self.assertEqual(core._shell_execute_runas("x.exe", ""), "denied")
            w.shell32.ShellExecuteW.return_value = 42
            self.assertEqual(core._shell_execute_runas("x.exe", ""), "started")
            w.shell32.ShellExecuteW.return_value = 2
            self.assertEqual(core._shell_execute_runas("x.exe", ""), "failed")


class WindowsApiShapes(unittest.TestCase):
    def test_recycle_bin_struct_matches_the_windows_header(self):
        """SHQUERYRBINFO is packed to 20 bytes. The un-packed 24-byte layout makes the API call fail silently."""
        import ctypes
        self.assertEqual(ctypes.sizeof(core._SHQUERYRBINFO), 20)

    @unittest.skipUnless(core.is_windows(), "Windows only")
    def test_real_windows_facts(self):
        import re
        snap = core.collect_snapshot([])
        self.assertTrue(snap.windows.startswith("Windows"))
        self.assertGreater(snap.disk_total, 0)
        self.assertTrue(re.fullmatch(r"[A-Z]:", snap.system_drive))
        self.assertTrue(snap.tools["defrag"] and snap.tools["dism"] and snap.tools["sfc"])
        self.assertGreater(snap.total_ram, 0)
        self.assertTrue(snap.cpu)
        self.assertIsInstance(core.recycle_bin_info(), tuple)


if __name__ == "__main__":
    unittest.main()
