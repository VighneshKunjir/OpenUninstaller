"""Cleaning tools: Junk Files Cleaner, History Cleaner, Unrecoverable Delete, Evidence Remover, Windows Tools."""

from __future__ import annotations

import ctypes
import fnmatch
import glob
import os
import shutil
import subprocess
import time
import winreg
from dataclasses import dataclass
from typing import Callable

from . import winutil as wu
from .config import settings, DEFAULT_JUNK_PATTERNS

Progress = Callable[[str], None]
Cancelled = Callable[[], bool]

# ---------------------------------------------------------------- junk files


@dataclass
class JunkFile:
    path: str
    size: int
    pattern: str
    description: str


def fixed_drives() -> list[str]:
    mask = ctypes.windll.kernel32.GetLogicalDrives()
    out = []
    for i in range(26):
        if mask & (1 << i):
            root = f"{chr(65 + i)}:\\"
            if ctypes.windll.kernel32.GetDriveTypeW(root) == 3:   # DRIVE_FIXED
                out.append(root)
    return out


def scan_junk(roots: list[str], progress: Progress = lambda s: None, cancelled: Cancelled = lambda: False,
              include_cloud: bool | None = None, skipped: list[str] | None = None) -> list[JunkFile]:
    """skipped (optional) collects the phone/cloud folders that were left out."""
    include_cloud = settings["include_cloud_folders"] if include_cloud is None else include_cloud
    pats = [p for p, on in settings["junk_patterns"].items() if on]
    excl = [wu.norm_path(p) for p in settings["junk_excludes"]]
    recent = time.time() - 86400 if settings["junk_skip_recent"] else None
    found: list[JunkFile] = []

    def on_skip(path: str, kind: str):
        if kind == "cloud" and skipped is not None and not any(wu.is_under(path, s) for s in skipped):
            skipped.append(path)

    def excluded(path: str) -> bool:
        n = wu.norm_path(path)
        return any(fnmatch.fnmatch(n, e) or fnmatch.fnmatch(n + "\\", e) for e in excl)

    def consider(full: str, pattern: str, desc: str):
        try:
            st = os.stat(full)
        except OSError:
            return
        if recent and max(st.st_atime, st.st_mtime) > recent:
            return
        found.append(JunkFile(full, st.st_size, pattern, desc))

    for root in roots:
        for dirpath, dirs, files in wu.safe_walk(root, include_cloud, on_skip):
            if cancelled():
                return found
            if excluded(dirpath):
                dirs[:] = []
                continue
            progress(dirpath)
            for f in files:
                low = f.lower()
                for p in pats:
                    if fnmatch.fnmatch(low, p):
                        consider(os.path.join(dirpath, f), p, DEFAULT_JUNK_PATTERNS.get(p, "Custom pattern"))
                        break
    for inc in settings["junk_includes"]:
        inc = wu.norm_path(inc)
        for dirpath, _dirs, files in wu.safe_walk(inc, include_cloud, on_skip):
            for f in files:
                consider(os.path.join(dirpath, f), "(included folder)", "Content of included folder")
    return found


def delete_files(paths: list[str], recycle: bool, progress: Progress = lambda s: None,
                 include_cloud: bool | None = None) -> list[dict]:
    """Returns one record per path: {kind, path, status, detail} (the Uninstall History item format)."""
    include_cloud = settings["include_cloud_folders"] if include_cloud is None else include_cloud
    results = []
    for p in paths:
        progress(p)
        rec = {"kind": "file", "path": p, "value_name": None, "status": "deleted", "detail": ""}
        if not include_cloud and wu.is_cloud_path(p):
            # Last line of defence: never touch phone / cloud storage unless the user opted in
            rec.update(status="skipped", detail="Phone/cloud storage (excluded in Options)")
        else:
            try:
                if recycle:
                    from send2trash import send2trash
                    send2trash(p)
                    rec["status"] = "recycled"
                else:
                    os.remove(p)
            except Exception as e:
                rec.update(status="failed", detail=str(e))
        results.append(rec)
    return results


