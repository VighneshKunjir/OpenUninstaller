"""Low-level Windows helpers: elevation, registry access, known folders, processes."""

from __future__ import annotations

import ctypes
import os
import subprocess
import sys
import winreg
from ctypes import wintypes
from typing import Iterator

CREATE_NO_WINDOW = 0x08000000

# ---------------------------------------------------------------- elevation


def is_frozen() -> bool:
    """True when running from the packaged OpenUninstaller.exe (PyInstaller)."""
    return bool(getattr(sys, "frozen", False))


def self_command() -> list[str]:
    """How to start this app again: the .exe when packaged, else pythonw + the launcher script."""
    if is_frozen():
        return [sys.executable]
    pyw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    launcher = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "OpenUninstaller.pyw")
    return [pyw if os.path.exists(pyw) else sys.executable, launcher]


def is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except OSError:
        return False


def relaunch_as_admin(argv: list[str] | None = None) -> bool:
    """Re-run the current interpreter elevated. Returns True if the UAC prompt was accepted."""
    argv = argv if argv is not None else sys.argv
    params = subprocess.list2cmdline(argv)
    exe = sys.executable
    pyw = os.path.join(os.path.dirname(exe), "pythonw.exe")
    if not is_frozen() and os.path.exists(pyw):
        exe = pyw
    rc = ctypes.windll.shell32.ShellExecuteW(None, "runas", exe, params, None, 1)
    return rc > 32


def run_hidden(cmd, timeout: float | None = None, check: bool = False) -> subprocess.CompletedProcess:
    """Run a console command without flashing a window; output is captured as text."""
    return subprocess.run(
        cmd, capture_output=True, text=True, errors="replace", timeout=timeout,
        creationflags=CREATE_NO_WINDOW, check=check,
        shell=isinstance(cmd, str),
    )


def powershell(script: str, timeout: float | None = 300) -> subprocess.CompletedProcess:
    return run_hidden(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", script],
        timeout=timeout,
    )


# ---------------------------------------------------------------- registry

HIVES = {
    "HKEY_LOCAL_MACHINE": winreg.HKEY_LOCAL_MACHINE,
    "HKEY_CURRENT_USER": winreg.HKEY_CURRENT_USER,
    "HKEY_CLASSES_ROOT": winreg.HKEY_CLASSES_ROOT,
    "HKEY_USERS": winreg.HKEY_USERS,
    "HKEY_CURRENT_CONFIG": winreg.HKEY_CURRENT_CONFIG,
}
HIVE_ALIASES = {"HKLM": "HKEY_LOCAL_MACHINE", "HKCU": "HKEY_CURRENT_USER", "HKCR": "HKEY_CLASSES_ROOT",
                "HKU": "HKEY_USERS", "HKCC": "HKEY_CURRENT_CONFIG"}
HIVE_NAMES = {v: k for k, v in HIVES.items()}

VIEW_64 = winreg.KEY_WOW64_64KEY
VIEW_32 = winreg.KEY_WOW64_32KEY
VIEW_DEFAULT = 0

REG_TYPE_NAMES = {
    winreg.REG_SZ: "REG_SZ", winreg.REG_EXPAND_SZ: "REG_EXPAND_SZ", winreg.REG_BINARY: "REG_BINARY",
    winreg.REG_DWORD: "REG_DWORD", winreg.REG_MULTI_SZ: "REG_MULTI_SZ", winreg.REG_QWORD: "REG_QWORD",
    winreg.REG_NONE: "REG_NONE",
}


def split_reg_path(full: str) -> tuple[int, str]:
    """'HKEY_LOCAL_MACHINE\\SOFTWARE\\X' -> (HKEY_LOCAL_MACHINE, 'SOFTWARE\\X')."""
    head, _, rest = full.partition("\\")
    head = HIVE_ALIASES.get(head.upper(), head.upper())
    return HIVES[head], rest


def join_reg_path(hive: int, sub: str) -> str:
    return HIVE_NAMES[hive] + ("\\" + sub if sub else "")


