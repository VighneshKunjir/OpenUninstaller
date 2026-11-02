"""Browser extension listing/removal for Chromium browsers (Chrome, Edge, Brave, Vivaldi, Opera) and Firefox."""

from __future__ import annotations

import glob
import json
import os
import shutil
import winreg
from dataclasses import dataclass, field

import psutil

from . import winutil as wu

LOCAL = os.environ.get("LOCALAPPDATA", "")
ROAMING = os.environ.get("APPDATA", "")

CHROMIUM = {
    "Google Chrome": (os.path.join(LOCAL, r"Google\Chrome\User Data"), "chrome.exe", r"Google\Chrome"),
    "Microsoft Edge": (os.path.join(LOCAL, r"Microsoft\Edge\User Data"), "msedge.exe", r"Microsoft\Edge"),
    "Brave": (os.path.join(LOCAL, r"BraveSoftware\Brave-Browser\User Data"), "brave.exe", r"BraveSoftware\Brave"),
    "Vivaldi": (os.path.join(LOCAL, r"Vivaldi\User Data"), "vivaldi.exe", r"Vivaldi"),
    "Opera": (os.path.join(ROAMING, r"Opera Software\Opera Stable"), "opera.exe", r"Opera Software"),
}
FIREFOX_PROFILES = os.path.join(ROAMING, r"Mozilla\Firefox\Profiles")


@dataclass
class Extension:
    browser: str
    profile: str
    ext_id: str
    name: str
    version: str = ""
    description: str = ""
    enabled: bool = True
    source: str = "User"            # User | External (registry) | Policy
    folder: str = ""
    profile_dir: str = ""
    reg_keys: list = field(default_factory=list)   # (hive, sub, view, value_name|None)


def _localized(text: str, ext_dir: str, default_locale: str | None) -> str:
    if not text or not text.startswith("__MSG_"):
        return text or ""
    key = text[6:-2].lower()
    for loc in filter(None, (default_locale, "en", "en_US")):
        try:
            with open(os.path.join(ext_dir, "_locales", loc, "messages.json"), encoding="utf-8-sig") as f:
                msgs = {k.lower(): v for k, v in json.load(f).items()}
            if key in msgs:
                return msgs[key].get("message", text)
        except (OSError, ValueError):
            continue
    return text