# ---------------------------------------------------------------- history cleaner

LOCAL = os.environ.get("LOCALAPPDATA", "")
ROAMING = os.environ.get("APPDATA", "")
HKCU = winreg.HKEY_CURRENT_USER
EXPLORER = r"Software\Microsoft\Windows\CurrentVersion\Explorer"


def _rm_glob(*patterns: str) -> int:
    n = 0
    for pat in patterns:
        for p in glob.glob(os.path.expandvars(pat)):
            try:
                if os.path.isdir(p) and not os.path.islink(p):
                    shutil.rmtree(p, ignore_errors=True)
                else:
                    os.remove(p)
                n += 1
            except OSError:
                pass
    return n


def _clear_key(sub: str, keep_key: bool = True) -> int:
    n = 0
    try:
        if keep_key:
            for name, _d, _t in wu.values(HKCU, sub):
                wu.delete_value(HKCU, sub, name)
                n += 1
            for child in wu.subkeys(HKCU, sub):
                wu.delete_key_tree(HKCU, sub + "\\" + child)
                n += 1
        else:
            wu.delete_key_tree(HKCU, sub)
            n += 1
    except OSError:
        pass
    return n


def _empty_recycle_bin() -> int:
    ctypes.windll.shell32.SHEmptyRecycleBinW(None, None, 0x7)   # no confirm, no progress, no sound
    return 1


def _clear_clipboard() -> int:
    if ctypes.windll.user32.OpenClipboard(None):
        ctypes.windll.user32.EmptyClipboard()
        ctypes.windll.user32.CloseClipboard()
    return 1


def _clear_regedit_lastkey() -> int:
    try:
        wu.delete_value(HKCU, r"Software\Microsoft\Windows\CurrentVersion\Applets\Regedit", "LastKey")
        return 1
    except OSError:
        return 0


def _chromium(base: str) -> dict[str, Callable[[], int]]:
    profiles = os.path.join(LOCAL, base, "User Data", "*")
    return {
        "Cache": lambda: _rm_glob(profiles + r"\Cache\*", profiles + r"\Code Cache\*", profiles + r"\GPUCache\*"),
        "History": lambda: _rm_glob(profiles + r"\History", profiles + r"\History-journal",
                                    profiles + r"\Visited Links", profiles + r"\Top Sites"),
        "Cookies": lambda: _rm_glob(profiles + r"\Network\Cookies", profiles + r"\Cookies"),
        "Download history": lambda: _rm_glob(profiles + r"\DownloadMetadata"),
        "Session": lambda: _rm_glob(profiles + r"\Sessions\*", profiles + r"\Current Session",
                                    profiles + r"\Last Session"),
    }


def _firefox() -> dict[str, Callable[[], int]]:
    prof = os.path.join(ROAMING, r"Mozilla\Firefox\Profiles\*")
    cache = os.path.join(LOCAL, r"Mozilla\Firefox\Profiles\*")
    return {
        "Cache": lambda: _rm_glob(cache + r"\cache2\*", cache + r"\startupCache\*"),
        "History": lambda: _rm_glob(prof + r"\places.sqlite", prof + r"\places.sqlite-wal", prof + r"\formhistory.sqlite"),
        "Cookies": lambda: _rm_glob(prof + r"\cookies.sqlite", prof + r"\cookies.sqlite-wal"),
        "Session": lambda: _rm_glob(prof + r"\sessionstore*", prof + r"\sessionstore-backups\*"),
    }