def wow_display(hive: int, sub: str, view: int) -> str:
    """Human-facing path: show the 32-bit view as the real WOW6432Node location."""
    if view == VIEW_32 and hive == winreg.HKEY_LOCAL_MACHINE and sub.lower().startswith("software\\") \
            and not sub.lower().startswith("software\\wow6432node"):
        sub = "SOFTWARE\\WOW6432Node\\" + sub[len("software\\"):]
    return join_reg_path(hive, sub)


def open_key(hive: int, sub: str, view: int = VIEW_DEFAULT, write: bool = False):
    access = (winreg.KEY_ALL_ACCESS if write else winreg.KEY_READ) | view
    return winreg.OpenKey(hive, sub, 0, access)


def key_exists(hive: int, sub: str, view: int = VIEW_DEFAULT) -> bool:
    try:
        with open_key(hive, sub, view):
            return True
    except OSError:
        return False


def iter_subkeys(key) -> Iterator[str]:
    i = 0
    while True:
        try:
            yield winreg.EnumKey(key, i)
        except OSError:
            return
        i += 1


def iter_values(key) -> Iterator[tuple[str, object, int]]:
    i = 0
    while True:
        try:
            yield winreg.EnumValue(key, i)
        except OSError:
            return
        i += 1


def subkeys(hive: int, sub: str, view: int = VIEW_DEFAULT) -> list[str]:
    try:
        with open_key(hive, sub, view) as k:
            return list(iter_subkeys(k))
    except OSError:
        return []


def values(hive: int, sub: str, view: int = VIEW_DEFAULT) -> list[tuple[str, object, int]]:
    try:
        with open_key(hive, sub, view) as k:
            return list(iter_values(k))
    except OSError:
        return []


def get_value(hive: int, sub: str, name: str, view: int = VIEW_DEFAULT, default=None):
    try:
        with open_key(hive, sub, view) as k:
            return winreg.QueryValueEx(k, name)[0]
    except OSError:
        return default


def delete_key_tree(hive: int, sub: str, view: int = VIEW_DEFAULT) -> None:
    """Recursively delete a registry key (winreg can only delete leaf keys)."""
    with open_key(hive, sub, view, write=True) as k:
        for child in list(iter_subkeys(k)):
            delete_key_tree(hive, sub + "\\" + child, view)
    winreg.DeleteKeyEx(hive, sub, view, 0)


def delete_value(hive: int, sub: str, name: str, view: int = VIEW_DEFAULT) -> None:
    with open_key(hive, sub, view, write=True) as k:
        winreg.DeleteValue(k, name)


def set_value(hive: int, sub: str, name: str, vtype: int, data, view: int = VIEW_DEFAULT) -> None:
    with winreg.CreateKeyEx(hive, sub, 0, winreg.KEY_ALL_ACCESS | view) as k:
        winreg.SetValueEx(k, name, 0, vtype, data)


def reg_export(hive: int, sub: str, view: int, dest: str) -> bool:
    """Export a key with reg.exe (keeps every value type exactly). Returns success."""
    flag = {VIEW_64: "/reg:64", VIEW_32: "/reg:32"}.get(view)
    cmd = ["reg.exe", "export", join_reg_path(hive, sub), dest, "/y"] + ([flag] if flag else [])
    return run_hidden(cmd, timeout=600).returncode == 0


def reg_import(path: str, view: int = VIEW_DEFAULT) -> bool:
    flag = {VIEW_64: "/reg:64", VIEW_32: "/reg:32"}.get(view)
    cmd = ["reg.exe", "import", path] + ([flag] if flag else [])
    return run_hidden(cmd, timeout=600).returncode == 0


def open_in_regedit(full_path: str) -> None:
    """Jump regedit to a key by seeding its LastKey value, then launch it."""
    try:
        set_value(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Applets\Regedit",
                  "LastKey", winreg.REG_SZ, "Computer\\" + full_path)
    except OSError:
        pass
    subprocess.Popen(["regedit.exe", "/m"])