def _load_json(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _chromium_profiles(user_data: str) -> list[str]:
    if os.path.isfile(os.path.join(user_data, "Preferences")):   # Opera keeps the profile in the root
        return [user_data]
    return [os.path.dirname(p) for p in glob.glob(os.path.join(user_data, "*", "Preferences"))]


def _external_reg(vendor_key: str) -> dict[str, list]:
    found: dict[str, list] = {}
    for hive, view in ((winreg.HKEY_LOCAL_MACHINE, wu.VIEW_64), (winreg.HKEY_LOCAL_MACHINE, wu.VIEW_32),
                       (winreg.HKEY_CURRENT_USER, 0)):
        sub = f"SOFTWARE\\{vendor_key}\\Extensions"
        for ext_id in wu.subkeys(hive, sub, view):
            found.setdefault(ext_id, []).append((hive, sub + "\\" + ext_id, view, None))
        pol = f"SOFTWARE\\Policies\\{vendor_key}\\ExtensionInstallForcelist"
        for name, data, _t in wu.values(hive, pol, view):
            ext_id = str(data).split(";")[0]
            found.setdefault(ext_id, []).append((hive, pol, view, name))
    return found


def list_extensions() -> list[Extension]:
    out: list[Extension] = []
    for browser, (user_data, _exe, vendor) in CHROMIUM.items():
        if not os.path.isdir(user_data):
            continue
        external = _external_reg(vendor)
        for prof in _chromium_profiles(user_data):
            prefs = _load_json(os.path.join(prof, "Preferences"))
            secure = _load_json(os.path.join(prof, "Secure Preferences"))
            settings_ = {**prefs.get("extensions", {}).get("settings", {}),
                         **secure.get("extensions", {}).get("settings", {})}
            prof_name = prefs.get("profile", {}).get("name") or os.path.basename(prof)
            ext_root = os.path.join(prof, "Extensions")
            ids = set(os.listdir(ext_root)) if os.path.isdir(ext_root) else set()
            for ext_id in sorted(ids):
                versions = sorted(glob.glob(os.path.join(ext_root, ext_id, "*", "manifest.json")))
                if not versions:
                    continue
                mdir = os.path.dirname(versions[-1])
                man = _load_json(versions[-1])
                if man.get("theme") is not None and not man.get("name"):
                    continue
                st = settings_.get(ext_id, {})
                if st.get("location") in (5, 10):          # component extensions ship with the browser
                    continue
                dl = man.get("default_locale")
                enabled = st.get("state", 1) == 1 and not st.get("disable_reasons")
                out.append(Extension(
                    browser, prof_name, ext_id, _localized(man.get("name", ext_id), mdir, dl),
                    man.get("version", ""), _localized(man.get("description", ""), mdir, dl)[:200], enabled,
                    "Policy" if any(k[3] for k in external.get(ext_id, [])) else
                    "External" if ext_id in external else "User",
                    os.path.join(ext_root, ext_id), prof, external.get(ext_id, [])))
    for ff in glob.glob(os.path.join(FIREFOX_PROFILES, "*", "extensions.json")):
        prof = os.path.dirname(ff)
        for a in _load_json(ff).get("addons", []):
            if a.get("type") not in ("extension", "theme") or a.get("location") not in ("app-profile", "app-global"):
                continue
            loc = a.get("defaultLocale") or {}
            out.append(Extension("Mozilla Firefox", os.path.basename(prof), a["id"], loc.get("name") or a["id"],
                                 a.get("version", ""), (loc.get("description") or "")[:200], bool(a.get("active")),
                                 "User", a.get("path") or "", prof))
    return out


def browser_running(browser: str) -> bool:
    exe = CHROMIUM.get(browser, (None, "firefox.exe"))[1]
    return any((p.info["name"] or "").lower() == exe for p in psutil.process_iter(["name"]))


def _strip_from_prefs(path: str, ext_id: str) -> None:
    data = _load_json(path)
    if not data:
        return
    changed = False
    for section in ("settings", "pinned_extensions", "toolbar"):
        cont = data.get("extensions", {}).get(section)
        if isinstance(cont, dict) and ext_id in cont:
            del cont[ext_id]
            changed = True
        elif isinstance(cont, list) and ext_id in cont:
            cont.remove(ext_id)
            changed = True
    macs = data.get("protection", {}).get("macs", {}).get("extensions", {}).get("settings", {})
    if ext_id in macs:
        del macs[ext_id]
        changed = True
    if changed:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, separators=(",", ":"))


def remove(ext: Extension) -> tuple[bool, str]:
    if browser_running(ext.browser):
        return False, f"Close {ext.browser} first."
    try:
        for hive, sub, view, value_name in ext.reg_keys:
            try:
                if value_name:
                    wu.delete_value(hive, sub, value_name, view)
                else:
                    wu.delete_key_tree(hive, sub, view)
            except OSError:
                pass
        if ext.browser == "Mozilla Firefox":
            if ext.folder and os.path.exists(ext.folder):
                (shutil.rmtree if os.path.isdir(ext.folder) else os.remove)(ext.folder)
            ej = os.path.join(ext.profile_dir, "extensions.json")
            data = _load_json(ej)
            data["addons"] = [a for a in data.get("addons", []) if a.get("id") != ext.ext_id]
            with open(ej, "w", encoding="utf-8") as f:
                json.dump(data, f)
            return True, ""
        shutil.rmtree(ext.folder, ignore_errors=True)
        for extra in ("Local Extension Settings", "Sync Extension Settings", "Managed Extension Settings"):
            shutil.rmtree(os.path.join(ext.profile_dir, extra, ext.ext_id), ignore_errors=True)
        for p in glob.glob(os.path.join(ext.profile_dir, "IndexedDB", f"chrome-extension_{ext.ext_id}_*")):
            shutil.rmtree(p, ignore_errors=True)
        for prefs in ("Preferences", "Secure Preferences"):
            _strip_from_prefs(os.path.join(ext.profile_dir, prefs), ext.ext_id)
        return True, ""
    except OSError as e:
        return False, str(e)