def history_cleaners() -> dict[str, dict[str, Callable[[], int]]]:
    win = os.environ.get("SystemRoot", r"C:\Windows")
    office = r"Software\Microsoft\Office"

    def office_mru(app: str) -> Callable[[], int]:
        def run():
            n = 0
            for ver in wu.subkeys(HKCU, office):
                base = f"{office}\\{ver}\\{app}"
                n += _clear_key(base + r"\File MRU") + _clear_key(base + r"\Place MRU")
                for ident in wu.subkeys(HKCU, base + r"\User MRU"):
                    n += _clear_key(f"{base}\\User MRU\\{ident}\\File MRU")
            return n
        return run

    return {
        "Windows": {
            "Recent documents history": lambda: _rm_glob(ROAMING + r"\Microsoft\Windows\Recent\*.lnk")
            + _clear_key(EXPLORER + r"\RecentDocs"),
            "Start menu Run history": lambda: _clear_key(EXPLORER + r"\RunMRU"),
            "Explorer search history": lambda: _clear_key(EXPLORER + r"\WordWheelQuery")
            + _clear_key(EXPLORER + r"\TypedPaths"),
            "Common dialog open/save history": lambda: _clear_key(EXPLORER + r"\ComDlg32\OpenSavePidlMRU"),
            "Common dialog last visited folders": lambda: _clear_key(EXPLORER + r"\ComDlg32\LastVisitedPidlMRU"),
            "Paint recent files": lambda: _clear_key(r"Software\Microsoft\Windows\CurrentVersion\Applets\Paint\Recent File List"),
            "WordPad recent files": lambda: _clear_key(r"Software\Microsoft\Windows\CurrentVersion\Applets\Wordpad\Recent File List"),
            "Regedit last opened key": _clear_regedit_lastkey,
            "Empty clipboard": _clear_clipboard,
            "Empty Recycle Bin": _empty_recycle_bin,
            "Windows temporary files": lambda: _rm_glob(os.environ.get("TEMP", "") + r"\*", win + r"\Temp\*"),
            "Jump lists (start menu click logs)": lambda: _rm_glob(
                ROAMING + r"\Microsoft\Windows\Recent\AutomaticDestinations\*",
                ROAMING + r"\Microsoft\Windows\Recent\CustomDestinations\*"),
            "Crash memory dumps": lambda: _rm_glob(win + r"\Minidump\*", win + r"\MEMORY.DMP",
                                                   LOCAL + r"\CrashDumps\*"),
            "Chkdsk file fragments": lambda: sum(_rm_glob(d + r"FOUND.*\*.chk") for d in fixed_drives()),
            "Thumbnail cache": lambda: _rm_glob(LOCAL + r"\Microsoft\Windows\Explorer\thumbcache_*.db",
                                                LOCAL + r"\Microsoft\Windows\Explorer\iconcache_*.db"),
        },
        "Google Chrome": _chromium(r"Google\Chrome"),
        "Microsoft Edge": _chromium(r"Microsoft\Edge"),
        "Brave": _chromium(r"BraveSoftware\Brave-Browser"),
        "Mozilla Firefox": _firefox(),
        "Microsoft Office": {f"{a} recent files": office_mru(a) for a in ("Word", "Excel", "PowerPoint", "Access")},
    }


# ---------------------------------------------------------------- secure deletion


def shred_file(path: str, passes: int = 3, chunk: int = 1 << 20) -> None:
    """Overwrite a file with random data `passes` times, rename it and delete it.

    Note: on SSDs wear levelling means overwritten blocks may survive internally; use the
    drive's secure-erase / TRIM for a guarantee there.
    """
    size = os.path.getsize(path)
    os.chmod(path, 0o666)
    with open(path, "r+b", buffering=0) as f:
        for _ in range(passes):
            f.seek(0)
            left = size
            while left > 0:
                n = min(chunk, left)
                f.write(os.urandom(n))
                left -= n
            os.fsync(f.fileno())
    folder = os.path.dirname(path)
    tmp = os.path.join(folder, "0" * min(len(os.path.basename(path)), 12))
    try:
        os.replace(path, tmp)
        path = tmp
    except OSError:
        pass
    os.remove(path)