def user_hives() -> list[tuple[str, str]]:
    """(SID, profile path) for every real user profile on the machine."""
    out = []
    plist = r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\ProfileList"
    for sid in subkeys(winreg.HKEY_LOCAL_MACHINE, plist):
        if not sid.startswith("S-1-5-21-") or sid.endswith(".bak"):
            continue
        path = get_value(winreg.HKEY_LOCAL_MACHINE, plist + "\\" + sid, "ProfileImagePath")
        if path:
            out.append((sid, os.path.expandvars(path)))
    return out


def current_user_sid() -> str | None:
    r = run_hidden(["whoami", "/user", "/fo", "csv", "/nh"])
    parts = r.stdout.strip().split('","')
    return parts[-1].strip('"') if len(parts) > 1 else None


# ---------------------------------------------------------------- known folders

def env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


def known_folders() -> dict[str, str]:
    up = env("USERPROFILE")
    d = {
        "windows": env("SystemRoot", r"C:\Windows"),
        "program_files": env("ProgramW6432", env("ProgramFiles")),
        "program_files_x86": env("ProgramFiles(x86)"),
        "common_files": env("CommonProgramW6432", env("CommonProgramFiles")),
        "common_files_x86": env("CommonProgramFiles(x86)"),
        "program_data": env("ProgramData", r"C:\ProgramData"),
        "appdata": env("APPDATA"),
        "local_appdata": env("LOCALAPPDATA"),
        "local_low": os.path.join(up, "AppData", "LocalLow") if up else "",
        "local_programs": os.path.join(env("LOCALAPPDATA"), "Programs"),
        "temp": env("TEMP"),
        "user_profile": up,
        "public": env("PUBLIC", r"C:\Users\Public"),
        "documents": os.path.join(up, "Documents") if up else "",
        "desktop": os.path.join(up, "Desktop") if up else "",
        "public_desktop": os.path.join(env("PUBLIC", r"C:\Users\Public"), "Desktop"),
        "start_menu": os.path.join(env("APPDATA"), r"Microsoft\Windows\Start Menu\Programs"),
        "common_start_menu": os.path.join(env("ProgramData", r"C:\ProgramData"),
                                          r"Microsoft\Windows\Start Menu\Programs"),
        "startup": os.path.join(env("APPDATA"), r"Microsoft\Windows\Start Menu\Programs\Startup"),
        "common_startup": os.path.join(env("ProgramData", r"C:\ProgramData"),
                                       r"Microsoft\Windows\Start Menu\Programs\Startup"),
        "taskbar_pins": os.path.join(env("APPDATA"), r"Microsoft\Internet Explorer\Quick Launch\User Pinned\TaskBar"),
        "tasks": os.path.join(env("SystemRoot", r"C:\Windows"), "System32", "Tasks"),
    }
    return {k: v for k, v in d.items() if v}


def norm_path(p: str) -> str:
    return os.path.normcase(os.path.normpath(os.path.expandvars(p.strip().strip('"')))) if p else ""


def is_under(child: str, parent: str) -> bool:
    c, p = norm_path(child), norm_path(parent)
    return bool(p) and (c == p or c.startswith(p.rstrip("\\") + "\\"))


# ---------------------------------------------------------------- phone / cloud storage and links
#
# Phone Link ("CrossDevice"), OneDrive, Dropbox, iCloud... register *sync roots*: folders on a local drive
# whose content really lives on another device. Deleting there deletes on the phone / in the cloud,
# and merely listing them talks to that device. They are skipped unless the user opts in.

FILE_ATTRIBUTE_REPARSE_POINT = 0x400
FILE_ATTRIBUTE_OFFLINE = 0x1000
FILE_ATTRIBUTE_RECALL_ON_OPEN = 0x40000
FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS = 0x400000
CLOUD_ATTRS = FILE_ATTRIBUTE_OFFLINE | FILE_ATTRIBUTE_RECALL_ON_OPEN | FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS
IO_REPARSE_TAG_MOUNT_POINT = 0xA0000003   # junction
IO_REPARSE_TAG_SYMLINK = 0xA000000C
IO_REPARSE_TAG_CLOUD = 0x9000001A

