"""Traced Programs: record what an installer changes, so the program can be removed 100% later.

Works by snapshot diff (no kernel driver): a snapshot of file system locations and registry trees is
taken before the installer runs and again after the user clicks Stop. Everything that appeared in
between is written to a *trace log* (JSON). Snapshots are pickled to disk so a trace survives a reboot.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import pickle
import subprocess
import sys
import uuid
import winreg
from typing import Callable

from . import winutil as wu
from .config import DATA_DIR, settings
from .leftovers import Leftover

LOGS_DIR = os.path.join(DATA_DIR, "TraceLogs")
PENDING = os.path.join(DATA_DIR, "pending_trace.pickle")

SKIP_DIRS = {
    "$recycle.bin", "temp", "inetcache", "webcache", "crashdumps", "packages", "d3dscache", "cache", "caches",
    "code cache", "gpucache", "logs", "windowsapps", "wer", "windows defender", "diagnosis", "search",
    "notifications", "connecteddevicesplatform", "node_modules", "__pycache__",
}
SKIP_REG_PREFIXES = [
    r"software\microsoft\windows\currentversion\explorer",
    r"software\classes\local settings",
    r"software\microsoft\windows\currentversion\cloudstore",
    r"software\microsoft\windows nt\currentversion\appcompatflags",
    r"software\microsoft\windows\currentversion\diagnostics",
    r"software\microsoft\windows defender",
    r"software\microsoft\windows\currentversion\windowsupdate",
    r"software\microsoft\tracing",
    r"software\microsoft\wbem",
    r"system\currentcontrolset\services\bam",
    r"system\currentcontrolset\services\tcpip",
]


def _fs_roots() -> list[tuple[str, bool]]:
    """(path, recursive)"""
    kf = wu.known_folders()
    rec = ["program_files", "program_files_x86", "common_files", "common_files_x86", "program_data",
           "appdata", "local_appdata", "local_low", "start_menu", "common_start_menu", "desktop",
           "public_desktop", "documents", "tasks"]
    roots = [(kf[k], True) for k in rec if kf.get(k)]
    win = kf.get("windows", r"C:\Windows")
    roots += [(os.path.join(win, "System32"), False), (os.path.join(win, "SysWOW64"), False),
              (os.path.join(win, "System32", "drivers"), False), (win, False)]
    roots += [(p, True) for p in settings["trace_roots_extra"]]
    return [(r, recursive) for r, recursive in roots if os.path.isdir(r)]


REG_ROOTS = [
    (winreg.HKEY_CURRENT_USER, "Software", 0),
    (winreg.HKEY_LOCAL_MACHINE, "SOFTWARE", wu.VIEW_64),
    (winreg.HKEY_LOCAL_MACHINE, "SOFTWARE", wu.VIEW_32),
    (winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Services", 0),
]


def snapshot(progress: Callable[[str], None] = lambda s: None) -> dict:
    files: dict[str, tuple[int, int]] = {}
    dirs: set[str] = set()
    include_cloud = settings["include_cloud_folders"]
    for root, recursive in _fs_roots():
        if not include_cloud and wu.is_cloud_path(root):
            continue
        progress(f"Files: {root}")
        stack = [root]
        while stack:
            d = stack.pop()
            try:
                it = os.scandir(d)
            except OSError:
                continue
            with it:
                for e in it:
                    try:
                        if e.is_dir(follow_symlinks=False):
                            kind = wu.entry_kind(e)
                            if kind == "link" or (kind == "cloud" and not include_cloud):
                                continue
                            if recursive and e.name.lower() not in SKIP_DIRS:
                                dirs.add(e.path.lower())
                                stack.append(e.path)
                        else:
                            st = e.stat(follow_symlinks=False)
                            files[e.path.lower()] = (st.st_size, int(st.st_mtime))
                    except OSError:
                        pass
    keys: dict[tuple[int, int, str], dict[str, int]] = {}
    for hive, root, view in REG_ROOTS:
        progress(f"Registry: {wu.wow_display(hive, root, view)}")
        stack = [root]
        while stack:
            sub = stack.pop()
            low = sub.lower()
            if any(low.startswith(p) for p in SKIP_REG_PREFIXES):
                continue
            if view == wu.VIEW_64 and low.startswith("software\\wow6432node"):
                continue
            try:
                k = wu.open_key(hive, sub, view)
            except OSError:
                continue
            with k:
                vals = {}
                for name, data, vtype in wu.iter_values(k):
                    vals[name] = hash((vtype, repr(data)))
                keys[(hive, view, low)] = vals
                for child in wu.iter_subkeys(k):
                    stack.append(sub + "\\" + child)
    return {"time": dt.datetime.now().isoformat(timespec="seconds"), "files": files, "dirs": dirs, "keys": keys}


def _topmost(paths: list[str]) -> list[str]:
    out: list[str] = []
    for p in sorted(paths):
        if not out or not p.startswith(out[-1].rstrip("\\") + "\\"):
            out.append(p)
    return out


_case_cache: dict[tuple[int, int, str], dict[str, str]] = {}


def _real_case(hive: int, view: int, low_sub: str) -> str:
    """Recover the original casing of a key path (snapshots store it lower-cased)."""
    cur = ""
    for part in low_sub.split("\\"):
        ck = (hive, view, cur.lower())
        if ck not in _case_cache:
            _case_cache[ck] = {c.lower(): c for c in wu.subkeys(hive, cur, view)}
        match = _case_cache[ck].get(part, part)
        cur = f"{cur}\\{match}" if cur else match
    return cur


def diff(before: dict, after: dict) -> dict:
    new_dirs = _topmost([d for d in after["dirs"] if d not in before["dirs"]])
    new_files = [f for f in after["files"] if f not in before["files"]
                 and not any(f.startswith(d + "\\") for d in new_dirs)]
    modified = [f for f, meta in after["files"].items() if f in before["files"] and before["files"][f] != meta]
    created_keys_low = [k for k in after["keys"] if k not in before["keys"]]
    created_set = set(created_keys_low)
    top_keys = []
    for hive, view, sub in sorted(created_keys_low, key=lambda k: k[2]):
        parent = sub.rsplit("\\", 1)[0]
        if (hive, view, parent) not in created_set:
            top_keys.append((hive, view, sub))
    new_values, changed_values = [], []
    for key, vals in after["keys"].items():
        old = before["keys"].get(key)
        if old is None:
            continue
        for name, h in vals.items():
            if name not in old:
                new_values.append((*key, name))
            elif old[name] != h:
                changed_values.append((*key, name))

    def real_path(p: str) -> str:
        # Re-case file paths from disk for display
        return os.path.normpath(p) if not os.path.exists(p) else _disk_case(p)

    return {
        "dirs_created": [real_path(d) for d in new_dirs],
        "files_created": [real_path(f) for f in new_files],
        "files_modified": [real_path(f) for f in modified],
        "keys_created": [[h, v, _real_case(h, v, s)] for h, v, s in top_keys],
        "values_created": [[h, v, _real_case(h, v, s), n] for h, v, s, n in new_values],
        "values_changed": [[h, v, _real_case(h, v, s), n] for h, v, s, n in changed_values],
    }


def _disk_case(p: str) -> str:
    try:
        import win32api
        long_path = win32api.GetLongPathName(win32api.GetShortPathName(p))
        return long_path[0].upper() + long_path[1:]
    except Exception:
        return os.path.normpath(p)


# ---------------------------------------------------------------- trace session


class TraceSession:
    """start() -> run installer -> stop() -> TraceLog dict."""

    def __init__(self, installer: str | None, name: str = ""):
        self.installer = installer
        self.name = name
        self.before: dict | None = None
        self.proc: subprocess.Popen | None = None

    def start(self, progress: Callable[[str], None] = lambda s: None, launch: bool = True) -> None:
        self.before = snapshot(progress)
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(PENDING, "wb") as f:
            pickle.dump({"installer": self.installer, "name": self.name, "before": self.before}, f)
        if launch and self.installer:
            progress("Starting installer...")
            if self.installer.lower().endswith(".msi"):
                self.proc = subprocess.Popen(["msiexec.exe", "/i", self.installer])
            else:
                os.startfile(self.installer)

    @classmethod
    def resume_pending(cls) -> "TraceSession | None":
        """A trace interrupted by a reboot can be finished after logon."""
        try:
            with open(PENDING, "rb") as f:
                d = pickle.load(f)
        except (OSError, pickle.UnpicklingError, EOFError):
            return None
        s = cls(d["installer"], d["name"])
        s.before = d["before"]
        return s

    def stop(self, name: str, progress: Callable[[str], None] = lambda s: None) -> dict:
        assert self.before is not None
        after = snapshot(progress)
        progress("Comparing snapshots...")
        changes = diff(self.before, after)
        uninstall_keys = []
        for h, v, sub in changes["keys_created"]:
            if sub.lower().startswith("software\\microsoft\\windows\\currentversion\\uninstall\\"):
                uninstall_keys.append(sub.split("\\")[-1])
        log = {
            "id": uuid.uuid4().hex[:12], "name": name or self.name or "Traced program",
            "created": dt.datetime.now().isoformat(timespec="seconds"), "installer": self.installer,
            "windows": f"{sys.getwindowsversion().major}.{sys.getwindowsversion().build}",
            "uninstall_keys": uninstall_keys, "author": os.environ.get("USERNAME", ""), "comment": "",
            **changes,
        }
        save_log(log)
        try:
            os.remove(PENDING)
        except OSError:
            pass
        return log


# ---------------------------------------------------------------- log management


def save_log(log: dict) -> None:
    os.makedirs(LOGS_DIR, exist_ok=True)
    with open(os.path.join(LOGS_DIR, log["id"] + ".json"), "w", encoding="utf-8") as f:
        json.dump(log, f, indent=1)


def list_logs() -> list[dict]:
    out = []
    if os.path.isdir(LOGS_DIR):
        for fn in os.listdir(LOGS_DIR):
            try:
                with open(os.path.join(LOGS_DIR, fn), encoding="utf-8") as f:
                    out.append(json.load(f))
            except (OSError, ValueError):
                pass
    out.sort(key=lambda l: l["name"].lower())
    return out


def delete_log(log_id: str) -> None:
    try:
        os.remove(os.path.join(LOGS_DIR, log_id + ".json"))
    except OSError:
        pass


def rename_log(log: dict, name: str) -> None:
    log["name"] = name
    save_log(log)


def export_log(log: dict, path: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"format": "openuninstaller-trace", "version": 1, **log}, f, indent=1)


def import_log(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        log = json.load(f)
    log.pop("format", None)
    log.pop("version", None)
    log["id"] = uuid.uuid4().hex[:12]
    save_log(log)
    return log


def merge_logs(logs: list[dict]) -> dict:
    """Merge newer logs into the oldest one; the newer logs are deleted."""
    logs = sorted(logs, key=lambda l: l["created"])
    base = logs[0]
    for other in logs[1:]:
        for k in ("dirs_created", "files_created", "files_modified", "keys_created", "values_created",
                  "values_changed", "uninstall_keys"):
            seen = {json.dumps(x) for x in base.get(k, [])}
            for x in other.get(k, []):
                if json.dumps(x) not in seen:
                    base.setdefault(k, []).append(x)
        delete_log(other["id"])
    save_log(base)
    return base


def log_for_program(program) -> dict | None:
    for log in list_logs():
        if program.key_name in log.get("uninstall_keys", []):
            return log
    return None


def log_items(log: dict) -> list[Leftover]:
    """Turn a trace log into Leftover items (only what still exists; all marked 'created')."""
    from .leftovers import is_excluded_key, is_protected_path
    items: list[Leftover] = []
    for hive, view, sub in log.get("keys_created", []):
        if wu.key_exists(hive, sub, view):
            p = wu.wow_display(hive, sub, view)
            items.append(Leftover("regkey", p, "Created during install", True, is_excluded_key(p),
                                  hive=hive, sub=sub, view=view))
    for hive, view, sub, name in log.get("values_created", []):
        if wu.get_value(hive, sub, name, view) is not None:
            items.append(Leftover("regvalue", wu.wow_display(hive, sub, view), "Value created during install",
                                  True, hive=hive, sub=sub, view=view, value_name=name))
    for p in log.get("dirs_created", []):
        if os.path.isdir(p):
            items.append(Leftover("folder", p, "Folder created during install", True, is_protected_path(p),
                                  size=wu.dir_size(p)))
    for p in log.get("files_created", []):
        if os.path.isfile(p):
            items.append(Leftover("file", p, "File created during install", True, is_protected_path(p),
                                  size=os.path.getsize(p)))
    return items
