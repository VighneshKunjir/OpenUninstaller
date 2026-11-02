"""Enumerate installed desktop programs from the registry Uninstall keys."""

from __future__ import annotations

import datetime as dt
import os
import re
import shlex
import winreg
from dataclasses import dataclass, field, asdict

from . import winutil as wu
from .config import settings

UNINSTALL_SUB = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"
GUID_RE = re.compile(r"^\{[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}\}$")
UPDATE_RE = re.compile(r"\bKB\d{6,}\b")

SOURCES = [
    (winreg.HKEY_LOCAL_MACHINE, UNINSTALL_SUB, wu.VIEW_64, "64-bit"),
    (winreg.HKEY_LOCAL_MACHINE, UNINSTALL_SUB, wu.VIEW_32, "32-bit"),
    (winreg.HKEY_CURRENT_USER, UNINSTALL_SUB, wu.VIEW_DEFAULT, "User"),
]


@dataclass
class Program:
    name: str
    key_name: str
    hive: int
    view: int
    scope: str                       # 64-bit / 32-bit / User
    version: str = ""
    publisher: str = ""
    install_location: str = ""
    install_source: str = ""
    uninstall_string: str = ""
    quiet_uninstall_string: str = ""
    modify_path: str = ""
    display_icon: str = ""
    install_date: str = ""           # YYYY-MM-DD
    size_bytes: int | None = None
    url: str = ""
    comments: str = ""
    is_msi: bool = False
    system_component: bool = False
    is_update: bool = False
    no_modify: bool = False
    no_repair: bool = False
    extra: dict = field(default_factory=dict)

    @property
    def reg_sub(self) -> str:
        return UNINSTALL_SUB + "\\" + self.key_name

    @property
    def reg_display(self) -> str:
        return wu.wow_display(self.hive, self.reg_sub, self.view)

    @property
    def uid(self) -> str:
        return f"{self.scope}|{self.key_name}"

    @property
    def product_code(self) -> str | None:
        return self.key_name.upper() if GUID_RE.match(self.key_name) else None

    def still_installed(self) -> bool:
        return wu.key_exists(self.hive, self.reg_sub, self.view)

    def to_dict(self) -> dict:
        return asdict(self)

    # ---- derived ------------------------------------------------------------

    def guess_install_dir(self) -> str:
        """InstallLocation, or the folder of DisplayIcon / the uninstaller exe when that is app-specific."""
        if self.install_location and os.path.isdir(_clean(self.install_location)):
            return _clean(self.install_location)
        for candidate in (self.display_icon.split(",")[0], exe_from_command(self.uninstall_string)):
            if not candidate:
                continue
            path = _clean(candidate)
            folder = os.path.dirname(path)
            name = os.path.basename(path).lower()
            if not folder or name in ("msiexec.exe", "rundll32.exe", "cmd.exe"):
                continue
            if is_generic_folder(folder):
                continue
            # Uninstallers kept in caches (Package Cache, Installer) are not the program folder
            low = folder.lower()
            if "package cache" in low or "\\installer" in low or "\\temp" in low:
                continue
            if os.path.isdir(folder):
                return folder
        return _clean(self.install_location) if self.install_location else ""


def _clean(path: str) -> str:
    return os.path.normpath(os.path.expandvars(path.strip().strip('"')))


def is_generic_folder(folder: str) -> bool:
    from .leftovers import is_protected_path  # local import to avoid a cycle
    return is_protected_path(folder)


def exe_from_command(cmd: str) -> str:
    """Pull the executable path out of an UninstallString (handles unquoted paths with spaces)."""
    cmd = (cmd or "").strip()
    if not cmd:
        return ""
    if cmd.startswith('"'):
        end = cmd.find('"', 1)
        return cmd[1:end] if end > 0 else cmd.strip('"')
    expanded = os.path.expandvars(cmd)
    low = expanded.lower()
    pos = 0
    while True:
        idx = low.find(".exe", pos)
        if idx < 0:
            break
        candidate = expanded[: idx + 4]
        if os.path.isfile(candidate) or " " not in candidate:
            return candidate
        pos = idx + 4
    try:
        return shlex.split(expanded, posix=False)[0]
    except ValueError:
        return expanded.split(" ")[0]