_sync_roots_cache: list[tuple[str, str]] | None = None


def sync_roots(refresh: bool = False) -> list[tuple[str, str]]:
    """(path, display name) of every registered phone/cloud sync root, plus OneDrive folders."""
    global _sync_roots_cache
    if _sync_roots_cache is not None and not refresh:
        return _sync_roots_cache
    found: dict[str, str] = {}
    base = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer\SyncRootManager"
    for root_id in subkeys(winreg.HKEY_LOCAL_MACHINE, base):
        name = get_value(winreg.HKEY_LOCAL_MACHINE, base + "\\" + root_id, "DisplayNameResource") or root_id
        if str(name).startswith("@"):
            name = root_id.split("!")[0]
        for _vname, path, _t in values(winreg.HKEY_LOCAL_MACHINE, base + "\\" + root_id + r"\UserSyncRoots"):
            if path:
                found.setdefault(os.path.normpath(str(path)), str(name))
    for var in ("OneDrive", "OneDriveConsumer", "OneDriveCommercial"):
        if env(var):
            found.setdefault(os.path.normpath(env(var)), "OneDrive")
    crossdevice = os.path.join(env("USERPROFILE"), "CrossDevice")
    if os.path.isdir(crossdevice):
        found.setdefault(crossdevice, "Phone Link devices")
    _sync_roots_cache = sorted(found.items())
    return _sync_roots_cache


def is_cloud_path(path: str) -> bool:
    """True if the path is inside a phone/cloud sync root or is an online-only placeholder."""
    if not path:
        return False
    if any(is_under(path, root) for root, _n in sync_roots()):
        return True
    try:
        st = os.lstat(path)
    except OSError:
        return False
    return _cloud_stat(st)


def _cloud_stat(st) -> bool:
    attrs = getattr(st, "st_file_attributes", 0)
    tag = getattr(st, "st_reparse_tag", 0)
    # IO_REPARSE_TAG_CLOUD .. IO_REPARSE_TAG_CLOUD_F = 0x9000001A, 0x9000101A, ... 0x9000F01A
    return bool(attrs & CLOUD_ATTRS) or (bool(attrs & FILE_ATTRIBUTE_REPARSE_POINT)
                                         and (tag & 0xFFFF0FFF) == IO_REPARSE_TAG_CLOUD)


def _is_link_stat(st) -> bool:
    return bool(getattr(st, "st_file_attributes", 0) & FILE_ATTRIBUTE_REPARSE_POINT) and \
        getattr(st, "st_reparse_tag", 0) in (IO_REPARSE_TAG_MOUNT_POINT, IO_REPARSE_TAG_SYMLINK)


def entry_kind(entry: os.DirEntry) -> str:
    """'link' (junction/symlink), 'cloud' (phone/cloud storage) or 'normal'. Uses the cached scandir stat."""
    try:
        st = entry.stat(follow_symlinks=False)
    except OSError:
        return "normal"
    if _is_link_stat(st) or entry.is_symlink():
        return "link"
    if _cloud_stat(st) or (entry.is_dir(follow_symlinks=False)
                           and any(norm_path(entry.path) == norm_path(r) for r, _n in sync_roots())):
        return "cloud"
    return "normal"


def safe_walk(top: str, include_cloud: bool = False, on_skip=None):
    """os.walk replacement: never follows junctions/symlinks; skips phone/cloud storage unless included.

    on_skip(path, reason) is called for every folder that is not entered.
    """
    if not include_cloud and is_cloud_path(top):
        if on_skip:
            on_skip(top, "cloud")
        return
    stack = [top]
    while stack:
        d = stack.pop()
        try:
            with os.scandir(d) as it:
                entries = list(it)
        except OSError:
            continue
        dirs, files = [], []
        for e in entries:
            try:
                is_dir = e.is_dir(follow_symlinks=False)
            except OSError:
                continue
            kind = entry_kind(e)
            if is_dir:
                if kind == "link" or (kind == "cloud" and not include_cloud):
                    if on_skip:
                        on_skip(e.path, kind)
                    continue
                dirs.append(e.name)
            else:
                if kind == "cloud" and not include_cloud:
                    continue
                files.append(e.name)
        yield d, dirs, files
        # callers may prune `dirs` in place, like os.walk(topdown=True)
        stack.extend(os.path.join(d, n) for n in reversed(dirs))


