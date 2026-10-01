"""Static guarantees: no network or telemetry code, no registry writes, no aggressive tooling, consistent versions,
no secrets. These fail the build if someone later adds something that breaks Odd$ Tune's promises."""
from __future__ import annotations

import ast
import re
import unittest
from pathlib import Path

from helpers import core

APP_DIR = Path(__file__).resolve().parents[1]
REPO = APP_DIR.parents[1]
SOURCES = [APP_DIR / "odds_tune_core.py", APP_DIR / "odds_tune.py"]

FORBIDDEN_IMPORTS = {"socket", "ssl", "urllib", "urllib2", "urllib3", "http", "httplib", "requests", "ftplib", "smtplib", "telnetlib",
                     "xmlrpc", "asyncio", "aiohttp", "websocket", "websockets", "paramiko", "pickle", "marshal", "sentry_sdk",
                     "segment", "mixpanel", "posthog"}
ALLOWED_WEBBROWSER_FILES = {"odds_tune.py"}


def imports_of(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module.split(".")[0])
    return names


class NoNetworkNoTelemetry(unittest.TestCase):
    def test_no_network_or_telemetry_imports(self):
        for src in SOURCES:
            bad = imports_of(src) & FORBIDDEN_IMPORTS
            self.assertEqual(bad, set(), f"{src.name} imports network/telemetry/unsafe modules: {bad}")

    def test_webbrowser_is_limited_to_user_clicked_gui_buttons(self):
        for src in SOURCES:
            if "webbrowser" in imports_of(src):
                self.assertIn(src.name, ALLOWED_WEBBROWSER_FILES)
        gui = (APP_DIR / "odds_tune.py").read_text(encoding="utf-8")
        for line in gui.splitlines():
            if "webbrowser.open(" in line:
                self.assertRegex(line, r"WEBSITE|as_uri\(\)")

    def test_no_url_strings_other_than_the_product_page(self):
        for src in SOURCES:
            urls = set(re.findall(r"https?://[^\s\"'<>)]+", src.read_text(encoding="utf-8")))
            self.assertLessEqual(urls, {"https://favorableodds.io/tools/odds-tune/"}, f"{src.name}: {urls}")


class NoAggressiveOperations(unittest.TestCase):
    def test_no_registry_writes(self):
        for src in SOURCES:
            text = src.read_text(encoding="utf-8")
            for needle in ("SetValue", "SetValueEx", "CreateKey", "DeleteKey", "DeleteValue", "reg.exe", "reg add", "reg delete"):
                self.assertNotIn(needle, text, f"{src.name} touches the registry ({needle})")

    def test_no_forbidden_system_tools_or_dangerous_calls(self):
        forbidden = ("shell=True", "os.system(", "eval(", "exec(", "Stop-Service", "Set-Service", "sc.exe", "sc config", "netsh",
                     "schtasks", "taskkill", "Stop-Process", "Remove-Item", "rmtree", "Disable-", "Uninstall", "msiexec",
                     "wmic", "bcdedit", "powercfg", "vssadmin", "cleanmgr", "PendingFileRenameOperations\" ,",
                     "SetProcessWorkingSetSize", "EmptyWorkingSet", "pnputil", "winget")
        for src in SOURCES:
            text = src.read_text(encoding="utf-8")
            for needle in forbidden:
                self.assertNotIn(needle, text, f"{src.name} contains {needle!r}")

    def test_cleanup_targets_are_only_the_allowlist(self):
        text = (APP_DIR / "odds_tune_core.py").read_text(encoding="utf-8")
        for needle in ("Prefetch", "History", "Cookies", "Login Data", "SoftwareDistribution", "WinSxS", "Downloads", "Documents\"]"):
            # these words may appear in safety text, but never as a cleanup root passed to CleanupCategory
            for m in re.finditer(r"\[(?:local|windir|program_data)[^\]]*\]", text):
                self.assertNotIn(needle, m.group(0))

    def test_no_wildcard_extension_deletion(self):
        text = (APP_DIR / "odds_tune_core.py").read_text(encoding="utf-8")
        for needle in ('"*.tmp"', "'*.tmp'", '".log"', '".tmp"', '".temp"', "glob(", "rglob("):
            self.assertNotIn(needle, text, "broad extension/glob based deletion is not allowed")


class VersionAndHygiene(unittest.TestCase):
    def test_semver_and_version_resource_agree(self):
        self.assertRegex(core.APP_VERSION, r"^\d+\.\d+\.\d+$")
        info = (APP_DIR / "version_info.txt").read_text(encoding="utf-8")
        major, minor, patch = core.APP_VERSION.split(".")
        self.assertIn(f"filevers=({major}, {minor}, {patch}, 0)", info)
        self.assertIn(f"prodvers=({major}, {minor}, {patch}, 0)", info)
        self.assertIn(f"u'FileVersion', u'{core.APP_VERSION}'", info)
        self.assertIn(f"u'ProductVersion', u'{core.APP_VERSION}'", info)
        self.assertIn("u'ProductName', u'Odd$ Tune'", info)
        self.assertIn("u'OriginalFilename', u'OddsTune.exe'", info)

    def test_readme_and_site_state_the_same_version(self):
        readme = (APP_DIR / "README.md").read_text(encoding="utf-8")
        self.assertIn(f"v{core.APP_VERSION}", readme)
        page = REPO / "tools" / "odds-tune" / "index.html"
        if page.exists():
            self.assertIn(core.APP_VERSION, page.read_text(encoding="utf-8"))
        for stale in ("v1.0 ", "v1.0\n", "Odd$ Tune v1\n"):
            self.assertNotIn(stale, readme)

    def test_no_secrets_or_private_material_in_the_app_folder(self):
        pattern = re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----|ghp_[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}|xox[baprs]-[A-Za-z0-9-]{10,}")
        for p in APP_DIR.rglob("*"):
            if p.is_file() and p.suffix not in (".ico", ".pyc") and "__pycache__" not in p.parts:
                self.assertIsNone(pattern.search(p.read_text(encoding="utf-8", errors="ignore")), f"secret-like content in {p}")
        forbidden_files = [p for p in APP_DIR.rglob("*") if p.suffix.lower() in (".pfx", ".p12", ".pem", ".key", ".env", ".exe", ".pyc", ".spec")]
        self.assertEqual([p for p in forbidden_files if "__pycache__" not in p.parts], [])

    def test_no_hardcoded_developer_paths(self):
        for src in SOURCES:
            text = src.read_text(encoding="utf-8")
            self.assertNotRegex(text, r"[A-Za-z]:\\Users\\(?!Public)\w+", f"{src.name} hardcodes a user profile path")
            self.assertNotIn("/home/", text)


if __name__ == "__main__":
    unittest.main()