def shred_paths(paths: list[str], progress: Progress = lambda s: None, cancelled: Cancelled = lambda: False,
                passes: int = 3) -> tuple[int, list[str]]:
    done, errors = 0, []
    include_cloud = settings["include_cloud_folders"]
    for p in paths:
        if not include_cloud and wu.is_cloud_path(p):
            errors.append(f"{p}: phone/cloud storage - skipped (allow it in Options)")
            continue
        targets = [p] if os.path.isfile(p) else [os.path.join(r, f) for r, _d, fs in
                                                 wu.safe_walk(p, include_cloud) for f in fs]
        for t in targets:
            if cancelled():
                return done, errors
            progress(t)
            try:
                shred_file(t, passes)
                done += 1
            except OSError as e:
                errors.append(f"{t}: {e}")
        if os.path.isdir(p):
            shutil.rmtree(p, ignore_errors=True)
    return done, errors


def wipe_free_space(drive: str, progress: Callable[[str, float], None] = lambda s, f: None,
                    cancelled: Cancelled = lambda: False, passes: int = 3) -> None:
    """Evidence Remover: fill the drive's free space with random data, then release it."""
    folder = os.path.join(drive, "OpenUninstaller_wipe.tmp")
    os.makedirs(folder, exist_ok=True)
    try:
        for n in range(passes):
            total = shutil.disk_usage(drive).free
            written = 0
            idx = 0
            block = os.urandom(4 << 20)
            while not cancelled():
                path = os.path.join(folder, f"fill{idx:05d}.bin")
                idx += 1
                try:
                    with open(path, "wb", buffering=0) as f:
                        for _ in range(256):          # 1 GB per file keeps FAT32 happy
                            if cancelled():
                                break
                            f.write(block)
                            written += len(block)
                            progress(f"Pass {n + 1}/{passes}", min(written / max(total, 1), 1.0))
                except OSError:                     # disk full - this pass is complete
                    break
            for f in os.listdir(folder):
                try:
                    os.remove(os.path.join(folder, f))
                except OSError:
                    pass
            if cancelled():
                break
    finally:
        shutil.rmtree(folder, ignore_errors=True)


# ---------------------------------------------------------------- windows tools

WINDOWS_TOOLS = [
    ("System Restore", "rstrui.exe"),
    ("Network Information", "cmd.exe /k ipconfig /all"),
    ("Windows Security", "start windowsdefender:"),
    ("System Properties", "SystemPropertiesAdvanced.exe"),
    ("System Information", "msinfo32.exe"),
    ("TCP/IP Netstat", "cmd.exe /k netstat -a -b -n"),
    ("On-Screen Keyboard", "osk.exe"),
    ("Disk Defragmenter", "dfrgui.exe"),
    ("Services", "services.msc"),
    ("Shared Folders", "fsmgmt.msc"),
    ("Group Policy", "gpedit.msc"),
    ("Windows Features", "optionalfeatures.exe"),
    ("Malicious Software Removal Tool", "mrt.exe"),
    ("Backup and Restore", "sdclt.exe"),
    ("Task Scheduler", "taskschd.msc"),
    ("Check Disk", "cmd.exe /k chkdsk"),
    ("System File Checker", "cmd.exe /k sfc /scannow"),
    ("Disk Cleanup", "cleanmgr.exe"),
    ("Resource Monitor", "resmon.exe"),
    ("DISM Health Restore", "cmd.exe /k DISM /Online /Cleanup-Image /RestoreHealth"),
    ("Flush DNS cache", "cmd.exe /k ipconfig /flushdns"),
    ("DirectX Diagnostic", "dxdiag.exe"),
    ("Device Manager", "devmgmt.msc"),
    ("Event Viewer", "eventvwr.msc"),
    ("Registry Editor", "regedit.exe"),
]


def launch_tool(command: str) -> None:
    subprocess.Popen(command, shell=True)
