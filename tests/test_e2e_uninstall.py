"""End-to-end test with a fake per-user app: uninstall -> scan -> delete (with backup) -> restore.

Creates only HKCU keys and folders named OUTest*, and removes them again. No admin needed.
Run:  .venv\\Scripts\\python tests\\test_e2e_uninstall.py
"""
import os
import shutil
import sys
import winreg

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from openuninstaller import backup, programs, winutil as wu  # noqa: E402
from openuninstaller.config import settings  # noqa: E402
from openuninstaller.leftovers import Target, scan  # noqa: E402
from openuninstaller.uninstall import run_uninstaller  # noqa: E402

HKCU = winreg.HKEY_CURRENT_USER
LOCAL, ROAM = os.environ["LOCALAPPDATA"], os.environ["APPDATA"]
APPDIR = os.path.join(LOCAL, "Programs", "OUTest Widget")
DATADIR = os.path.join(ROAM, "OUTestCorp", "OUTest Widget")
UNINST = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\OUTestWidget"
RUN = r"Software\Microsoft\Windows\CurrentVersion\Run"
LNK = os.path.join(wu.known_folders()["start_menu"], "OUTest Widget.lnk")


def setup():
    os.makedirs(APPDIR, exist_ok=True)
    os.makedirs(DATADIR, exist_ok=True)
    exe = os.path.join(APPDIR, "widget.exe")
    open(exe, "wb").write(b"MZ fake")
    open(os.path.join(DATADIR, "settings.ini"), "w").write("[x]\na=1\n")
    bat = os.path.join(APPDIR, "uninstall.bat")
    # Sloppy uninstaller: only removes its exe and its uninstall key
    open(bat, "w").write(f'@echo off\r\ndel "{exe}"\r\nreg delete "HKCU\\{UNINST}" /f >nul\r\n')
    wu.set_value(HKCU, UNINST, "DisplayName", winreg.REG_SZ, "OUTest Widget 2.1")
    wu.set_value(HKCU, UNINST, "DisplayVersion", winreg.REG_SZ, "2.1.0")
    wu.set_value(HKCU, UNINST, "Publisher", winreg.REG_SZ, "OUTestCorp Inc.")
    wu.set_value(HKCU, UNINST, "InstallLocation", winreg.REG_SZ, APPDIR)
    wu.set_value(HKCU, UNINST, "UninstallString", winreg.REG_SZ, f'cmd.exe /c "{bat}"')
    wu.set_value(HKCU, r"Software\OUTestCorp\OUTest Widget", "Theme", winreg.REG_SZ, "dark")
    wu.set_value(HKCU, r"Software\OUTestCorp\OUTest Widget", "Count", winreg.REG_DWORD, 42)
    wu.set_value(HKCU, RUN, "OUTestWidget", winreg.REG_SZ, f'"{exe}" /tray')
    wu.set_value(HKCU, r"Software\Classes\OUTestWidget.Document\shell\open\command", "", winreg.REG_SZ, f'"{exe}" "%1"')
    wu.create_shortcut(LNK, exe)


def cleanup(backup_id=None):
    for sub in (r"Software\OUTestCorp", r"Software\Classes\OUTestWidget.Document", UNINST):
        try:
            wu.delete_key_tree(HKCU, sub)
        except OSError:
            pass
    try:
        wu.delete_value(HKCU, RUN, "OUTestWidget")
    except OSError:
        pass
    for d in (APPDIR, os.path.join(ROAM, "OUTestCorp")):
        shutil.rmtree(d, ignore_errors=True)
    if os.path.exists(LNK):
        os.remove(LNK)
    if backup_id:
        shutil.rmtree(os.path.join(backup.BACKUP_DIR, backup_id), ignore_errors=True)
    for h in backup.list_history():
        if (h.get("program") or {}).get("name", "").startswith("OUTest"):
            backup.delete_history(h["id"])


results = []


def check(label, cond):
    results.append(bool(cond))
    print(("PASS " if cond else "FAIL ") + label)


def main():
    setup()
    m = None
    try:
        p = next((x for x in programs.list_programs() if x.name == "OUTest Widget 2.1"), None)
        check("program is listed", p is not None)
        target = Target.from_program(p)
        res = run_uninstaller(p)
        check("built-in uninstaller ran and removed its entry", res["ran"] and not res["still_installed"])
        items = scan(target, "moderate")
        created = {(i.kind, i.path.lower()) for i in items if i.created}
        check("found install folder", ("folder", APPDIR.lower()) in created)
        check("found publisher folder", ("folder", os.path.join(ROAM, "OUTestCorp").lower()) in created)
        check("found publisher key", ("regkey", r"hkey_current_user\software\outestcorp") in created)
        check("found start menu shortcut", ("file", LNK.lower()) in created)
        check("found Run value", any(i.kind == "regvalue" and i.value_name == "OUTestWidget" for i in items))
        check("found ProgID", any(i.path.endswith("OUTestWidget.Document") for i in items))

        settings.data["file_delete_mode"] = "backup"   # in memory only: keep test files out of the Recycle Bin
        m = backup.delete_items([i for i in items if i.created], "Uninstall", p.name)
        check("nothing failed", all(i["status"] != "failed" for i in m["items"]))
        check("app folder gone", not os.path.exists(APPDIR))
        check("publisher key gone", not wu.key_exists(HKCU, r"Software\OUTestCorp"))
        check("Run value gone", wu.get_value(HKCU, RUN, "OUTestWidget") is None)

        res = backup.restore_backup(m["id"])
        check("restore reported success", all(r[1] for r in res))
        check("publisher key restored with DWORD", wu.get_value(HKCU, r"Software\OUTestCorp\OUTest Widget", "Count") == 42)
        check("Run value restored", wu.get_value(HKCU, RUN, "OUTestWidget") is not None)
        check("files restored", os.path.isfile(os.path.join(DATADIR, "settings.ini")))
    finally:
        cleanup(m and m["id"])
    print("\nALL PASSED" if all(results) else "\nSOME CHECKS FAILED")
    return all(results)


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
