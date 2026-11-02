"""Autorun Manager: Run/RunOnce keys, Startup folders, auto-start services and logon/boot tasks."""

from __future__ import annotations

import os
import re
import struct
import subprocess
import time
import winreg
from dataclasses import dataclass, field

import psutil

from . import winutil as wu
from .leftovers import Leftover
from .programs import exe_from_command

RUN_BASE = r"SOFTWARE\Microsoft\Windows\CurrentVersion"
APPROVED = r"Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved"


@dataclass
class AutorunItem:
    name: str
    command: str
    kind: str                # registry | folder | service | task
    location: str            # human readable
    enabled: bool = True
    publisher: str = ""
    description: str = ""
    exe: str = ""
    extra: dict = field(default_factory=dict)

    @property
    def valid(self) -> bool:
        return bool(self.exe) and os.path.exists(self.exe)

    @property
    def running(self) -> bool:
        return bool(self.exe) and wu.norm_path(self.exe) in _running_exes()


_running_cache: tuple[float, set[str]] = (0.0, set())


def _running_exes() -> set[str]:
    global _running_cache
    if time.time() - _running_cache[0] > 3:
        exes = set()
        for p in psutil.process_iter(["exe"]):
            if p.info["exe"]:
                exes.add(wu.norm_path(p.info["exe"]))
        _running_cache = (time.time(), exes)
    return _running_cache[1]


def _resolve_exe(cmd: str) -> str:
    exe = exe_from_command(cmd)
    base = os.path.basename(exe).lower()
    if base in ("rundll32.exe", "rundll32"):
        m = re.search(r'rundll32(?:\.exe)?"?\s+"?([^",]+)', cmd, re.I)
        exe = m.group(1) if m else exe
    exe = wu.norm_path(exe)
    if exe and not os.path.isabs(exe):
        found = subprocess.run(["where", exe], capture_output=True, text=True,
                               creationflags=wu.CREATE_NO_WINDOW).stdout.splitlines()
        exe = found[0] if found else exe
    return exe


def _approved_state(hive: int, leaf: str, name: str) -> bool:
    data = wu.get_value(hive, APPROVED + "\\" + leaf, name)
    if isinstance(data, bytes) and data:
        return data[0] % 2 == 0      # 0x02/0x06 enabled, 0x03/0x07 disabled
    return True


def _set_approved(hive: int, leaf: str, name: str, enabled: bool) -> None:
    if enabled:
        blob = bytes([2]) + bytes(11)
    else:
        ft = int((time.time() + 11644473600) * 10_000_000)
        blob = bytes([3, 0, 0, 0]) + struct.pack("<Q", ft)
    wu.set_value(hive, APPROVED + "\\" + leaf, name, winreg.REG_BINARY, blob)


def _fill_meta(item: AutorunItem) -> AutorunItem:
    item.exe = item.exe or _resolve_exe(item.command)
    if item.exe and os.path.isfile(item.exe):
        info = wu.file_version_info(item.exe)
        item.publisher = info.get("CompanyName", "")
        item.description = info.get("FileDescription", "")
    return item


def _registry_items() -> list[AutorunItem]:
    out = []
    locs = [(winreg.HKEY_CURRENT_USER, 0, "Run", "HKCU"),
            (winreg.HKEY_LOCAL_MACHINE, wu.VIEW_64, "Run", "HKLM"),
            (winreg.HKEY_LOCAL_MACHINE, wu.VIEW_32, "Run32", "HKLM (32-bit)")]
    for hive, view, approved_leaf, label in locs:
        for leaf in ("Run", "RunOnce"):
            sub = RUN_BASE + "\\" + leaf
            for name, data, _t in wu.values(hive, sub, view):
                if not name:
                    continue
                enabled = _approved_state(hive, approved_leaf, name) if leaf == "Run" else True
                out.append(_fill_meta(AutorunItem(
                    name, str(data), "registry", f"{label}\\{leaf}", enabled,
                    extra={"hive": hive, "sub": sub, "view": view, "approved": approved_leaf})))
    return out


