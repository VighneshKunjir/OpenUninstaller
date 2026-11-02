"""Persistent settings stored as JSON under %LOCALAPPDATA%\\OpenUninstaller."""

from __future__ import annotations

import json
import os
import threading

from . import APP_NAME

DATA_DIR = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), APP_NAME)
SETTINGS_FILE = os.path.join(DATA_DIR, "settings.json")

# Registry keys that are never offered as leftovers (wildcards ? and * allowed;
# a trailing "\\*" also protects every sub key).
DEFAULT_REG_EXCLUDES = [
    r"HKEY_LOCAL_MACHINE\SOFTWARE",
    r"HKEY_LOCAL_MACHINE\SOFTWARE\Classes",
    r"HKEY_LOCAL_MACHINE\SOFTWARE\Classes\CLSID",
    r"HKEY_LOCAL_MACHINE\SOFTWARE\Classes\Installer",
    r"HKEY_LOCAL_MACHINE\SOFTWARE\Clients",
    r"HKEY_LOCAL_MACHINE\SOFTWARE\Microsoft",
    r"HKEY_LOCAL_MACHINE\SOFTWARE\Microsoft\Windows",
    r"HKEY_LOCAL_MACHINE\SOFTWARE\Microsoft\Windows NT",
    r"HKEY_LOCAL_MACHINE\SOFTWARE\Microsoft\Windows\CurrentVersion",
    r"HKEY_LOCAL_MACHINE\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall",
    r"HKEY_LOCAL_MACHINE\SOFTWARE\Microsoft\Windows\CurrentVersion\Run",
    r"HKEY_LOCAL_MACHINE\SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths",
    r"HKEY_LOCAL_MACHINE\SOFTWARE\Policies",
    r"HKEY_LOCAL_MACHINE\SOFTWARE\RegisteredApplications",
    r"HKEY_LOCAL_MACHINE\SOFTWARE\WOW6432Node",
    r"HKEY_LOCAL_MACHINE\SOFTWARE\WOW6432Node\Microsoft",
    r"HKEY_LOCAL_MACHINE\SOFTWARE\WOW6432Node\Classes",
    r"HKEY_LOCAL_MACHINE\SOFTWARE\Microsoft\Windows\CurrentVersion\Installer",
    r"HKEY_LOCAL_MACHINE\SOFTWARE\Microsoft\Windows\CurrentVersion\Installer\UserData",
    r"HKEY_LOCAL_MACHINE\SOFTWARE\Microsoft\Windows\CurrentVersion\Installer\UserData\*\Products",
    r"HKEY_LOCAL_MACHINE\SOFTWARE\Microsoft\Windows\CurrentVersion\Installer\Folders",
    r"HKEY_LOCAL_MACHINE\SOFTWARE\Classes\Installer\Products",
    r"HKEY_LOCAL_MACHINE\SOFTWARE\Classes\Installer\Features",
    r"HKEY_LOCAL_MACHINE\SOFTWARE\Classes\Installer\Components",
    r"HKEY_LOCAL_MACHINE\SOFTWARE\Classes\Installer\Patches",
    r"HKEY_LOCAL_MACHINE\SOFTWARE\Classes\Installer\UpgradeCodes",
    r"HKEY_LOCAL_MACHINE\SYSTEM",
    r"HKEY_LOCAL_MACHINE\SYSTEM\CurrentControlSet",
    r"HKEY_LOCAL_MACHINE\SYSTEM\CurrentControlSet\Services",
    r"HKEY_LOCAL_MACHINE\SYSTEM\CurrentControlSet\Control\*",
    r"HKEY_LOCAL_MACHINE\SYSTEM\CurrentControlSet\Enum\*",
    r"HKEY_CURRENT_USER\Software",
    r"HKEY_CURRENT_USER\Software\Classes",
    r"HKEY_CURRENT_USER\Software\Microsoft",
    r"HKEY_CURRENT_USER\Software\Microsoft\Windows",
    r"HKEY_CURRENT_USER\Software\Microsoft\Windows\CurrentVersion",
    r"HKEY_CURRENT_USER\Software\Microsoft\Windows\CurrentVersion\Run",
    r"HKEY_CURRENT_USER\Software\Policies",
    r"HKEY_CURRENT_USER\Software\Microsoft\Windows\CurrentVersion\Explorer\*",
    r"HKEY_CLASSES_ROOT",
    r"HKEY_USERS\*\Software",
    r"HKEY_USERS\*\Software\Microsoft",
    r"HKEY_USERS\*\Software\Classes",
]

