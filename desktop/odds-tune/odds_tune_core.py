"""Odd$ Tune core: read-only scanning, allowlisted cleanup, maintenance tasks and local reports.

This module has no GUI and no network code. Everything that can change the computer lives here so it can be
unit-tested; the GUI (odds_tune.py) only calls into it.

Design rules (see docs/SECURITY_AND_SCOPE.md):
  * Cleanup is allowlist-based. Each root is built from a trusted base, validated, and re-checked while walking.
  * One traversal (``_walk``) is shared by scan and clean, so a scan always previews exactly what a clean would touch.
  * Links, junctions and every other reparse point are never followed, and a file is only deleted if it is old
    by *both* its modified time and (on Windows) its creation time.
  * When unsure whether something is safe to delete, it is skipped.
"""
from __future__ import annotations

import codecs
import ctypes
import datetime as dt
import html
import json
import os
import platform
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable, Iterator, Mapping, Optional

APP_NAME = "Odd$ Tune"
APP_VERSION = "1.0.0"
PUBLISHER = "Favorable Odds LLC"
WEBSITE = "https://favorableodds.io/tools/odds-tune/"
REPORT_SCHEMA_VERSION = 1

FILE_ATTRIBUTE_READONLY = 0x1
FILE_ATTRIBUTE_REPARSE_POINT = 0x400
CREATE_NO_WINDOW = 0x08000000
MAX_ERRORS_PER_CATEGORY = 15


def is_windows() -> bool:
    return os.name == "nt"


# ---------------------------------------------------------------------------------------------------------------------
# Link / reparse-point and age helpers
# ---------------------------------------------------------------------------------------------------------------------

def _reparse_flag(st: os.stat_result) -> bool:
    """True when Windows marks the entry as a reparse point (symlink, junction, mount point, cloud placeholder...)."""
    return bool(getattr(st, "st_file_attributes", 0) & FILE_ATTRIBUTE_REPARSE_POINT)


def stat_is_link_like(st: os.stat_result) -> bool:
    return stat.S_ISLNK(st.st_mode) or _reparse_flag(st)


def path_is_link_like(path: os.PathLike | str) -> bool:
    """Fail safe: if we cannot tell, treat the path as a link."""
    try:
        return stat_is_link_like(os.lstat(path))
    except OSError:
        return True


def reference_time(st: os.stat_result) -> float:
    """The moment an item was last 'touched' for age purposes.

    On Windows this is the later of modified and creation time. Installers often extract files that keep an old
    modified time but a brand-new creation time; those must count as recent. Elsewhere (tests) only mtime exists.
    """
    t = float(st.st_mtime)
    if is_windows():
        created = getattr(st, "st_birthtime", None)
        if created is None:
            created = st.st_ctime
        t = max(t, float(created))
    return t


def _is_within(child: os.PathLike | str, parent: os.PathLike | str) -> bool:
    c = os.path.normcase(os.path.abspath(child))
    p = os.path.normcase(os.path.abspath(parent))
    try:
        return os.path.commonpath([c, p]) == p
    except ValueError:  # different drives
        return False


def _is_drive_root(path: Path) -> bool:
    return len(path.parts) <= 1


def _tail(path: Path, n: int) -> tuple[str, ...]:
    return tuple(p.casefold() for p in path.parts[-n:])


# ---------------------------------------------------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------------------------------------------------

@dataclass
class WalkStats:
    found_bytes: int = 0
    found_files: int = 0
    deleted_bytes: int = 0
    deleted_files: int = 0
    removed_empty_dirs: int = 0
    skipped_recent: int = 0
    skipped_links: int = 0
    skipped_locked: int = 0   # in use, read-only we could not clear, or access denied
    skipped_other: int = 0
    errors: list[str] = field(default_factory=list)

    def note(self, message: str) -> None:
        if len(self.errors) < MAX_ERRORS_PER_CATEGORY:
            self.errors.append(redact(message))

    @property
    def skipped_total(self) -> int:
        return self.skipped_recent + self.skipped_links + self.skipped_locked + self.skipped_other

    def merge(self, other: "WalkStats") -> None:
        for name in ("found_bytes", "found_files", "deleted_bytes", "deleted_files", "removed_empty_dirs",
                     "skipped_recent", "skipped_links", "skipped_locked", "skipped_other"):
            setattr(self, name, getattr(self, name) + getattr(other, name))
        for e in other.errors:
            if len(self.errors) < MAX_ERRORS_PER_CATEGORY:
                self.errors.append(e)


@dataclass
class CleanupCategory:
    key: str
    name: str
    description: str
    roots: list[Path]
    min_age_hours: int
    requires_admin: bool = False
    default_selected: bool = True
    unavailable_reason: str = ""
    notes: list[str] = field(default_factory=list)
    stats: WalkStats = field(default_factory=WalkStats)
    estimate_bytes: int = 0     # set by the read-only scan; kept while cleaning so before/after can be compared
    estimate_files: int = 0

    @property
    def available(self) -> bool:
        return not self.unavailable_reason and bool(self.roots)

    def reset(self) -> None:
        self.stats = WalkStats()

    def reset_estimate(self) -> None:
        self.estimate_bytes = 0
        self.estimate_files = 0


@dataclass
class HealthSnapshot:
    timestamp: str
    app_version: str
    windows: str
    build: str
    architecture: str
    support_tier: str          # "primary" | "best-effort" | "unsupported"
    support_note: str
    cpu: str
    logical_cpus: int
    admin: bool
    total_ram: int
    system_drive: str
    disk_total: int
    disk_used: int
    disk_free: int
    drive_model: str
    drive_media: str
    drive_bus: str
    pending_restart: bool
    startup_items: int
    recycle_bin_bytes: int
    recycle_bin_items: int
    cleanable_bytes: int
    cleanable_files: int
    tools: dict[str, bool]


@dataclass
class OperationRecord:
    name: str
    started: str
    finished: str
    ok: Optional[bool]
    detail: str
    exit_code: Optional[int] = None


# ---------------------------------------------------------------------------------------------------------------------
# Privacy: redact user-identifying path parts before anything is written to a report
# ---------------------------------------------------------------------------------------------------------------------

