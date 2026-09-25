"""Low-level reading and change detection for Elite Dangerous Status.json."""

from __future__ import annotations

import ctypes
import json
import os
from ctypes import wintypes
from os import PathLike
from pathlib import Path
from typing import Any


ELITE_DANGEROUS_PROCESS = "EliteDangerous64.exe"
TH32CS_SNAPPROCESS = 0x00000002


class _ProcessEntry32W(ctypes.Structure):
    """Windows Tool Help process entry used for executable-name enumeration."""

    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("th32DefaultHeapID", ctypes.c_size_t),
        ("th32ModuleID", wintypes.DWORD),
        ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD),
        ("pcPriClassBase", wintypes.LONG),
        ("dwFlags", wintypes.DWORD),
        ("szExeFile", wintypes.WCHAR * 260),
    ]


def _windows_process_names() -> tuple[str, ...]:
    """Return executable names from the Windows process snapshot API."""
    if os.name != "nt":
        return ()
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(_ProcessEntry32W)]
    kernel32.Process32FirstW.restype = wintypes.BOOL
    kernel32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(_ProcessEntry32W)]
    kernel32.Process32NextW.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL

    snapshot = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snapshot == wintypes.HANDLE(-1).value:
        return ()
    names = []
    try:
        entry = _ProcessEntry32W()
        entry.dwSize = ctypes.sizeof(entry)
        if kernel32.Process32FirstW(snapshot, ctypes.byref(entry)):
            while True:
                names.append(entry.szExeFile)
                if not kernel32.Process32NextW(snapshot, ctypes.byref(entry)):
                    break
    finally:
        kernel32.CloseHandle(snapshot)
    return tuple(names)


def elite_dangerous_is_running() -> bool:
    """Return whether the actual Elite Dangerous game process is running."""
    expected = ELITE_DANGEROUS_PROCESS.casefold()
    return any(name.casefold() == expected for name in _windows_process_names())


def read_status_if_changed(
    path: str | PathLike[str],
    previous_mtime_ns: int | None,
    *,
    force: bool = False,
) -> tuple[int, Any] | None:
    """Read a status document when its file has changed or rereading is forced."""
    status_path = Path(path)
    mtime_ns = status_path.stat().st_mtime_ns
    if not force and mtime_ns == previous_mtime_ns:
        return None
    payload = json.loads(status_path.read_text(encoding="utf-8"))
    return mtime_ns, payload