# Folder paths that are never offered for deletion (environment variables are expanded).
DEFAULT_FOLDER_EXCLUDES = [
    r"%SystemRoot%\*",
    r"%SystemDrive%\Users",
    r"%SystemDrive%\Users\*\AppData",
    r"%SystemDrive%\Users\*\AppData\Local",
    r"%SystemDrive%\Users\*\AppData\Roaming",
    r"%SystemDrive%\Users\*\AppData\LocalLow",
    r"%SystemDrive%\Users\*\Documents",
    r"%SystemDrive%\Users\*\Desktop",
    r"%ProgramFiles%",
    r"%ProgramFiles(x86)%",
    r"%CommonProgramFiles%",
    r"%CommonProgramFiles(x86)%",
    r"%ProgramData%",
    r"%ProgramData%\Microsoft",
    r"%APPDATA%\Microsoft",
    r"%LOCALAPPDATA%\Microsoft",
    r"%LOCALAPPDATA%\Packages",
    r"%LOCALAPPDATA%\Programs",
    r"%LOCALAPPDATA%\Temp",
    r"%APPDATA%\Microsoft\Windows\Start Menu\Programs",
    r"%ProgramData%\Microsoft\Windows\Start Menu\Programs",
    r"%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup",
    r"%ProgramFiles%\WindowsApps\*",
    r"%ProgramFiles%\Windows Defender\*",
    r"%ProgramFiles%\Common Files\microsoft shared\*",
]

DEFAULT_JUNK_PATTERNS = {
    "*.tmp": "Temporary file", "*.temp": "Temporary file", "~*.*": "Temporary file",
    "*.~*": "Temporary file", "*.$$$": "Temporary file", "*.---": "Temporary file",
    "*._mp": "Temporary file", "*.old": "Old file", "*.bak": "Backup file",
    "*.chk": "Chkdsk fragment", "*.gid": "Windows help index", "*.dmp": "Memory dump",
    "*.err": "Error log", "*.log": "Log file", "*.wbk": "Word backup",
    "*.prv": "Old file", "*.fts": "Help search index", "*.ftg": "Help search index",
    "thumbs.db": "Thumbnail cache", "*.nch": "Outlook Express temp",
}

DEFAULT_JUNK_EXCLUDES = [r"%SystemRoot%\WinSxS\*", r"%SystemRoot%\System32\*", r"%SystemRoot%\Installer\*",
                         r"*\$Recycle.Bin\*", r"*\System Volume Information\*", r"%ProgramFiles%\WindowsApps\*"]

DEFAULTS = {
    "create_restore_point": True,
    "backup_registry_items": True,
    "full_registry_backup": False,
    "file_delete_mode": "recycle",          # recycle | backup | permanent
    "default_scan_mode": "moderate",        # safe | moderate | advanced
    "check_all_leftovers": False,
    "scan_all_users": False,
    "kill_running_exes": True,
    "show_system_components": False,
    "show_updates": False,
    "only_builtin_uninstaller": False,
    "auto_delete_leftovers": False,
    "open_wizard_maximized": False,
    # Phone Link / OneDrive / Dropbox... folders: scanning them talks to the device, deleting deletes there.
    "include_cloud_folders": False,
    "delete_log_after_uninstall": True,
    "new_program_days": 7,
    "reg_excludes": DEFAULT_REG_EXCLUDES,
    "folder_excludes": DEFAULT_FOLDER_EXCLUDES,
    "junk_patterns": {k: True for k in DEFAULT_JUNK_PATTERNS},
    "junk_excludes": DEFAULT_JUNK_EXCLUDES,
    "junk_includes": [],
    "junk_recycle": True,
    "junk_skip_recent": True,
    "hidden_programs": [],
    "program_comments": {},
    "program_groups": {},
    "groups": ["Internet", "Games", "Multimedia", "Utilities"],
    "custom_tools": [],
    "theme": "system",              # system | light | dark
    "trace_roots_extra": [],
}


class Settings:
    def __init__(self, path: str = SETTINGS_FILE):
        self.path = path
        self._lock = threading.Lock()
        self.data = dict(DEFAULTS)
        try:
            with open(path, encoding="utf-8") as f:
                self.data.update(json.load(f))
        except (OSError, ValueError):
            pass

    def __getitem__(self, key):
        return self.data.get(key, DEFAULTS.get(key))

    def __setitem__(self, key, value):
        self.data[key] = value
        self.save()

    def get(self, key, default=None):
        return self.data.get(key, DEFAULTS.get(key, default))

    def reset(self, key):
        self[key] = json.loads(json.dumps(DEFAULTS[key]))

    def save(self):
        with self._lock:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.data, f, indent=2)
            os.replace(tmp, self.path)


settings = Settings()


def data_path(*parts: str) -> str:
    p = os.path.join(DATA_DIR, *parts)
    os.makedirs(os.path.dirname(p) if os.path.splitext(p)[1] else p, exist_ok=True)
    return p