def _folder_items() -> list[AutorunItem]:
    kf = wu.known_folders()
    out = []
    for key, hive in (("startup", winreg.HKEY_CURRENT_USER), ("common_startup", winreg.HKEY_LOCAL_MACHINE)):
        folder = kf.get(key)
        if not folder or not os.path.isdir(folder):
            continue
        for f in os.listdir(folder):
            if f.lower() == "desktop.ini":
                continue
            full = os.path.join(folder, f)
            target = wu.resolve_shortcut(full) if f.lower().endswith(".lnk") else full
            out.append(_fill_meta(AutorunItem(
                os.path.splitext(f)[0], target or full, "folder", "Startup folder" +
                (" (all users)" if key == "common_startup" else ""),
                _approved_state(hive, "StartupFolder", f), exe=wu.norm_path(target) if target else "",
                extra={"file": full, "hive": hive})))
    return out


def _service_items(include_microsoft: bool) -> list[AutorunItem]:
    base = r"SYSTEM\CurrentControlSet\Services"
    out = []
    for svc in wu.subkeys(winreg.HKEY_LOCAL_MACHINE, base):
        sub = base + "\\" + svc
        vals = {n: v for n, v, _t in wu.values(winreg.HKEY_LOCAL_MACHINE, sub)}
        stype = vals.get("Type", 0)
        if not isinstance(stype, int) or not stype & 0x30:         # Win32 services only, no drivers
            continue
        start = vals.get("Start")
        if start not in (2, 4) or "ImagePath" not in vals:
            continue
        disabled_by_us = start == 4 and vals.get("OpenUninstallerPrevStart") is not None
        if start == 4 and not disabled_by_us:
            continue
        img = str(vals["ImagePath"])
        item = _fill_meta(AutorunItem(str(vals.get("DisplayName") or svc), img, "service", "Services",
                                      start == 2, extra={"service": svc, "sub": sub}))
        if item.name.startswith("@"):        # unresolved resource string like @%SystemRoot%\x.dll,-101
            item.name = svc
        if not include_microsoft and (item.publisher.startswith("Microsoft") or "svchost.exe" in img.lower()):
            continue
        out.append(item)
    return out


def _task_items(include_microsoft: bool) -> list[AutorunItem]:
    tasks_dir = wu.known_folders().get("tasks", "")
    out = []
    for root, _dirs, files in os.walk(tasks_dir):
        for f in files:
            full = os.path.join(root, f)
            rel = "\\" + os.path.relpath(full, tasks_dir)
            if not include_microsoft and rel.lower().startswith("\\microsoft\\"):
                continue
            try:
                raw = open(full, "rb").read(200_000)
            except OSError:
                continue
            text = raw.decode("utf-16", "ignore") if raw[:2] in (b"\xff\xfe", b"\xfe\xff") else raw.decode("utf-8", "ignore")
            if not re.search(r"<(LogonTrigger|BootTrigger)\b", text):
                continue
            cmd = (re.findall(r"<Command>(.*?)</Command>", text, re.S) or [""])[0].strip()
            args = (re.findall(r"<Arguments>(.*?)</Arguments>", text, re.S) or [""])[0].strip()
            settings_block = text.split("<Settings>", 1)[-1]
            enabled = not re.search(r"<Enabled>\s*false\s*</Enabled>", settings_block.split("</Settings>")[0], re.I)
            item = _fill_meta(AutorunItem(f, (f'"{cmd}" ' + args).strip() if cmd else "(COM handler)", "task",
                                          "Task Scheduler", enabled, exe=wu.norm_path(cmd) if cmd else "",
                                          extra={"task": rel}))
            out.append(item)
    return out