def redact(text: str, env: Optional[Mapping[str, str]] = None, home: Optional[Path] = None) -> str:
    env = os.environ if env is None else env
    out = str(text)
    pairs: list[tuple[str, str]] = []
    for var in ("LOCALAPPDATA", "APPDATA", "USERPROFILE", "TEMP", "TMP", "ONEDRIVE"):
        value = _env_get(env, var)
        if value:
            pairs.append((value, f"%{var}%"))
    try:
        pairs.append((str(home or Path.home()), "%USERPROFILE%"))
    except RuntimeError:
        pass
    for value, token in sorted(set(pairs), key=lambda p: len(p[0]), reverse=True):
        if len(value) > 3:
            out = re.sub(re.escape(value), token.replace("\\", "\\\\"), out, flags=re.IGNORECASE)
    out = re.sub(r"(?i)([a-z]:\\Users\\)[^\\/:*?\"<>|]+", r"\1<user>", out)
    return out


# ---------------------------------------------------------------------------------------------------------------------
# Cleanup roots: trusted bases, validation, allowlist
# ---------------------------------------------------------------------------------------------------------------------

USER_FOLDERS = ("Documents", "Desktop", "Downloads", "Pictures", "Music", "Videos")


def _env_get(env: Mapping[str, str], name: str) -> Optional[str]:
    """Case-insensitive lookup (real Windows environments already are; plain dicts used in tests are not)."""
    if name in env:
        return env[name] or None
    wanted = name.casefold()
    for k, v in env.items():
        if k.casefold() == wanted:
            return v or None
    return None


def _env_path(env: Mapping[str, str], *names: str) -> Optional[Path]:
    for n in names:
        v = _env_get(env, n)
        if v:
            return Path(v)
    return None


def _trusted_local_appdata(env: Mapping[str, str], home: Path) -> Optional[Path]:
    for cand in (_env_path(env, "LOCALAPPDATA"), home / "AppData" / "Local"):
        if cand is not None and cand.is_absolute() and _tail(cand, 2) == ("appdata", "local"):
            return cand
    return None


def _trusted_named_dir(value: Optional[Path], leaf: str) -> Optional[Path]:
    if value is not None and value.is_absolute() and not _is_drive_root(value) and value.name.casefold() == leaf:
        return value
    return None


def protected_folders(env: Mapping[str, str], home: Path) -> list[Path]:
    """Places a cleanup root must never be inside of (or contain)."""
    out: list[Path] = [home]
    for n in USER_FOLDERS:
        out.append(home / n)
    for var in ("ONEDRIVE", "ONEDRIVECONSUMER", "ONEDRIVECOMMERCIAL"):
        p = _env_path(env, var)
        if p:
            out.append(p)
    for var in ("PROGRAMFILES", "PROGRAMFILES(X86)", "PROGRAMW6432", "PUBLIC"):
        p = _env_path(env, var)
        if p:
            out.append(p)
    return out


def _validate_temp_candidate(temp: Path, protected: list[Path], windir: Optional[Path]) -> str:
    """Return '' if the user's TEMP folder is safe to treat as an allowlisted root, otherwise the reason it is not."""
    if not temp.is_absolute():
        return "TEMP is not an absolute path"
    if _is_drive_root(temp):
        return "TEMP points at a drive root"
    if temp.name.casefold() not in ("temp", "tmp"):
        return "TEMP folder is not named Temp"
    if os.path.lexists(temp) and path_is_link_like(temp):
        return "TEMP is a redirected (linked) folder"
    if windir is not None and _is_within(temp, windir):
        return "TEMP is inside the Windows folder"
    for p in protected:
        if _is_within(temp, p) and os.path.normcase(os.path.abspath(temp)) != os.path.normcase(os.path.abspath(p)):
            # inside the profile is normal (AppData\Local\Temp); only the named personal folders are off-limits
            if p.name in USER_FOLDERS or p.name.casefold().startswith(("onedrive", "program files")) or p.name.casefold() == "public":
                return f"TEMP is inside a protected folder ({p.name})"
        if _is_within(p, temp):
            return f"TEMP contains a protected folder ({p.name or str(p)})"
    return ""


def _root_refusal(root: Path, protected: list[Path], home: Path) -> str:
    """Why a candidate cleanup root is not acceptable ('' if it is). Applied to every root, however it was derived."""
    if not root.is_absolute():
        return "it is not an absolute path"
    if _is_drive_root(root):
        return "it is a drive root"
    for p in protected:
        if os.path.normcase(os.path.abspath(p)) == os.path.normcase(os.path.abspath(home)):
            continue                    # the profile folder itself legitimately contains AppData
        if _is_within(root, p):
            return f"it is inside a protected folder ({p.name or p})"
    return ""


def build_categories(env: Optional[Mapping[str, str]] = None, home: Optional[Path] = None,
                     temp_dir: Optional[str] = None) -> list[CleanupCategory]:
    """Build the fixed cleanup allowlist. Anything that cannot be validated is marked unavailable, not guessed."""
    env = os.environ if env is None else env
    try:
        home = home or Path.home()
    except RuntimeError:
        home = Path(env.get("USERPROFILE", "."))
    local = _trusted_local_appdata(env, home)
    windir = _trusted_named_dir(_env_path(env, "WINDIR", "SYSTEMROOT"), "windows")
    program_data = _trusted_named_dir(_env_path(env, "PROGRAMDATA"), "programdata")
    protected = protected_folders(env, home)
    temp_dir = temp_dir if temp_dir is not None else tempfile.gettempdir()

    def category(key, name, desc, roots, hours, admin, base_ok, why):
        c = CleanupCategory(key, name, desc, [Path(r) for r in roots] if base_ok else [], hours, admin)
        if not base_ok:
            c.unavailable_reason = why
        return c

    user_temp = category("user_temp", "User temporary files",
                         "Temporary files in your Windows user profile older than 48 hours.",
                         [local / "Temp"] if local else [], 48, False, local is not None,
                         "Could not confirm your Local AppData folder.")
    is_default_temp = local is not None and os.path.normcase(os.path.abspath(temp_dir)) == os.path.normcase(os.path.abspath(local / "Temp"))
    if not is_default_temp:                      # a non-default TEMP is only used if it passes every safety rule
        reason = _validate_temp_candidate(Path(temp_dir), protected, windir)
        if reason:
            user_temp.notes.append(f"Your TEMP setting was ignored for safety: {reason}.")
        else:
            user_temp.roots.append(Path(temp_dir))
            user_temp.unavailable_reason = ""

    cats = [
        user_temp,
        category("crash_dumps", "Old application crash dumps",
                 "Crash dump files older than 7 days. These are normally only useful for troubleshooting.",
                 [local / "CrashDumps"] if local else [], 24 * 7, False, local is not None,
                 "Could not confirm your Local AppData folder."),
        category("shader_cache", "DirectX shader cache",
                 "Old DirectX shader cache data older than 7 days. Windows and games recreate it as needed.",
                 [local / "D3DSCache"] if local else [], 24 * 7, False, local is not None,
                 "Could not confirm your Local AppData folder."),
        category("windows_temp", "Windows temporary files",
                 "System temporary files older than 72 hours. Some files need administrator access.",
                 [windir / "Temp"] if windir else [], 72, True, windir is not None,
                 "Could not confirm the Windows folder."),
        category("error_reports", "Old Windows error reports",
                 "Queued and archived Windows Error Reporting files older than 7 days.",
                 [program_data / "Microsoft" / "Windows" / "WER" / "ReportQueue",
                  program_data / "Microsoft" / "Windows" / "WER" / "ReportArchive"] if program_data else [],
                 24 * 7, True, program_data is not None, "Could not confirm the ProgramData folder."),
    ]
    for c in cats:                      # final gate: whatever the base was, no root may be a drive root or inside a personal folder
        kept = []
        for root in c.roots:
            why = _root_refusal(root, protected, home)
            if why:
                c.notes.append(f"{root.name or str(root)} was skipped for safety: {why}.")
            else:
                kept.append(root)
        c.roots = kept
        if not kept and not c.unavailable_reason:
            c.unavailable_reason = "No safe location was found."
    return cats


