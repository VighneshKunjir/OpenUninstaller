"""Leftover scanner: finds files, folders, registry keys/values, services and tasks left by a program.

Three intensity levels (each includes the previous one):

* safe      - exact matches only: the install folder, folders/keys named exactly like the program
              in the standard locations, the Uninstall key, shortcuts / Run entries / App Paths /
              services / scheduled tasks that point into the install folder.
* moderate  - adds vendor folders/keys that hold nothing but this program, partial name matches,
              firewall rules, SharedDLLs, MSI product registration, Temp and Documents.
* advanced  - adds a deep registry walk (COM classes, type libraries, ProgIDs, file associations,
              MUI cache, compatibility store) and a deeper folder walk.

Every item carries ``created`` (bold in the UI - we are confident the program made it) and
``excluded`` (on the exclude list / protected - never deleted).
"""

from __future__ import annotations

import fnmatch
import os
import re
import winreg
from dataclasses import dataclass, field
from typing import Callable, Iterable

from . import winutil as wu
from .config import settings

MODES = ("safe", "moderate", "advanced")

GENERIC_WORDS = {
    "microsoft", "windows", "update", "updates", "common", "system", "program", "programs", "files",
    "file", "tools", "tool", "software", "app", "apps", "application", "data", "the", "and", "for",
    "x64", "x86", "setup", "install", "installer", "driver", "drivers", "runtime", "service", "services",
    "client", "user", "users", "inc", "llc", "ltd", "corp", "corporation", "company", "group", "studio",
    "studios", "games", "game", "library", "libraries", "plugin", "plugins", "pro", "free", "edition",
    "version", "bit", "beta", "desktop", "launcher", "helper", "manager", "core", "plus", "suite", "online",
    "temp", "cache", "logs", "log", "config", "settings", "shared", "local", "roaming", "default", "public",
    "packages", "package", "classes", "clsid", "policies", "network", "internet", "security", "media",
    "player", "office", "home", "english", "portable", "lite", "standard", "professional", "enterprise",
    "components", "component", "tools", "support", "assistant", "agent", "framework", "sdk", "redistributable",
    "visual", "net", "dotnet", "java", "python", "node", "web", "browser", "cloud", "device", "devices", "audio",
}
PROTECTED_FOLDER_NAMES = {
    "microsoft", "windows", "common files", "temp", "tmp", "packages", "programs", "system32", "syswow64",
    "drivers", "users", "public", "default", "appdata", "local", "roaming", "locallow", "startup",
    "start menu", "desktop", "documents", "downloads", "pictures", "music", "videos", "program files",
    "program files (x86)", "programdata", "windowsapps", "installer", "package cache", "microsoft shared",
    "crashdumps", "d3dscache", "fonts", "assembly", "winsxs", "inf", "prefetch", "recent", "history",
}
GENERIC_INSTALL_LEAVES = {"application", "app", "bin", "current", "program", "x64", "x86", "win64", "win32",
                          "client", "binaries", "main"}
PUBLISHER_SUFFIXES = re.compile(
    r"[,.]?\s*\b(inc|incorporated|ltd|limited|llc|l\.l\.c|gmbh|ag|s\.?a\.?|b\.?v\.?|co|corp|corporation|"
    r"company|group|plc|pty|s\.r\.o|srl|oy|ab|as|kk|software|technologies|technology|labs|team)\b\.?",
    re.I)
NAME_NOISE = re.compile(
    r"\(.*?\)|\[.*?\]|\bv?\d+([._]\d+)+[a-z]?\b|\b(x64|x86|amd64|arm64|win64|win32|64[- ]?bit|32[- ]?bit)\b|"
    r"\b(version|update|build|release|setup|installer)\b|[®™©]|\s-\s.*$", re.I)


def norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def clean_name(name: str) -> str:
    out = NAME_NOISE.sub(" ", name or "")
    out = re.sub(r"\b\d{4}\b$", "", out.strip())  # trailing year is usually part of the name - keep core
    return re.sub(r"\s+", " ", out).strip(" -_.,")


def clean_publisher(pub: str) -> str:
    out = PUBLISHER_SUFFIXES.sub(" ", pub or "")
    return re.sub(r"\s+", " ", out).strip(" -_.,")


# ---------------------------------------------------------------- safety


def _known_roots() -> set[str]:
    return {wu.norm_path(v) for v in wu.known_folders().values()}