def dir_size(path: str) -> int:
    total = 0
    for root, _dirs, files in safe_walk(path):
        for f in files:
            try:
                total += os.lstat(os.path.join(root, f)).st_size
            except OSError:
                pass
    return total


def human_size(n: float | None) -> str:
    if n is None:
        return ""
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return ""


def open_folder(path: str) -> None:
    if os.path.isfile(path):
        subprocess.Popen(["explorer.exe", "/select,", path])
    elif os.path.isdir(path):
        os.startfile(path)


def show_properties(path: str) -> None:
    """Open the Explorer Properties dialog for a file."""
    class SHELLEXECUTEINFO(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("fMask", ctypes.c_ulong), ("hwnd", wintypes.HWND),
                    ("lpVerb", wintypes.LPCWSTR), ("lpFile", wintypes.LPCWSTR),
                    ("lpParameters", wintypes.LPCWSTR), ("lpDirectory", wintypes.LPCWSTR),
                    ("nShow", ctypes.c_int), ("hInstApp", wintypes.HINSTANCE), ("lpIDList", ctypes.c_void_p),
                    ("lpClass", wintypes.LPCWSTR), ("hkeyClass", wintypes.HKEY), ("dwHotKey", wintypes.DWORD),
                    ("hIcon", wintypes.HANDLE), ("hProcess", wintypes.HANDLE)]
    sei = SHELLEXECUTEINFO()
    sei.cbSize = ctypes.sizeof(sei)
    sei.fMask = 0x0000000C  # SEE_MASK_INVOKEIDLIST
    sei.lpVerb = "properties"
    sei.lpFile = path
    sei.nShow = 1
    ctypes.windll.shell32.ShellExecuteExW(ctypes.byref(sei))


def delete_on_reboot(path: str) -> bool:
    """Schedule a locked file/empty folder for deletion at next boot (needs admin)."""
    MOVEFILE_DELAY_UNTIL_REBOOT = 0x4
    return bool(ctypes.windll.kernel32.MoveFileExW(path, None, MOVEFILE_DELAY_UNTIL_REBOOT))


def resolve_shortcut(lnk: str) -> str:
    """Return the target of a .lnk file ('' when it cannot be resolved)."""
    try:
        import pythoncom  # noqa: F401  (initialises COM for this thread)
        import win32com.client
        pythoncom.CoInitialize()
        shell = win32com.client.Dispatch("WScript.Shell")
        return shell.CreateShortCut(lnk).TargetPath or ""
    except Exception:
        return ""


def create_shortcut(lnk: str, target: str, args: str = "") -> None:
    import pythoncom
    import win32com.client
    pythoncom.CoInitialize()
    sc = win32com.client.Dispatch("WScript.Shell").CreateShortCut(lnk)
    sc.TargetPath = target
    sc.Arguments = args
    sc.WorkingDirectory = os.path.dirname(target)
    sc.save()


def file_version_info(path: str) -> dict[str, str]:
    """CompanyName / FileDescription / ProductName from an executable's version resource."""
    try:
        import win32api
        lang, cp = win32api.GetFileVersionInfo(path, "\\VarFileInfo\\Translation")[0]
        out = {}
        for field in ("CompanyName", "FileDescription", "ProductName", "FileVersion"):
            try:
                out[field] = win32api.GetFileVersionInfo(
                    path, f"\\StringFileInfo\\{lang:04X}{cp:04X}\\{field}") or ""
            except Exception:
                out[field] = ""
        return out
    except Exception:
        return {}