def unique_roots(category: CleanupCategory) -> list[Path]:
    seen: set[str] = set()
    result: list[Path] = []
    for root in category.roots:
        try:
            key = os.path.normcase(os.path.realpath(root))
        except OSError:
            key = os.path.normcase(str(root))
        if key not in seen:
            seen.add(key)
            result.append(root)
    return result


# ---------------------------------------------------------------------------------------------------------------------
# The single traversal used by both scan and clean
# ---------------------------------------------------------------------------------------------------------------------

def _runtime_protected() -> list[str]:
    """Never touch Odd$ Tune's own PyInstaller extraction folder (it lives inside %TEMP% while the app runs)."""
    out = []
    mei = getattr(sys, "_MEIPASS", None)
    if mei:
        out.append(os.path.normcase(os.path.realpath(mei)))
    return out


def _classify_oserror(exc: OSError) -> str:
    if isinstance(exc, PermissionError):
        return "locked"
    if getattr(exc, "winerror", None) in (5, 32, 33):
        return "locked"
    return "other"


def _walk(root: Path, cutoff: float, stats: WalkStats, dirs: list[tuple[Path, float]]) -> Iterator[tuple[Path, os.stat_result]]:
    """Yield (path, lstat) for every file that is old enough. Never follows links; never leaves ``root``."""
    try:
        root_state = os.lstat(root)
    except FileNotFoundError:
        return                     # missing folder: nothing to do, not an error
    except OSError as exc:
        stats.skipped_other += 1
        stats.note(f"{root}: {type(exc).__name__}")
        return
    if stat_is_link_like(root_state):
        stats.skipped_links += 1
        stats.note(f"{root}: redirected location skipped")
        return
    if not stat.S_ISDIR(root_state.st_mode):
        return
    root_real = os.path.realpath(root)
    runtime = _runtime_protected()
    stack: list[Path] = [root]
    while stack:
        current = stack.pop()
        try:
            cur_state = os.lstat(current)
        except OSError:
            stats.skipped_other += 1
            continue
        if stat_is_link_like(cur_state):                       # re-check right before listing (race/redirect)
            stats.skipped_links += 1
            continue
        cur_real = os.path.realpath(current)
        if not _is_within(cur_real, root_real):                 # something redirected us outside the root
            stats.skipped_links += 1
            continue
        if any(_is_within(cur_real, r) for r in runtime):
            continue
        try:
            with os.scandir(current) as it:
                entries = list(it)
        except OSError as exc:
            if _classify_oserror(exc) == "locked":
                stats.skipped_locked += 1
            else:
                stats.skipped_other += 1
            stats.note(f"{current}: {type(exc).__name__}")
            continue
        dirs.append((current, reference_time(cur_state)))
        for entry in entries:
            try:
                st = entry.stat(follow_symlinks=False)
            except OSError:
                stats.skipped_other += 1
                continue
            if stat_is_link_like(st):
                stats.skipped_links += 1
                continue
            if stat.S_ISDIR(st.st_mode):
                stack.append(Path(entry.path))
                continue
            if not stat.S_ISREG(st.st_mode):
                stats.skipped_other += 1
                continue
            if reference_time(st) > cutoff:
                stats.skipped_recent += 1
                continue
            yield Path(entry.path), st


def scan_root(root: Path, min_age_hours: int, now: Optional[float] = None) -> WalkStats:
    """Read-only: report what clean_root would remove. Performs no writes of any kind."""
    stats = WalkStats()
    cutoff = (time.time() if now is None else now) - min_age_hours * 3600
    for _path, st in _walk(Path(root), cutoff, stats, []):
        stats.found_bytes += st.st_size
        stats.found_files += 1
    return stats


def _delete_one(path: Path, st: os.stat_result, cutoff: float, stats: WalkStats) -> None:
    try:
        fresh = os.lstat(path)                                  # re-check immediately before deleting
    except FileNotFoundError:
        return
    except OSError as exc:
        stats.skipped_other += 1
        stats.note(f"{path}: {type(exc).__name__}")
        return
    if stat_is_link_like(fresh):
        stats.skipped_links += 1
        return
    if reference_time(fresh) > cutoff:
        stats.skipped_recent += 1
        return
    try:
        try:
            os.unlink(path)
        except PermissionError:
            if is_windows() and getattr(fresh, "st_file_attributes", 0) & FILE_ATTRIBUTE_READONLY:
                os.chmod(path, stat.S_IWRITE)                   # old read-only temp file: clear the flag, retry once
                os.unlink(path)
            else:
                raise
    except FileNotFoundError:
        return
    except OSError as exc:
        if _classify_oserror(exc) == "locked":
            stats.skipped_locked += 1
        else:
            stats.skipped_other += 1
        stats.note(f"{path}: {type(exc).__name__}")
        return
    stats.deleted_bytes += fresh.st_size
    stats.deleted_files += 1