def is_protected_path(path: str) -> bool:
    n = wu.norm_path(path)
    if not n or len(n) <= 3:
        return True
    if os.path.basename(n) in PROTECTED_FOLDER_NAMES:
        return True
    kf = wu.known_folders()
    if wu.is_under(n, kf.get("windows", r"C:\Windows")):
        return True
    roots = _known_roots()
    if n in roots or any(wu.is_under(r, n) for r in roots):  # n is a known root or one of its ancestors
        return True
    for pat in settings["folder_excludes"]:
        if fnmatch.fnmatch(n, wu.norm_path(pat)):
            return True
    return False


def is_excluded_key(full_path: str) -> bool:
    low = full_path.lower().rstrip("\\")
    if low.count("\\") < 2:  # hive\Software level and above
        return True
    for pat in settings["reg_excludes"]:
        if fnmatch.fnmatch(low, pat.lower()):
            return True
    return False


# ---------------------------------------------------------------- model


@dataclass
class Leftover:
    kind: str                    # regkey | regvalue | file | folder | service | task
    path: str                    # display path
    reason: str
    created: bool = True
    excluded: bool = False
    hive: int | None = None
    sub: str = ""
    view: int = 0
    value_name: str | None = None
    size: int | None = None
    extra: dict = field(default_factory=dict)

    @property
    def is_registry(self) -> bool:
        return self.kind in ("regkey", "regvalue")

    @property
    def ident(self) -> str:
        return f"{self.kind}|{self.path.lower()}|{self.value_name or ''}"


@dataclass
class Target:
    """What we are looking for. Built from an installed Program or from Forced Uninstall input."""
    names: list[str]
    publisher: str = ""
    install_dirs: list[str] = field(default_factory=list)
    key_name: str = ""
    product_code: str | None = None
    uninstall_reg: tuple[int, str, int] | None = None
    exe_paths: list[str] = field(default_factory=list)

    @classmethod
    def from_program(cls, p) -> "Target":
        d = p.guess_install_dir()
        return cls(names=[p.name], publisher=p.publisher, install_dirs=[d] if d else [],
                   key_name=p.key_name, product_code=p.product_code,
                   uninstall_reg=(p.hive, p.reg_sub, p.view))

    @classmethod
    def forced(cls, names: Iterable[str] = (), paths: Iterable[str] = ()) -> "Target":
        dirs, exes = [], []
        for raw in paths:
            pth = wu.norm_path(raw)
            if not pth:
                continue
            if pth.endswith(".exe") or os.path.isfile(pth):
                exes.append(pth)
                dirs.append(os.path.dirname(pth))
            else:
                dirs.append(pth)
        names = [n.strip() for n in names if n.strip()]
        if not names:
            names = [os.path.basename(d) for d in dirs]
        return cls(names=names, install_dirs=dirs, exe_paths=exes)