def _parse_date(raw) -> str:
    raw = str(raw or "").strip()
    for fmt in ("%Y%m%d", "%m/%d/%Y", "%d/%m/%Y", "%Y-%m-%d", "%d.%m.%Y"):
        try:
            return dt.datetime.strptime(raw, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return ""


def _key_write_date(hive: int, sub: str, view: int) -> str:
    try:
        with wu.open_key(hive, sub, view) as k:
            ts = winreg.QueryInfoKey(k)[2]  # 100ns since 1601
        return (dt.datetime(1601, 1, 1) + dt.timedelta(microseconds=ts // 10)).strftime("%Y-%m-%d")
    except OSError:
        return ""


def _read_program(hive: int, view: int, scope: str, key_name: str) -> Program | None:
    sub = UNINSTALL_SUB + "\\" + key_name
    vals = {n: v for n, v, _t in wu.values(hive, sub, view)}
    name = str(vals.get("DisplayName") or "").strip()
    if not name:
        return None
    size_kb = vals.get("EstimatedSize")
    p = Program(
        name=name, key_name=key_name, hive=hive, view=view, scope=scope,
        version=str(vals.get("DisplayVersion") or ""),
        publisher=str(vals.get("Publisher") or "").strip(),
        install_location=str(vals.get("InstallLocation") or "").strip().strip('"'),
        install_source=str(vals.get("InstallSource") or ""),
        uninstall_string=str(vals.get("UninstallString") or "").strip(),
        quiet_uninstall_string=str(vals.get("QuietUninstallString") or "").strip(),
        modify_path=str(vals.get("ModifyPath") or ""),
        display_icon=str(vals.get("DisplayIcon") or "").strip().strip('"'),
        install_date=_parse_date(vals.get("InstallDate")) or _key_write_date(hive, sub, view),
        size_bytes=int(size_kb) * 1024 if isinstance(size_kb, int) and size_kb > 0 else None,
        url=str(vals.get("URLInfoAbout") or vals.get("HelpLink") or ""),
        comments=str(vals.get("Comments") or ""),
        is_msi=vals.get("WindowsInstaller") == 1 or (bool(GUID_RE.match(key_name)) and
                                                       "msiexec" in str(vals.get("UninstallString", "")).lower()),
        system_component=vals.get("SystemComponent") == 1,
        is_update=bool(vals.get("ParentKeyName") or vals.get("ParentDisplayName")) or
        str(vals.get("ReleaseType", "")).lower() in ("update", "hotfix", "security update", "service pack") or
        bool(UPDATE_RE.search(key_name)),
        no_modify=vals.get("NoModify") == 1,
        no_repair=vals.get("NoRepair") == 1,
    )
    p.display_icon = p.display_icon.split(",")[0].strip('"') if p.display_icon else ""
    return p


def list_programs(include_components: bool | None = None, include_updates: bool | None = None) -> list[Program]:
    include_components = settings["show_system_components"] if include_components is None else include_components
    include_updates = settings["show_updates"] if include_updates is None else include_updates
    seen: set[tuple[str, str]] = set()
    out: list[Program] = []
    hidden = set(settings["hidden_programs"])
    for hive, sub, view, scope in SOURCES:
        for key_name in wu.subkeys(hive, sub, view):
            p = _read_program(hive, view, scope, key_name)
            if p is None:
                continue
            if p.is_update and not include_updates:
                continue
            if p.system_component and not include_components:
                continue
            if not (p.uninstall_string or p.is_msi) and not include_components:
                continue
            ident = (p.name.lower(), p.version.lower())
            if ident in seen:
                continue
            seen.add(ident)
            if p.uid in hidden:
                p.extra["hidden"] = True
            out.append(p)
    out.sort(key=lambda x: x.name.lower())
    return out


def compute_size(p: Program) -> int | None:
    d = p.guess_install_dir()
    if d and os.path.isdir(d) and not is_generic_folder(d):
        return wu.dir_size(d)
    return p.size_bytes


def is_new(p: Program, days: int | None = None) -> bool:
    days = settings["new_program_days"] if days is None else days
    if not p.install_date:
        return False
    try:
        d = dt.datetime.strptime(p.install_date, "%Y-%m-%d")
    except ValueError:
        return False
    return (dt.datetime.now() - d).days <= days


# ---------------------------------------------------------------- uninstall commands

def uninstall_command(p: Program, quiet: bool = False, forced_msi: bool = False) -> str:
    """Build the command line that runs a program's own uninstaller."""
    code = p.product_code
    if code and (p.is_msi or forced_msi):
        return f"msiexec.exe /x {code}" + (" /qb- REBOOT=ReallySuppress" if quiet else "")
    if quiet and p.quiet_uninstall_string:
        return p.quiet_uninstall_string
    cmd = p.uninstall_string
    low = cmd.lower()
    if "msiexec" in low:
        # Many MSI entries say /I{GUID} (which opens the repair UI). Force removal.
        cmd = re.sub(r"(?i)/i\s*\{", "/X{", cmd)
        if quiet and "/q" not in low:
            cmd += " /qb- REBOOT=ReallySuppress"
        return cmd
    if quiet:
        cmd += " " + silent_switches(cmd)
    return cmd.strip()


def silent_switches(cmd: str) -> str:
    """Best-guess silent flags for the common installer engines."""
    exe = os.path.basename(exe_from_command(cmd)).lower()
    if re.match(r"unins\d{3}\.exe", exe):            # Inno Setup
        return "/VERYSILENT /SUPPRESSMSGBOXES /NORESTART"
    if exe in ("uninstall.exe", "uninst.exe", "uninstaller.exe") or exe.startswith("un_"):
        return "/S"                                   # NSIS convention
    if "setup.exe" in exe and "installshield" in cmd.lower():
        return "-s"
    return "/S"


def modify_command(p: Program, repair: bool = False) -> str | None:
    code = p.product_code
    if code and p.is_msi:
        return f"msiexec.exe {'/fa' if repair else '/i'} {code}"
    if p.modify_path and not repair:
        return p.modify_path
    return None


def find_by_location(path: str) -> list[Program]:
    """Programs whose install folder contains the given path (used by Forced Uninstall / Hunter)."""
    path = wu.norm_path(path)
    found = []
    for p in list_programs(include_components=True):
        d = p.guess_install_dir()
        if d and not is_generic_folder(d) and (wu.is_under(path, d) or wu.is_under(d, path)):
            found.append(p)
    return found


def find_by_name(name: str) -> list[Program]:
    name = name.lower().strip()
    return [p for p in list_programs(include_components=True) if name and name in p.name.lower()]


def export_list(programs: list[Program], path: str, fmt: str) -> None:
    import csv
    import html
    import json
    cols = ["name", "version", "publisher", "install_date", "size_bytes", "install_location", "scope",
            "uninstall_string"]
    rows = [{c: getattr(p, c) for c in cols} for p in programs]
    if fmt == "csv":
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=cols)
            w.writeheader()
            w.writerows(rows)
    elif fmt == "json":
        with open(path, "w", encoding="utf-8") as f:
            json.dump(rows, f, indent=2)
    elif fmt == "html":
        with open(path, "w", encoding="utf-8") as f:
            f.write("<!doctype html><meta charset=utf-8><title>Installed programs</title>"
                    "<style>body{font-family:Segoe UI,sans-serif}td,th{border:1px solid #ccc;padding:4px}"
                    "table{border-collapse:collapse}</style><table><tr>")
            f.write("".join(f"<th>{c}</th>" for c in cols) + "</tr>")
            for r in rows:
                f.write("<tr>" + "".join(f"<td>{html.escape(str(r[c] or ''))}</td>" for c in cols) + "</tr>")
            f.write("</table>")
    else:
        with open(path, "w", encoding="utf-8") as f:
            for r in rows:
                f.write(" | ".join(str(r[c] or "") for c in cols) + "\n")