def clean_root(root: Path, min_age_hours: int, now: Optional[float] = None) -> WalkStats:
    """Delete eligible old files below ``root``. The root itself is never removed. Never raises for a single bad file."""
    stats = WalkStats()
    cutoff = (time.time() if now is None else now) - min_age_hours * 3600
    dirs: list[tuple[Path, float]] = []
    for path, st in _walk(Path(root), cutoff, stats, dirs):
        stats.found_bytes += st.st_size
        stats.found_files += 1
        _delete_one(path, st, cutoff, stats)
    # Remove empty child folders that were themselves old before we emptied them. Never the root.
    for d, age in sorted(dirs[1:], key=lambda x: len(x[0].parts), reverse=True):
        if age > cutoff or path_is_link_like(d):
            continue
        try:
            os.rmdir(d)
            stats.removed_empty_dirs += 1
        except OSError:
            pass
    return stats


def scan_categories(categories: list[CleanupCategory], now: Optional[float] = None) -> None:
    for c in categories:
        c.reset()
        c.reset_estimate()
        if not c.available:
            continue
        for root in unique_roots(c):
            c.stats.merge(scan_root(root, c.min_age_hours, now))
        c.estimate_bytes, c.estimate_files = c.stats.found_bytes, c.stats.found_files


def clean_categories(categories: list[CleanupCategory], selected: set[str], now: Optional[float] = None,
                     progress: Optional[Callable[[str], None]] = None) -> None:
    for c in categories:
        if c.key not in selected or not c.available:
            continue
        c.reset()
        for root in unique_roots(c):
            if progress:
                progress(f"Cleaning {c.name}")
            c.stats.merge(clean_root(root, c.min_age_hours, now))


# ---------------------------------------------------------------------------------------------------------------------
# Windows facts (all read-only)
# ---------------------------------------------------------------------------------------------------------------------

def is_admin() -> bool:
    if not is_windows():
        return False
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())  # type: ignore[attr-defined]
    except Exception:
        return False


def bytes_readable(value: int) -> str:
    n = float(max(0, value))
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.2f} {unit}"
        n /= 1024
    return f"{n:.2f} PB"


_DRIVE_RX = re.compile(r"^[A-Za-z]:$")


def system_drive(env: Optional[Mapping[str, str]] = None) -> str:
    """The drive Windows is installed on (validated 'X:'), never blindly 'C:' when the OS says otherwise."""
    env = os.environ if env is None else env
    for cand in (_env_get(env, "SystemDrive"), (_env_get(env, "SystemRoot") or _env_get(env, "WINDIR") or "")[:2]):
        if cand and _DRIVE_RX.match(cand):
            return cand.upper()
    return "C:"


def system32_exe(name: str, env: Optional[Mapping[str, str]] = None) -> str:
    env = os.environ if env is None else env
    windir = _trusted_named_dir(_env_path(env, "SYSTEMROOT", "WINDIR"), "windows") or Path(system_drive(env) + "\\Windows")
    return str(windir / "System32" / name)


def windows_details() -> tuple[str, str, str, str, str]:
    """(name, build, architecture, support_tier, support_note)."""
    arch_raw = (os.environ.get("PROCESSOR_ARCHITEW6432") or os.environ.get("PROCESSOR_ARCHITECTURE") or platform.machine()).upper()
    arch = "x64" if arch_raw in ("AMD64", "X86_64") else ("ARM64" if arch_raw == "ARM64" else arch_raw)
    if not is_windows():
        return platform.system() or "Unknown", "", arch, "unsupported", "Odd$ Tune is a Windows utility."
    v = sys.getwindowsversion()  # type: ignore[attr-defined]
    build = int(v.build)
    if v.major == 10 and build >= 22000:
        name = "Windows 11"
    elif v.major == 10:
        name = "Windows 10"
    else:
        name = f"Windows {v.major}.{v.minor}"
    if arch != "x64":
        return name, str(build), arch, "unsupported", f"{arch} is not a tested target. Odd$ Tune v{APP_VERSION} supports Windows x64."
    if name == "Windows 11":
        return name, str(build), arch, "primary", "Windows 11 x64 is the primary target."
    if name == "Windows 10" and build >= 19041:
        return name, str(build), arch, "best-effort", "Windows 10 x64 is best-effort support."
    return name, str(build), arch, "unsupported", "This Windows version is not a supported target."


def total_ram_bytes() -> int:
    if not is_windows():
        return 0

    class MEMORYSTATUSEX(ctypes.Structure):
        _fields_ = [("dwLength", ctypes.c_uint32), ("dwMemoryLoad", ctypes.c_uint32),
                    ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]

    state = MEMORYSTATUSEX()
    state.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
    try:
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(state))  # type: ignore[attr-defined]
        return int(state.ullTotalPhys)
    except Exception:
        return 0


def cpu_name() -> str:
    if is_windows():
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0") as k:
                value, _ = winreg.QueryValueEx(k, "ProcessorNameString")
                return " ".join(str(value).split())
        except Exception:
            pass
    return platform.processor() or "Unknown"


def pending_restart() -> bool:
    if not is_windows():
        return False
    try:
        import winreg
        for key in (r"SOFTWARE\Microsoft\Windows\CurrentVersion\Component Based Servicing\RebootPending",
                    r"SOFTWARE\Microsoft\Windows\CurrentVersion\WindowsUpdate\Auto Update\RebootRequired"):
            try:
                winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key).Close()
                return True
            except OSError:
                pass
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\Session Manager") as k:
                value, _ = winreg.QueryValueEx(k, "PendingFileRenameOperations")
                return bool(value)
        except OSError:
            pass
    except Exception:
        pass
    return False