class Matcher:
    """Turns a Target into normalised keyword sets and scores candidate names."""

    def __init__(self, t: Target):
        self.t = t
        strong: set[str] = set()
        weak: set[str] = set()
        pub = clean_publisher(t.publisher)
        self.pub = norm(pub) if norm(pub) not in GENERIC_WORDS and len(norm(pub)) >= 3 else ""
        for raw in t.names:
            c = clean_name(raw)
            for variant in (c, raw):
                if len(norm(variant)) >= 3 and norm(variant) not in GENERIC_WORDS:
                    strong.add(norm(variant))
            words = c.split()
            # "Mozilla Firefox" by "Mozilla" -> also "Firefox"
            if pub and len(words) > 1 and norm(words[0]) == norm(pub.split()[0]):
                rest = norm(" ".join(words[1:]))
                if len(rest) >= 4 and rest not in GENERIC_WORDS:
                    strong.add(rest)
            if len(words) > 1 and len(norm(words[0])) >= 5 and norm(words[0]) not in GENERIC_WORDS:
                weak.add(norm(words[0]))
        if t.key_name and not t.key_name.startswith("{"):
            k = norm(clean_name(t.key_name))
            if len(k) >= 3 and k not in GENERIC_WORDS:
                strong.add(k)
        self.pub_strong = self.pub
        dirs_display: list[str] = []
        for x in t.install_dirs:
            d = os.path.normpath(os.path.expandvars(x.strip().strip('"'))) if x else ""
            if not d or is_protected_path(d):
                continue
            dirs_display.append(d)
            # ...\Brave-Browser\Application -> the real program root is the parent folder
            if norm(os.path.basename(d)) in GENERIC_INSTALL_LEAVES:
                parent = os.path.dirname(d)
                if not is_protected_path(parent):
                    dirs_display.append(parent)
        self.dirs_display = list(dict.fromkeys(dirs_display))
        self.dirs = [wu.norm_path(d) for d in self.dirs_display]
        for d in self.dirs:
            base = norm(os.path.basename(d))
            if len(base) >= 3 and base not in GENERIC_WORDS and base not in GENERIC_INSTALL_LEAVES:
                strong.add(base)
        self.exe_names: set[str] = set()
        exes = list(t.exe_paths)
        for d in self.dirs:
            try:
                exes += [os.path.join(d, f) for f in os.listdir(d) if f.lower().endswith(".exe")]
            except OSError:
                pass
        skip_exe = re.compile(r"^(unins\d*|uninst(all)?|setup|update(r)?|helper|crashreporter|maintenance.*)$", re.I)
        for e in exes:
            stem = os.path.splitext(os.path.basename(e))[0]
            self.exe_names.add(os.path.basename(e).lower())
            if not skip_exe.match(stem) and len(norm(stem)) >= 4 and norm(stem) not in GENERIC_WORDS:
                weak.add(norm(stem))
        self.strong = strong
        self.weak = weak - strong

    def score(self, candidate: str, mode: str) -> str | None:
        """'exact' | 'partial' | None."""
        n = norm(candidate)
        if not n:
            return None
        if n in self.strong:
            return "exact"
        if mode == "safe":
            return None
        if n in self.weak:
            return "partial"
        for k in self.strong:
            if len(k) >= 5 and (n.startswith(k) or (len(n) >= 5 and k.startswith(n) and len(n) / len(k) >= 0.7)):
                return "partial"
        if mode == "advanced":
            for k in self.strong:
                if len(k) >= 6 and k in n:
                    return "partial"
        return None

    def is_vendor(self, candidate: str) -> bool:
        return bool(self.pub) and norm(candidate) == self.pub

    def refers_to_install(self, text: str) -> bool:
        if not text or not self.dirs:
            return False
        low = os.path.expandvars(str(text)).lower().replace("/", "\\")
        return any(d + "\\" in low or low.rstrip("\\\" ") == d or low.endswith(d) for d in self.dirs)


# ---------------------------------------------------------------- scanner