def list_autoruns(include_services: bool = True, include_tasks: bool = True,
                  include_microsoft: bool = False) -> list[AutorunItem]:
    items = _registry_items() + _folder_items()
    if include_services:
        items += _service_items(include_microsoft)
    if include_tasks:
        items += _task_items(include_microsoft)
    return items


def set_enabled(item: AutorunItem, enabled: bool) -> tuple[bool, str]:
    try:
        if item.kind == "registry":
            if item.extra["sub"].endswith("RunOnce"):
                return False, "RunOnce entries cannot be disabled, only removed."
            _set_approved(item.extra["hive"], item.extra["approved"], item.name, enabled)
        elif item.kind == "folder":
            _set_approved(item.extra["hive"], "StartupFolder", os.path.basename(item.extra["file"]), enabled)
        elif item.kind == "service":
            sub = item.extra["sub"]
            hk = winreg.HKEY_LOCAL_MACHINE
            if enabled:
                prev = wu.get_value(hk, sub, "OpenUninstallerPrevStart", default=2)
                wu.set_value(hk, sub, "Start", winreg.REG_DWORD, int(prev))
                wu.delete_value(hk, sub, "OpenUninstallerPrevStart")
            else:
                wu.set_value(hk, sub, "OpenUninstallerPrevStart", winreg.REG_DWORD, 2)
                wu.set_value(hk, sub, "Start", winreg.REG_DWORD, 4)
        elif item.kind == "task":
            r = wu.run_hidden(["schtasks.exe", "/change", "/tn", item.extra["task"],
                               "/enable" if enabled else "/disable"])
            if r.returncode:
                return False, (r.stderr or r.stdout).strip()
        item.enabled = enabled
        return True, ""
    except OSError as e:
        return False, str(e)


def as_leftover(item: AutorunItem) -> Leftover:
    """Map an autorun entry onto the deletion engine so removals are backed up like leftovers."""
    if item.kind == "registry":
        return Leftover("regvalue", wu.wow_display(item.extra["hive"], item.extra["sub"], item.extra["view"]),
                        "Autorun entry", hive=item.extra["hive"], sub=item.extra["sub"], view=item.extra["view"],
                        value_name=item.name)
    if item.kind == "folder":
        return Leftover("file", item.extra["file"], "Startup folder entry")
    if item.kind == "service":
        return Leftover("service", item.extra["service"], "Autorun service", hive=winreg.HKEY_LOCAL_MACHINE,
                        sub=item.extra["sub"])
    return Leftover("task", item.extra["task"], "Autorun task")


def remove(items: list[AutorunItem]):
    from .backup import delete_items
    return delete_items([as_leftover(i) for i in items], "Autorun Manager", "Autorun entries",
                        file_mode="backup")


def add(name: str, command: str, all_users: bool, where: str) -> None:
    """where: run | runonce | folder"""
    if where == "folder":
        kf = wu.known_folders()
        folder = kf["common_startup" if all_users else "startup"]
        exe = exe_from_command(command)
        args = command[len(exe) + 2:].strip() if command.startswith('"') else command[len(exe):].strip()
        wu.create_shortcut(os.path.join(folder, name + ".lnk"), exe, args)
        return
    hive = winreg.HKEY_LOCAL_MACHINE if all_users else winreg.HKEY_CURRENT_USER
    leaf = "RunOnce" if where == "runonce" else "Run"
    wu.set_value(hive, RUN_BASE + "\\" + leaf, name, winreg.REG_SZ, command,
                 wu.VIEW_64 if all_users else 0)


def run(item: AutorunItem) -> None:
    subprocess.Popen(item.command if item.kind != "folder" else item.extra["file"], shell=True)


def kill(item: AutorunItem) -> int:
    n = 0
    target = wu.norm_path(item.exe)
    for p in psutil.process_iter(["exe"]):
        if p.info["exe"] and wu.norm_path(p.info["exe"]) == target:
            try:
                p.kill()
                n += 1
            except psutil.Error:
                pass
    return n