def startup_item_count() -> int:
    """Approximate count of startup entries (Run keys and Startup folders). Informational only."""
    if not is_windows():
        return 0
    count = 0
    try:
        import winreg
        for hive, path in ((winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run"),
                           (winreg.HKEY_LOCAL_MACHINE, r"Software\Microsoft\Windows\CurrentVersion\Run"),
                           (winreg.HKEY_LOCAL_MACHINE, r"Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Run")):
            try:
                with winreg.OpenKey(hive, path) as key:
                    i = 0
                    while True:
                        try:
                            winreg.EnumValue(key, i)
                            count += 1
                            i += 1
                        except OSError:
                            break
            except OSError:
                pass
    except Exception:
        pass
    for var in ("APPDATA", "PROGRAMDATA"):
        base = os.environ.get(var)
        if not base:
            continue
        p = Path(base) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
        try:
            count += sum(1 for x in p.iterdir() if x.is_file() and x.name.lower() != "desktop.ini")
        except OSError:
            pass
    return count


class _SHQUERYRBINFO(ctypes.Structure):
    _pack_ = 1   # the Windows header packs this struct on 1-byte boundaries (20 bytes); default packing breaks the call
    _fields_ = [("cbSize", ctypes.c_uint32), ("i64Size", ctypes.c_longlong), ("i64NumItems", ctypes.c_longlong)]


def recycle_bin_info(drive: Optional[str] = None) -> tuple[int, int]:
    """(bytes, items) in the Recycle Bin of the system drive. (0, 0) if it cannot be read."""
    if not is_windows():
        return 0, 0
    info = _SHQUERYRBINFO()
    info.cbSize = ctypes.sizeof(info)
    try:
        fn = ctypes.windll.shell32.SHQueryRecycleBinW  # type: ignore[attr-defined]
        fn.argtypes = [ctypes.c_wchar_p, ctypes.c_void_p]
        fn.restype = ctypes.c_long
        rc = fn((drive or system_drive()) + "\\", ctypes.byref(info))
        return (int(info.i64Size), int(info.i64NumItems)) if rc == 0 else (0, 0)
    except Exception:
        return 0, 0


def empty_recycle_bin(drive: Optional[str] = None) -> tuple[bool, str]:
    if not is_windows():
        return False, "Windows only."
    size, items = recycle_bin_info(drive)
    if items == 0 and size == 0:
        return True, "The Recycle Bin was already empty."
    flags = 0x1 | 0x2 | 0x4        # no confirmation, no progress UI, no sound
    try:
        fn = ctypes.windll.shell32.SHEmptyRecycleBinW  # type: ignore[attr-defined]
        fn.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_uint32]
        fn.restype = ctypes.c_long
        rc = fn(None, (drive or system_drive()) + "\\", flags)
        return rc == 0, "Recycle Bin emptied." if rc == 0 else f"Windows returned code {rc & 0xFFFFFFFF:#x}."
    except Exception as exc:
        return False, redact(str(exc))


# --- Drive type, read-only, without launching any process -------------------------------------------------------------
# Uses the same documented IOCTLs Windows' own tools use. Opening the volume with access 0 allows query-only calls and
# needs no administrator rights. If anything fails the answer is "Unknown": we never guess.

IOCTL_STORAGE_QUERY_PROPERTY = 0x002D1400
STORAGE_DEVICE_PROPERTY = 0
STORAGE_DEVICE_SEEK_PENALTY_PROPERTY = 7
BUS_TYPES = {0: "Unknown", 1: "SCSI", 2: "ATAPI", 3: "ATA", 4: "1394", 5: "SSA", 6: "Fibre Channel", 7: "USB", 8: "RAID", 9: "iSCSI",
             10: "SAS", 11: "SATA", 12: "SD", 13: "MMC", 14: "Virtual", 15: "File-backed virtual", 16: "Storage Spaces", 17: "NVMe",
             18: "SCM", 19: "UFS"}


def parse_seek_penalty(buf: bytes) -> Optional[bool]:
    """DEVICE_SEEK_PENALTY_DESCRIPTOR: Version u32, Size u32, IncursSeekPenalty u8. True = spinning disk."""
    if len(buf) < 9:
        return None
    return bool(buf[8])


def parse_device_descriptor(buf: bytes) -> tuple[str, str]:
    """STORAGE_DEVICE_DESCRIPTOR -> (model, bus type). Strings live at offsets inside the buffer."""
    import struct
    if len(buf) < 36:
        return "Unknown", "Unknown"
    vendor_off, product_off = struct.unpack_from("<II", buf, 12)
    bus = struct.unpack_from("<I", buf, 28)[0]

    def text(off: int) -> str:
        if not off or off >= len(buf):
            return ""
        end = buf.find(b"\x00", off)
        return buf[off:end if end != -1 else len(buf)].decode("ascii", "replace").strip()

    model = " ".join(x for x in (text(vendor_off), text(product_off)) if x) or "Unknown"
    return model, BUS_TYPES.get(bus, "Unknown")


def _query_storage_property(handle, property_id: int, size: int = 1024) -> Optional[bytes]:
    from ctypes import wintypes

    class Query(ctypes.Structure):
        _fields_ = [("PropertyId", ctypes.c_uint32), ("QueryType", ctypes.c_uint32), ("Extra", ctypes.c_ubyte * 1)]

    k = ctypes.windll.kernel32  # type: ignore[attr-defined]
    k.DeviceIoControl.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD, ctypes.c_void_p,
                                  wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]
    k.DeviceIoControl.restype = wintypes.BOOL
    query = Query(property_id, 0)          # PropertyStandardQuery
    out = ctypes.create_string_buffer(size)
    returned = wintypes.DWORD(0)
    ok = k.DeviceIoControl(handle, IOCTL_STORAGE_QUERY_PROPERTY, ctypes.byref(query), ctypes.sizeof(query), out, size,
                           ctypes.byref(returned), None)
    return out.raw[:returned.value] if ok else None


def detect_drive(drive: Optional[str] = None) -> tuple[str, str, str]:
    """(model, media type, bus type) for the system drive. 'Unknown' where Windows does not say."""
    if not is_windows():
        return "Unknown", "Unknown", "Unknown"
    drive = drive or system_drive()
    if not _DRIVE_RX.match(drive):
        return "Unknown", "Unknown", "Unknown"
    try:
        from ctypes import wintypes
        k = ctypes.windll.kernel32  # type: ignore[attr-defined]
        k.CreateFileW.restype = wintypes.HANDLE
        k.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD,
                                  wintypes.DWORD, wintypes.HANDLE]
        k.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = k.CreateFileW("\\\\.\\" + drive, 0, 3, None, 3, 0, None)   # query-only access, share read/write, OPEN_EXISTING
        if handle in (None, wintypes.HANDLE(-1).value):
            return "Unknown", "Unknown", "Unknown"
        try:
            device = _query_storage_property(handle, STORAGE_DEVICE_PROPERTY)
            penalty = _query_storage_property(handle, STORAGE_DEVICE_SEEK_PENALTY_PROPERTY)
        finally:
            k.CloseHandle(handle)
        model, bus = parse_device_descriptor(device) if device else ("Unknown", "Unknown")
        seek = parse_seek_penalty(penalty) if penalty else None
        media = "Unknown" if seek is None else ("HDD" if seek else "SSD")
        return model, media, bus
    except Exception:
        return "Unknown", "Unknown", "Unknown"


