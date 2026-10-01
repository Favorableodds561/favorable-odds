"""Shared test helpers. Tests only ever touch directories they create themselves under a TemporaryDirectory."""
from __future__ import annotations

import hashlib
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import odds_tune_core as core  # noqa: E402

IS_WINDOWS = os.name == "nt"
HOUR = 3600


def write(path: Path, data: bytes = b"x", age_hours: float = 0) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    if age_hours:
        make_old(path, age_hours)
    return path


def make_old(path: Path, age_hours: float) -> None:
    """Make an item look ``age_hours`` old by modified time (and by creation time on Windows)."""
    t = time.time() - age_hours * HOUR
    os.utime(path, (t, t))
    if IS_WINDOWS:
        set_creation_time(path, t)


def set_creation_time(path: Path, ts: float) -> None:
    """Windows only: set the creation time (FILE_BASIC_INFO) so 'old by creation time' can be tested for real."""
    import ctypes
    from ctypes import wintypes

    k = ctypes.windll.kernel32
    k.CreateFileW.restype = wintypes.HANDLE
    k.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID, wintypes.DWORD,
                              wintypes.DWORD, wintypes.HANDLE]
    k.SetFileTime.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.FILETIME), ctypes.c_void_p, ctypes.c_void_p]
    k.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = k.CreateFileW(str(path), 0x100, 7, None, 3, 0x02000000, None)   # WRITE_ATTRIBUTES, share all, OPEN_EXISTING, BACKUP_SEMANTICS
    if handle in (None, wintypes.HANDLE(-1).value):
        raise OSError(f"CreateFileW failed for {path}")
    try:
        ticks = int((ts + 11644473600) * 10_000_000)
        ft = wintypes.FILETIME(ticks & 0xFFFFFFFF, ticks >> 32)
        if not k.SetFileTime(handle, ctypes.byref(ft), None, None):
            raise OSError("SetFileTime failed")
    finally:
        k.CloseHandle(handle)


def tree_fingerprint(root: Path) -> dict[str, tuple]:
    """Everything observable about a tree: paths, sizes, mtimes and content hashes."""
    out: dict[str, tuple] = {}
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        for name in dirnames + filenames:
            p = Path(dirpath) / name
            st = os.lstat(p)
            digest = hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() and not p.is_symlink() else ""
            out[str(p.relative_to(root))] = (st.st_size, st.st_mtime_ns, digest)
    return out