class Scanner:
    def __init__(self, target: Target, mode: str = "moderate", all_users: bool = False,
                 progress: Callable[[str], None] | None = None, cancelled: Callable[[], bool] | None = None):
        assert mode in MODES
        self.t = target
        self.mode = mode
        self.level = MODES.index(mode)
        self.all_users = all_users
        self.include_cloud = settings["include_cloud_folders"]
        self.m = Matcher(target)
        self.items: dict[str, Leftover] = {}
        self.progress = progress or (lambda s: None)
        self.cancelled = cancelled or (lambda: False)

    # ---- bookkeeping --------------------------------------------------------

    def _add(self, item: Leftover):
        if item.is_registry:
            item.excluded = item.kind == "regkey" and is_excluded_key(item.path)
        elif item.kind in ("file", "folder"):
            item.excluded = is_protected_path(item.path)
        cur = self.items.get(item.ident)
        if cur is None or (item.created and not cur.created):
            self.items[item.ident] = item

    def _add_key(self, hive, sub, view, reason, created=True):
        self._add(Leftover("regkey", wu.wow_display(hive, sub, view), reason, created, hive=hive, sub=sub, view=view))

    def _add_value(self, hive, sub, view, name, reason, created=True, data=None):
        disp = wu.wow_display(hive, sub, view)
        self._add(Leftover("regvalue", disp, reason, created, hive=hive, sub=sub, view=view, value_name=name,
                           extra={"data": str(data)[:300] if data is not None else ""}))

    def _add_fs(self, path, reason, created=True):
        path = os.path.normpath(path)
        if not os.path.lexists(path):
            return
        if not self.include_cloud and wu.is_cloud_path(path):
            return  # phone / cloud storage is never offered unless the user opted in
        kind = "folder" if os.path.isdir(path) else "file"
        self._add(Leftover(kind, path, reason, created))

    def _enterable(self, e: os.DirEntry) -> bool:
        """May the scanner look inside this folder? Never through links; cloud only when opted in."""
        kind = wu.entry_kind(e)
        return kind == "normal" or (kind == "cloud" and self.include_cloud)

    # ---- entry point --------------------------------------------------------

    def scan(self) -> list[Leftover]:
        steps = [
            ("Uninstall registry entry", self._scan_uninstall_key),
            ("Install folder", self._scan_install_dirs),
            ("Program and data folders", self._scan_folders),
            ("Shortcuts", self._scan_shortcuts),
            ("Software registry keys", self._scan_software_keys),
            ("Startup entries", self._scan_run_keys),
            ("App Paths", self._scan_app_paths),
            ("Services", self._scan_services),
            ("Scheduled tasks", self._scan_tasks),
        ]
        if self.level >= 1:
            steps += [("Firewall rules", self._scan_firewall), ("Shared DLLs", self._scan_shared_dlls),
                      ("Windows Installer data", self._scan_msi), ("File types", self._scan_classes)]
        if self.level >= 2:
            steps += [
                      ("Usage caches", self._scan_caches),
                      ("Deep registry search", self._scan_deep_registry),
                      ("Deep folder search", self._scan_deep_folders)]
        for label, fn in steps:
            if self.cancelled():
                break
            self.progress(label)
            try:
                fn()
            except Exception as e:  # one failing location must not abort the scan
                self.progress(f"{label}: skipped ({e})")
        self._add_parent_containers()
        items = list(self.items.values())
        for it in items:
            if it.kind == "folder" and it.size is None:
                it.size = wu.dir_size(it.path)
            elif it.kind == "file":
                try:
                    it.size = os.path.getsize(it.path)
                except OSError:
                    pass
        items.sort(key=lambda i: (not i.is_registry, i.path.lower(), i.value_name or ""))
        return items

    # ---- locations ----------------------------------------------------------

    def _user_roots(self) -> list[dict[str, str]]:
        kf = wu.known_folders()
        roots = [kf]
        if self.all_users:
            me = wu.norm_path(kf.get("user_profile", ""))
            for _sid, prof in wu.user_hives():
                if wu.norm_path(prof) == me or not os.path.isdir(prof):
                    continue
                roots.append({
                    "appdata": os.path.join(prof, r"AppData\Roaming"),
                    "local_appdata": os.path.join(prof, r"AppData\Local"),
                    "local_low": os.path.join(prof, r"AppData\LocalLow"),
                    "local_programs": os.path.join(prof, r"AppData\Local\Programs"),
                    "documents": os.path.join(prof, "Documents"),
                    "desktop": os.path.join(prof, "Desktop"),
                    "start_menu": os.path.join(prof, r"AppData\Roaming\Microsoft\Windows\Start Menu\Programs"),
                    "temp": os.path.join(prof, r"AppData\Local\Temp"),
                })
        return roots

    def _folder_roots(self) -> list[str]:
        keys = ["program_files", "program_files_x86", "common_files", "common_files_x86", "program_data",
                "appdata", "local_appdata", "local_low", "local_programs", "start_menu", "common_start_menu"]
        if self.level >= 1:
            keys += ["documents", "temp", "user_profile"]
        out = []
        for i, roots in enumerate(self._user_roots()):
            for k in keys:
                if i > 0 and k in ("program_files", "program_files_x86", "common_files", "common_files_x86",
                                   "program_data", "common_start_menu"):
                    continue
                if roots.get(k) and os.path.isdir(roots[k]):
                    out.append(roots[k])
        return list(dict.fromkeys(out))

    def _scan_uninstall_key(self):
        if self.t.uninstall_reg:
            hive, sub, view = self.t.uninstall_reg
            if wu.key_exists(hive, sub, view):
                self._add_key(hive, sub, view, "Program's uninstall entry")

    def _scan_install_dirs(self):
        for d in self.m.dirs_display:
            if os.path.isdir(d):
                self._add_fs(d, "Install folder")

    def _scan_folders(self):
        for root in self._folder_roots():
            if self.cancelled():
                return
            try:
                entries = list(os.scandir(root))
            except OSError:
                continue
            for e in entries:
                name = e.name
                if e.is_file() and not (root.lower().endswith("programs") or self.level >= 1):
                    continue
                sc = self.m.score(os.path.splitext(name)[0] if e.is_file() else name, self.mode)
                if sc == "exact":
                    self._add_fs(e.path, "Name matches (exact)", True)
                elif e.is_dir() and (self.m.is_vendor(name) or sc == "partial") and self._enterable(e):
                    # Publisher-style container (e.g. BraveSoftware): look inside for the program itself
                    if not self._scan_vendor_folder(e.path, is_vendor=self.m.is_vendor(name)) and sc:
                        self._add_fs(e.path, "Name matches (partial)", False)
                elif sc:
                    self._add_fs(e.path, f"Name matches ({sc})", False)

    def _scan_vendor_folder(self, vendor: str, is_vendor: bool = True) -> bool:
        """Returns True if the whole container was claimed."""
        try:
            children = list(os.scandir(vendor))
        except OSError:
            return False
        matched = 0
        for c in children:
            sc = self.m.score(os.path.splitext(c.name)[0] if c.is_file() else c.name, self.mode)
            install_root = any(wu.is_under(d, c.path) for d in self.m.dirs)
            if sc or install_root:
                created = sc == "exact" or install_root
                self._add_fs(c.path, "Inside publisher folder" + (" (program folder)" if install_root else f" ({sc})"),
                             created)
                matched += created
        if self.level >= 1 and children and matched == len(children):
            self._add_fs(vendor, "Publisher folder (contains only this program)", True)
            return True
        return False

    def _scan_shortcuts(self):
        kf = wu.known_folders()
        places = [kf.get("start_menu"), kf.get("common_start_menu"), kf.get("desktop"), kf.get("public_desktop"),
                  kf.get("taskbar_pins"), kf.get("startup"), kf.get("common_startup")]
        for r in self._user_roots()[1:]:
            places += [r.get("start_menu"), r.get("desktop")]
        for place in filter(None, places):
            for root, _dirs, files in wu.safe_walk(place, self.include_cloud):
                for f in files:
                    if not f.lower().endswith((".lnk", ".url")):
                        continue
                    full = os.path.join(root, f)
                    target = wu.resolve_shortcut(full) if f.lower().endswith(".lnk") else ""
                    if target and self.m.refers_to_install(target):
                        self._add_fs(full, "Shortcut to program")
                    elif self.m.score(os.path.splitext(f)[0], "safe"):
                        broken = bool(target) and not os.path.exists(target)
                        self._add_fs(full, "Shortcut name matches" + (" (broken)" if broken else ""),
                                     broken or not target)

    def _software_roots(self) -> list[tuple[int, str, int]]:
        roots = [(winreg.HKEY_CURRENT_USER, "Software", 0),
                 (winreg.HKEY_LOCAL_MACHINE, "SOFTWARE", wu.VIEW_64),
                 (winreg.HKEY_LOCAL_MACHINE, "SOFTWARE", wu.VIEW_32)]
        if self.all_users:
            me = wu.current_user_sid()
            for sid in wu.subkeys(winreg.HKEY_USERS, ""):
                if sid.startswith("S-1-5-21-") and not sid.endswith("_Classes") and sid != me:
                    roots.append((winreg.HKEY_USERS, sid + "\\Software", 0))
        return roots

    def _scan_software_keys(self):
        skip = {"classes", "microsoft", "policies", "wow6432node", "clients", "registeredapplications"}
        for hive, root, view in self._software_roots():
            for child in wu.subkeys(hive, root, view):
                if child.lower() in skip:
                    continue
                sub = root + "\\" + child
                sc = self.m.score(child, self.mode)
                if sc == "exact":
                    self._add_key(hive, sub, view, "Key name matches (exact)", True)
                elif sc == "partial" or self.m.is_vendor(child) or (self.level >= 1 and self._key_is_vendorish(child)):
                    kids = wu.subkeys(hive, sub, view)
                    matched = 0
                    for k in kids:
                        s2 = self.m.score(k, self.mode)
                        if s2:
                            matched += s2 == "exact"
                            self._add_key(hive, sub + "\\" + k, view, f"Inside publisher key ({s2})", s2 == "exact")
                    claimed = (self.level >= 1 and kids and matched == len(kids)
                               and not [v for v in wu.values(hive, sub, view) if v[0]])
                    if claimed:
                        self._add_key(hive, sub, view, "Publisher key (contains only this program)", True)
                    elif sc:
                        self._add_key(hive, sub, view, "Key name matches (partial)", False)

    def _key_is_vendorish(self, name: str) -> bool:
        # Publisher strings often differ from the registry vendor key ("Mozilla Corporation" vs "Mozilla")
        n = norm(name)
        return bool(self.m.pub) and len(n) >= 4 and (self.m.pub.startswith(n) or n.startswith(self.m.pub))

    def _scan_run_keys(self):
        locs = [(winreg.HKEY_CURRENT_USER, 0), (winreg.HKEY_LOCAL_MACHINE, wu.VIEW_64),
                (winreg.HKEY_LOCAL_MACHINE, wu.VIEW_32)]
        for hive, view in locs:
            for leaf in ("Run", "RunOnce", "RunOnceEx"):
                sub = r"SOFTWARE\Microsoft\Windows\CurrentVersion" + "\\" + leaf
                for name, data, _t in wu.values(hive, sub, view):
                    if self.m.refers_to_install(data):
                        self._add_value(hive, sub, view, name, "Starts the program at logon", data=data)
                    elif name and self.m.score(name, "safe"):
                        self._add_value(hive, sub, view, name, "Startup entry name matches", False, data=data)
            approved = r"Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run"
            for name, _d, _t in wu.values(hive, approved, view):
                if name and self.m.score(name, "safe"):
                    self._add_value(hive, approved, view, name, "Startup approval record")

    def _scan_app_paths(self):
        for hive, view in ((winreg.HKEY_LOCAL_MACHINE, wu.VIEW_64), (winreg.HKEY_LOCAL_MACHINE, wu.VIEW_32),
                           (winreg.HKEY_CURRENT_USER, 0)):
            sub = r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths"
            for child in wu.subkeys(hive, sub, view):
                default = wu.get_value(hive, sub + "\\" + child, "", view)
                if self.m.refers_to_install(default) or (default and not os.path.exists(wu.norm_path(str(default)))
                                                         and child.lower() in self.m.exe_names):
                    self._add_key(hive, sub + "\\" + child, view, "App Paths registration")

    def _scan_services(self):
        base = r"SYSTEM\CurrentControlSet\Services"
        for svc in wu.subkeys(winreg.HKEY_LOCAL_MACHINE, base):
            img = wu.get_value(winreg.HKEY_LOCAL_MACHINE, base + "\\" + svc, "ImagePath")
            if img and self.m.refers_to_install(img):
                disp = wu.get_value(winreg.HKEY_LOCAL_MACHINE, base + "\\" + svc, "DisplayName") or svc
                self._add(Leftover("service", svc, f"Service runs from install folder ({disp})", True,
                                   hive=winreg.HKEY_LOCAL_MACHINE, sub=base + "\\" + svc, extra={"image": img}))

    def _scan_tasks(self):
        tasks_dir = wu.known_folders().get("tasks")
        if not tasks_dir:
            return
        for root, _dirs, files in os.walk(tasks_dir):
            for f in files:
                full = os.path.join(root, f)
                try:
                    raw = open(full, "rb").read(200_000)
                except OSError:
                    continue
                text = raw.decode("utf-16", "ignore") if raw[:2] in (b"\xff\xfe", b"\xfe\xff") \
                    else raw.decode("utf-8", "ignore")
                cmds = re.findall(r"<Command>(.*?)</Command>", text, re.S)
                name = os.path.relpath(full, tasks_dir)
                hit = any(self.m.refers_to_install(c) for c in cmds)
                if hit or self.m.score(f, "safe"):
                    self._add(Leftover("task", "\\" + name, "Scheduled task" + (" runs the program" if hit else
                                                                                   " name matches"), hit or True,
                                       extra={"command": "; ".join(cmds)[:300], "file": full}))

    def _scan_firewall(self):
        sub = r"SYSTEM\CurrentControlSet\Services\SharedAccess\Parameters\FirewallPolicy\FirewallRules"
        for name, data, _t in wu.values(winreg.HKEY_LOCAL_MACHINE, sub):
            m = re.search(r"\|App=([^|]+)", str(data))
            if m and self.m.refers_to_install(m.group(1)):
                self._add_value(winreg.HKEY_LOCAL_MACHINE, sub, 0, name, "Firewall rule for the program", data=data)

    def _scan_shared_dlls(self):
        sub = r"SOFTWARE\Microsoft\Windows\CurrentVersion\SharedDLLs"
        for view in (wu.VIEW_64, wu.VIEW_32):
            for name, _d, _t in wu.values(winreg.HKEY_LOCAL_MACHINE, sub, view):
                if self.m.refers_to_install(name):
                    self._add_value(winreg.HKEY_LOCAL_MACHINE, sub, view, name, "Shared DLL reference")

    def _scan_msi(self):
        code = self.t.product_code
        if not code:
            return
        packed = pack_guid(code)
        hklm, hkcu = winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER
        for hive, sub in ((hklm, r"SOFTWARE\Classes\Installer\Products\\" + packed),
                          (hklm, r"SOFTWARE\Classes\Installer\Features\\" + packed),
                          (hkcu, r"Software\Microsoft\Installer\Products\\" + packed),
                          (hkcu, r"Software\Microsoft\Installer\Features\\" + packed),
                          (hklm, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Installer\UserData\S-1-5-18\Products\\"
                           + packed)):
            sub = sub.replace("\\\\", "\\")
            if wu.key_exists(hive, sub, wu.VIEW_64):
                self._add_key(hive, sub, wu.VIEW_64, "Windows Installer product registration")
        up = r"SOFTWARE\Classes\Installer\UpgradeCodes"
        for uc in wu.subkeys(hklm, up, wu.VIEW_64):
            vals = wu.values(hklm, up + "\\" + uc, wu.VIEW_64)
            if any(n.upper() == packed for n, _d, _t in vals):
                if len(vals) == 1:
                    self._add_key(hklm, up + "\\" + uc, wu.VIEW_64, "Windows Installer upgrade code")
                else:
                    self._add_value(hklm, up + "\\" + uc, wu.VIEW_64, packed, "Windows Installer upgrade code")

    def _class_roots(self):
        return [(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Classes", wu.VIEW_64),
                (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Classes", wu.VIEW_32),
                (winreg.HKEY_CURRENT_USER, r"Software\Classes", 0)]

    def _scan_classes(self):
        if not self.m.dirs:
            return
        progids: set[str] = set()
        for hive, root, view in self._class_roots():
            if self.cancelled():
                return
            for clsid in (wu.subkeys(hive, root + r"\CLSID", view) if self.level >= 2 else []):
                base = root + r"\CLSID\\" + clsid
                base = base.replace("\\\\", "\\")
                for server in ("InprocServer32", "LocalServer32", "InprocHandler32"):
                    val = wu.get_value(hive, base + "\\" + server, "", view)
                    if val and self.m.refers_to_install(val):
                        self._add_key(hive, base, view, f"COM class served by the program ({server})")
                        pid = wu.get_value(hive, base + r"\ProgID", "", view)
                        if pid:
                            progids.add(str(pid))
                        break
            for tlb in (wu.subkeys(hive, root + r"\TypeLib", view) if self.level >= 2 else []):
                base = root + r"\TypeLib" + "\\" + tlb
                hit = False
                for ver in wu.subkeys(hive, base, view):
                    for lcid in wu.subkeys(hive, base + "\\" + ver, view):
                        for plat in wu.subkeys(hive, base + "\\" + ver + "\\" + lcid, view):
                            v = wu.get_value(hive, "\\".join((base, ver, lcid, plat)), "", view)
                            if v and self.m.refers_to_install(v):
                                hit = True
                if hit:
                    self._add_key(hive, base, view, "Type library registered by the program")
            for name in wu.subkeys(hive, root, view):
                if name.startswith((".", "*")) or name in ("CLSID", "TypeLib", "Interface", "AppID", "Installer"):
                    continue
                k = root + "\\" + name
                cmd = wu.get_value(hive, k + r"\shell\open\command", "", view)
                icon = wu.get_value(hive, k + r"\DefaultIcon", "", view)
                if (cmd and self.m.refers_to_install(cmd)) or (icon and self.m.refers_to_install(icon)) \
                        or name in progids:
                    self._add_key(hive, k, view, "File type / ProgID handled by the program")
                    progids.add(name)
            apps = root + r"\Applications"
            for exe in wu.subkeys(hive, apps, view):
                if exe.lower() in self.m.exe_names:
                    self._add_key(hive, apps + "\\" + exe, view, "'Open with' application registration")
            if progids:
                for ext in (n for n in wu.subkeys(hive, root, view) if n.startswith(".")):
                    owp = root + "\\" + ext + r"\OpenWithProgids"
                    for vname, _d, _t in wu.values(hive, owp, view):
                        if vname in progids:
                            self._add_value(hive, owp, view, vname, f"'Open with' entry for {ext}")
                    if str(wu.get_value(hive, root + "\\" + ext, "", view) or "") in progids:
                        self._add_value(hive, root + "\\" + ext, view, "", f"Default handler of {ext}", False)

    def _scan_caches(self):
        hkcu = winreg.HKEY_CURRENT_USER
        for sub in (r"Software\Classes\Local Settings\Software\Microsoft\Windows\Shell\MuiCache",
                    r"Software\Microsoft\Windows NT\CurrentVersion\AppCompatFlags\Compatibility Assistant\Store",
                    r"Software\Microsoft\Windows NT\CurrentVersion\AppCompatFlags\Layers"):
            for name, _d, _t in wu.values(hkcu, sub):
                if self.m.refers_to_install(name.split(".FriendlyAppName")[0].split(".ApplicationCompany")[0]):
                    self._add_value(hkcu, sub, 0, name, "Windows usage/compatibility record")
        for view in (wu.VIEW_64, wu.VIEW_32):
            sub = r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\AppCompatFlags\Layers"
            for name, _d, _t in wu.values(winreg.HKEY_LOCAL_MACHINE, sub, view):
                if self.m.refers_to_install(name):
                    self._add_value(winreg.HKEY_LOCAL_MACHINE, sub, view, name, "Compatibility setting")
        sub = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Installer\Folders"
        for name, _d, _t in wu.values(winreg.HKEY_LOCAL_MACHINE, sub, wu.VIEW_64):
            if self.m.refers_to_install(name):
                self._add_value(winreg.HKEY_LOCAL_MACHINE, sub, wu.VIEW_64, name, "Windows Installer folder record")

    def _scan_deep_registry(self, max_depth: int = 4):
        """Walk Software trees a few levels deep looking for exact name matches anywhere."""
        for hive, root, view in self._software_roots():
            stack = [(root, 0)]
            while stack:
                if self.cancelled():
                    return
                sub, depth = stack.pop()
                for child in wu.subkeys(hive, sub, view):
                    path = sub + "\\" + child
                    if depth >= 1 and self.m.score(child, "safe"):
                        self._add_key(hive, path, view, "Key name matches (deep search)", False)
                    elif depth + 1 < max_depth and child.lower() not in ("classes", "wow6432node") and \
                            not child.startswith("{"):
                        stack.append((path, depth + 1))
                        if self.m.refers_to_install(wu.get_value(hive, path, "", view) or ""):
                            self._add_key(hive, path, view, "Key points into install folder", False)

    def _scan_deep_folders(self, max_depth: int = 3):
        for root in self._folder_roots():
            stack = [(root, 0)]
            while stack:
                if self.cancelled():
                    return
                path, depth = stack.pop()
                try:
                    entries = [e for e in os.scandir(path) if e.is_dir(follow_symlinks=False) and self._enterable(e)]
                except OSError:
                    continue
                for e in entries:
                    if depth >= 1 and self.m.score(e.name, "safe"):
                        self._add_fs(e.path, "Folder name matches (deep search)", False)
                    elif depth + 1 < max_depth and e.name.lower() not in ("windowsapps", "packages", "node_modules",
                                                                         "site-packages", ".git"):
                        stack.append((e.path, depth + 1))

    def _add_parent_containers(self):
        """After removal a Start-menu sub folder may be left empty - offer it too."""
        kf = wu.known_folders()
        menus = [wu.norm_path(kf.get("start_menu", "")), wu.norm_path(kf.get("common_start_menu", ""))]
        by_parent: dict[str, int] = {}
        for it in self.items.values():
            if it.kind in ("file", "folder"):
                by_parent[wu.norm_path(os.path.dirname(it.path))] = by_parent.get(
                    wu.norm_path(os.path.dirname(it.path)), 0) + 1
        for parent, count in by_parent.items():
            if not any(m and wu.is_under(parent, m) and parent != m for m in menus):
                continue
            try:
                if len(os.listdir(parent)) == count:
                    self._add_fs(parent, "Start Menu folder that becomes empty", True)
            except OSError:
                pass


def pack_guid(guid: str) -> str:
    """{12345678-ABCD-EF01-2345-6789ABCDEF01} -> MSI 'packed' (compressed) GUID form."""
    g = guid.strip("{}").replace("-", "").upper()
    parts = [g[0:8][::-1], g[8:12][::-1], g[12:16][::-1]]
    rest = g[16:]
    parts.append("".join(rest[i:i + 2][::-1] for i in range(0, 16, 2)))
    return "".join(parts)


def scan(target: Target, mode: str = "moderate", **kw) -> list[Leftover]:
    return Scanner(target, mode, **kw).scan()