def tool_availability() -> dict[str, bool]:
    names = {"defrag": "defrag.exe", "dism": "Dism.exe", "sfc": "sfc.exe"}
    return {k: bool(is_windows() and os.path.isfile(system32_exe(v))) for k, v in names.items()}


def collect_snapshot(categories: list[CleanupCategory]) -> HealthSnapshot:
    """Read-only. Scans the allowlisted locations and gathers system facts. Writes nothing."""
    scan_categories(categories)
    drive = system_drive()
    try:
        usage = shutil.disk_usage(drive + "\\" if is_windows() else Path.home())
        total, used, free = usage.total, usage.used, usage.free
    except OSError:
        total = used = free = 0
    name, build, arch, tier, note = windows_details()
    model, media, bus = detect_drive(drive)
    rb_bytes, rb_items = recycle_bin_info(drive)
    return HealthSnapshot(
        timestamp=dt.datetime.now().astimezone().isoformat(timespec="seconds"), app_version=APP_VERSION,
        windows=name, build=build, architecture=arch, support_tier=tier, support_note=note,
        cpu=cpu_name(), logical_cpus=os.cpu_count() or 0, admin=is_admin(), total_ram=total_ram_bytes(),
        system_drive=drive, disk_total=total, disk_used=used, disk_free=free,
        drive_model=model, drive_media=media, drive_bus=bus, pending_restart=pending_restart(),
        startup_items=startup_item_count(), recycle_bin_bytes=rb_bytes, recycle_bin_items=rb_items,
        cleanable_bytes=sum(c.estimate_bytes for c in categories),
        cleanable_files=sum(c.estimate_files for c in categories), tools=tool_availability())


# ---------------------------------------------------------------------------------------------------------------------
# Opening Windows UI and elevation (no scripts written to disk, no encoded commands)
# ---------------------------------------------------------------------------------------------------------------------

def open_startup_settings() -> None:
    """Open Windows' Startup Apps page. Odd$ Tune never disables a startup item itself."""
    if not is_windows():
        return
    try:
        os.startfile("ms-settings:startupapps")  # type: ignore[attr-defined]
    except Exception:
        subprocess.Popen([system32_exe("Taskmgr.exe")], shell=False)


def _shell_execute_runas(executable: str, params: str) -> str:
    """Returns 'started', 'denied' (user said No to UAC) or 'failed'."""
    if not is_windows():
        return "failed"
    try:
        fn = ctypes.windll.shell32.ShellExecuteW  # type: ignore[attr-defined]
        fn.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_int]
        fn.restype = ctypes.c_void_p
        rc = int(fn(None, "runas", executable, params, None, 1) or 0)
    except Exception:
        return "failed"
    if rc > 32:
        return "started"
    return "denied" if rc == 5 else "failed"


def _self_command(extra: list[str]) -> tuple[str, str]:
    if getattr(sys, "frozen", False):
        return sys.executable, subprocess.list2cmdline(extra)
    return sys.executable, subprocess.list2cmdline([str(Path(sys.argv[0]).resolve())] + extra)


def relaunch_as_admin() -> str:
    exe, params = _self_command([])
    return _shell_execute_runas(exe, params)


TASKS = ("optimize", "repair")


def launch_elevated_task(task: str) -> str:
    """Start Odd$ Tune itself, elevated, in worker mode. Only a fixed task name crosses the UAC boundary."""
    if task not in TASKS:
        return "failed"
    exe, params = _self_command(["--task", task])
    return _shell_execute_runas(exe, params)


# ---------------------------------------------------------------------------------------------------------------------
# Maintenance tasks (run by the elevated worker): defrag /O, then DISM + SFC
# ---------------------------------------------------------------------------------------------------------------------

@dataclass
class CommandSpec:
    label: str
    argv: list[str]


def maintenance_commands(task: str, env: Optional[Mapping[str, str]] = None) -> list[CommandSpec]:
    if task == "optimize":
        drive = system_drive(env)
        # /O = Windows picks the right optimization for the media (TRIM for SSD, defrag for HDD). /U progress, /V verbose.
        return [CommandSpec(f"Drive optimization ({drive})", [system32_exe("defrag.exe", env), drive, "/O", "/U", "/V"])]
    if task == "repair":
        return [CommandSpec("DISM component-store repair", [system32_exe("Dism.exe", env), "/Online", "/Cleanup-Image", "/RestoreHealth"]),
                CommandSpec("System File Checker", [system32_exe("sfc.exe", env), "/scannow"])]
    raise ValueError(f"unknown task: {task}")


_PROGRESS_RX = re.compile(r"^\s*(\[[= ]*[\d.]+%[= ]*\]|Verification \d+% complete\.?|([\w\- ]+?\.{0,3}\s*)?\d+% complete\.?)\s*$")
_SFC_HINTS = (
    ("did not find any integrity violations", True, "No integrity violations were found."),
    ("found corrupt files and successfully repaired them", True, "Corrupt files were found and repaired."),
    ("found corrupt files but was unable to fix", False, "Corrupt files were found but some could not be repaired. See the log."),
    ("unable to start the repair service", False, "Windows Resource Protection could not start the repair service."),
    ("could not perform the requested operation", False, "Windows Resource Protection could not perform the operation."),
)


def interpret_result(label: str, exit_code: Optional[int], output_tail: str) -> tuple[bool, str]:
    """Turn an exit code into a plain-language result. The raw exit code is always shown as well."""
    if exit_code is None:
        return False, "The command could not be started."
    low = output_tail.casefold()
    if "System File Checker" in label:
        for needle, ok, text in _SFC_HINTS:
            if needle in low:
                return ok, text
        return exit_code == 0, f"Finished with exit code {exit_code}. See the log for details."
    if "DISM" in label:
        if exit_code == 0:
            return True, "Completed successfully."
        if exit_code == 3010:
            return True, "Completed. Restart Windows to finish applying changes."
        return False, f"DISM reported exit code {exit_code}. See the log for details."
    if "optimization" in label.casefold():
        return (exit_code == 0), ("Windows finished optimizing the drive." if exit_code == 0 else f"defrag reported exit code {exit_code}.")
    return exit_code == 0, f"Exit code {exit_code}."


def _choose_codec(first_chunk: bytes) -> str:
    if b"\x00" in first_chunk[:64]:
        return "utf-16-le"       # sfc.exe writes UTF-16 when its output is redirected
    return "oem" if is_windows() else "utf-8"


def run_command(spec: CommandSpec, emit: Callable[[str, bool], None],
                popen: Callable[..., subprocess.Popen] = subprocess.Popen) -> OperationRecord:
    started = dt.datetime.now().astimezone().isoformat(timespec="seconds")
    tail: list[str] = []
    code: Optional[int] = None
    try:
        proc = popen(spec.argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, shell=False,
                     creationflags=CREATE_NO_WINDOW if is_windows() else 0)
    except OSError as exc:
        emit(f"Could not start {spec.label}: {type(exc).__name__}", False)
        proc = None
    if proc is not None:
        decoder = None
        buffer = ""
        assert proc.stdout is not None
        while True:
            chunk = proc.stdout.read1(4096) if hasattr(proc.stdout, "read1") else proc.stdout.read(4096)
            if not chunk:
                break
            if decoder is None:
                decoder = codecs.getincrementaldecoder(_choose_codec(chunk))(errors="replace")
            buffer += decoder.decode(chunk)
            parts = re.split(r"\r\n|\n|\r", buffer)
            buffer = parts.pop()
            for line in parts:
                if line.strip():
                    is_progress = bool(_PROGRESS_RX.match(line))
                    emit(line, is_progress)
                    if not is_progress or "100" in line:
                        tail.append(line)
                        tail[:] = tail[-60:]
        if buffer.strip():
            emit(buffer, False)
            tail.append(buffer)
        code = proc.wait()
    ok, summary = interpret_result(spec.label, code, "\n".join(tail))
    finished = dt.datetime.now().astimezone().isoformat(timespec="seconds")
    return OperationRecord(spec.label, started, finished, ok, summary, code)


def _reports_chain_ok(directory: Path) -> bool:
    """Refuse to write through a link: the reports folder and its parent must be real folders (or not exist yet)."""
    for p in (directory, directory.parent):
        if os.path.lexists(p) and path_is_link_like(p):
            return False
    return True


class LogWriter:
    """Append-only log. Created exclusively (never overwrites or follows a pre-planted link) inside the reports folder."""

    def __init__(self, path: Path):
        self.path = path
        self._fh = None
        try:
            if not _reports_chain_ok(path.parent):
                raise OSError("reports folder is a link")
            self._fh = open(path, "x", encoding="utf-8", newline="\n")
        except OSError:
            self._fh = None

    def write(self, line: str) -> None:
        if self._fh:
            self._fh.write(redact(line) + "\n")
            self._fh.flush()

    def close(self) -> None:
        if self._fh:
            self._fh.close()
            self._fh = None


def run_maintenance_task(task: str, emit: Callable[[str, bool], None], log: Optional[LogWriter] = None,
                         popen: Callable[..., subprocess.Popen] = subprocess.Popen) -> list[OperationRecord]:
    records: list[OperationRecord] = []
    if log:
        log.write(f"{APP_NAME} v{APP_VERSION} - {task}")

    def tee(text: str, progress: bool) -> None:
        emit(text, progress)
        if log and (not progress or "100" in text):
            log.write(text)

    for spec in maintenance_commands(task):
        tee(f"=== {spec.label} ===", False)
        rec = run_command(spec, tee, popen)
        tee(f"{spec.label}: {rec.detail} (exit code {rec.exit_code})", False)
        records.append(rec)
    return records


# ---------------------------------------------------------------------------------------------------------------------
# Reports (local only)
# ---------------------------------------------------------------------------------------------------------------------

def documents_dir() -> Path:
    if is_windows():
        try:
            buf = ctypes.create_unicode_buffer(260)
            if ctypes.windll.shell32.SHGetFolderPathW(None, 5, None, 0, buf) == 0 and buf.value:  # type: ignore[attr-defined]
                return Path(buf.value)
        except Exception:
            pass
    docs = Path.home() / "Documents"
    return docs if docs.is_dir() else Path.home()


def report_dir(create: bool = False) -> Path:
    p = documents_dir() / "Favorable Odds" / "Odd$ Tune Reports"
    if create:
        p.mkdir(parents=True, exist_ok=True)
    return p


def build_report(snapshot: HealthSnapshot, categories: list[CleanupCategory], action: str,
                 operations: Optional[list[OperationRecord]] = None, disk_free_before: Optional[int] = None,
                 disk_free_after: Optional[int] = None, recycle_result: Optional[tuple[bool, str]] = None) -> dict:
    snap = asdict(snapshot)
    return {
        "schema_version": REPORT_SCHEMA_VERSION,
        "product": APP_NAME,
        "version": APP_VERSION,
        "publisher": PUBLISHER,
        "action": action,
        "generated": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        "system": snap,
        "disk_free_before": disk_free_before,
        "disk_free_after": disk_free_after,
        "cleanup": [{
            "key": c.key, "name": c.name, "available": c.available, "minimum_age_hours": c.min_age_hours,
            "found_bytes": c.estimate_bytes, "found_files": c.estimate_files,
            "recovered_bytes": c.stats.deleted_bytes, "removed_files": c.stats.deleted_files,
            "removed_empty_folders": c.stats.removed_empty_dirs,
            "skipped_recent": c.stats.skipped_recent, "skipped_links": c.stats.skipped_links,
            "skipped_in_use_or_denied": c.stats.skipped_locked, "skipped_other": c.stats.skipped_other,
            "skipped_total": c.stats.skipped_total, "notes": [redact(n) for n in c.notes],
            "errors": [redact(e) for e in c.stats.errors]} for c in categories],
        "recycle_bin": None if recycle_result is None else {"ok": recycle_result[0], "message": recycle_result[1]},
        "operations": [asdict(o) | {"detail": redact(o.detail)} for o in (operations or [])],
        "privacy": "Generated locally on this computer. Odd$ Tune does not upload reports and contains no telemetry. "
                   "Computer name and user name are not recorded; paths are shortened.",
    }


def render_html(report: dict) -> str:
    e = html.escape
    s = report["system"]
    cards = [("Windows", f"{s['windows']} build {s['build']} ({s['architecture']})"), ("CPU", s["cpu"]),
             ("RAM", bytes_readable(s["total_ram"])),
             ("System drive", f"{s['system_drive']} {bytes_readable(s['disk_used'])} used of {bytes_readable(s['disk_total'])}"),
             ("Disk free", bytes_readable(s["disk_free"])), ("Drive type", f"{s['drive_media']} / {s['drive_bus']} / {s['drive_model']}"),
             ("Administrator", "Yes" if s["admin"] else "No"), ("Restart pending", "Yes" if s["pending_restart"] else "No")]
    cards_html = "".join(f'<div class="card"><b>{e(k)}</b><br>{e(str(v))}</div>' for k, v in cards)
    rows = "".join(
        f"<tr><td>{e(c['name'])}</td><td>{bytes_readable(c['found_bytes'])}<br><small>{c['found_files']} files</small></td>"
        f"<td>{bytes_readable(c['recovered_bytes'])}<br><small>{c['removed_files']} files</small></td>"
        f"<td>{c['skipped_total']}<br><small>recent {c['skipped_recent']}, in use/denied {c['skipped_in_use_or_denied']}, "
        f"linked {c['skipped_links']}, other {c['skipped_other']}</small></td></tr>" for c in report["cleanup"])
    ops = "".join(f"<tr><td>{e(o['name'])}</td><td>{'OK' if o['ok'] else ('Failed' if o['ok'] is False else '-')}</td>"
                  f"<td>{e(str(o['exit_code']) if o['exit_code'] is not None else '-')}</td><td>{e(o['detail'])}</td></tr>"
                  for o in report["operations"])
    ops_html = (f"<h2>Operations</h2><table><thead><tr><th>Operation</th><th>Result</th><th>Exit code</th><th>Details</th></tr></thead>"
                f"<tbody>{ops}</tbody></table>") if ops else ""
    rb = report.get("recycle_bin")
    rb_html = f"<p>Recycle Bin: {e(rb['message'])}</p>" if rb else ""
    errs = [f"{c['name']}: {x}" for c in report["cleanup"] for x in c["errors"]]
    err_html = ("<h2>Items that could not be removed</h2><ul>" + "".join(f"<li>{e(x)}</li>" for x in errs) + "</ul>") if errs else ""
    before_after = ""
    if report.get("disk_free_before") is not None and report.get("disk_free_after") is not None:
        before_after = (f"<p>Free space before: <b>{bytes_readable(report['disk_free_before'])}</b> &rarr; after: "
                        f"<b>{bytes_readable(report['disk_free_after'])}</b></p>")
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{e(APP_NAME)} report</title>
<style>
body{{font-family:Segoe UI,Arial,sans-serif;background:#f5f4f0;color:#0d0d0f;margin:0;padding:28px}}
main{{max-width:920px;margin:auto;background:#fff;border:1px solid #ddd;border-radius:14px;padding:30px}}
h1{{margin:.2em 0}} .pill{{display:inline-block;background:#0d0d0f;color:#fff;padding:4px 12px;border-radius:99px;font-size:13px}}
.cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:10px;margin:20px 0}}
.card{{padding:12px 14px;border:1px solid #ddd;border-radius:10px;font-size:14px}}
table{{width:100%;border-collapse:collapse;margin:12px 0 22px}} th,td{{text-align:left;padding:9px;border-bottom:1px solid #e5e5e5;vertical-align:top;font-size:14px}}
th{{background:#f7f7f7}} small{{color:#666}} footer{{margin-top:24px;font-size:12px;color:#666}}
</style></head><body><main>
<span class="pill">{e(str(report['action']).title())}</span>
<h1>{e(APP_NAME)} v{e(APP_VERSION)}</h1>
<p><small>Generated {e(report['generated'])}. {e(report['privacy'])}</small></p>
<div class="cards">{cards_html}</div>
{before_after}
<h2>Cleanup categories</h2>
<table><thead><tr><th>Category</th><th>Eligible found</th><th>Recovered</th><th>Skipped</th></tr></thead><tbody>{rows}</tbody></table>
{rb_html}{ops_html}{err_html}
<footer>{e(PUBLISHER)} &middot; {e(WEBSITE)}</footer>
</main></body></html>"""


def _exclusive_write(directory: Path, base: str, ext: str, text: str) -> Path:
    if not _reports_chain_ok(directory):
        raise OSError("reports folder is a link")
    for n in range(0, 100):
        name = f"{base}{'' if n == 0 else '-' + str(n)}.{ext}"
        path = directory / name
        try:
            with open(path, "x", encoding="utf-8", newline="\n") as fh:
                fh.write(text)
            return path
        except FileExistsError:
            continue
    raise OSError("could not choose a unique report name")


def save_report(report: dict, directory: Optional[Path] = None) -> tuple[Path, Path]:
    """Write the JSON + HTML report pair into the (created on demand) local reports folder."""
    directory = directory or report_dir(create=True)
    directory.mkdir(parents=True, exist_ok=True)
    base = f"odds-tune-{report['action']}_{dt.datetime.now().strftime('%Y%m%d_%H%M%S')}"
    j = _exclusive_write(directory, base, "json", json.dumps(report, indent=2))
    h = _exclusive_write(directory, j.stem, "html", render_html(report))
    return j, h


def list_reports(directory: Optional[Path] = None, limit: int = 50) -> list[Path]:
    directory = directory or report_dir()
    try:
        files = [Path(e.path) for e in os.scandir(directory)
                 if e.name.startswith("odds-tune-") and e.name.rsplit(".", 1)[-1] in ("html", "json", "txt")
                 and e.is_file(follow_symlinks=False)]
    except OSError:
        return []
    def mtime(p: Path) -> float:
        try:
            return p.stat().st_mtime
        except OSError:
            return 0.0
    return sorted(files, key=mtime, reverse=True)[:limit]
