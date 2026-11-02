"""Render README screenshots of the real UI filled with neutral demo data (nothing from this PC is shown).

Run:  .venv\\Scripts\\python docs\\make_screenshots.py      -> docs/screenshots/*.png
"""
import os
import sys
import time
import winreg

os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
OUT = os.path.join(ROOT, "docs", "screenshots")

from PySide6.QtWidgets import QApplication  # noqa: E402

from openuninstaller import autorun, backup, programs, winutil as wu  # noqa: E402
from openuninstaller.config import settings  # noqa: E402
from openuninstaller.leftovers import Leftover  # noqa: E402

HKLM, HKCU = winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER
MB = 1024 * 1024

# ---------------------------------------------------------------- demo data

DEMO_PROGRAMS = [
    # name, version, publisher, size MB, date, scope, msi
    ("7-Zip 24.09 (x64)", "24.09", "Igor Pavlov", 5.6, "2025-11-04", "64-bit", False),
    ("Audacity 3.7.1", "3.7.1", "Audacity Team", 98.2, "2025-12-18", "64-bit", False),
    ("Blender", "4.3.2", "Blender Foundation", 1210.0, "2026-01-22", "64-bit", True),
    ("Discord", "1.0.9172", "Discord Inc.", 113.8, "2026-10-29", "User", False),
    ("GIMP 2.10.38", "2.10.38", "The GIMP Team", 312.4, "2025-09-30", "64-bit", False),
    ("Git", "2.47.1", "The Git Development Community", 334.0, "2026-02-11", "64-bit", False),
    ("Google Chrome", "131.0.6778.86", "Google LLC", 612.7, "2026-10-27", "64-bit", True),
    ("HandBrake 1.9.0", "1.9.0", "HandBrake Team", 74.1, "2026-03-05", "64-bit", False),
    ("Inkscape", "1.4.0", "Inkscape Project", 486.3, "2025-10-12", "64-bit", True),
    ("LibreOffice 24.8.3.2", "24.8.3.2", "The Document Foundation", 1043.5, "2026-04-02", "64-bit", True),
    ("Microsoft Visual Studio Code (User)", "1.96.0", "Microsoft Corporation", 402.6, "2026-10-30", "User", False),
    ("Mozilla Firefox (x64 en-US)", "133.0", "Mozilla", 243.9, "2026-10-28", "64-bit", False),
    ("Notepad++ (64-bit x64)", "8.7.4", "Notepad++ Team", 16.9, "2026-05-14", "64-bit", False),
    ("OBS Studio", "31.0.0", "OBS Project", 512.0, "2026-06-20", "64-bit", False),
    ("Paint.NET", "5.1.2", "dotPDN LLC", 211.0, "2026-07-08", "64-bit", True),
    ("Python 3.13.1 (64-bit)", "3.13.1", "Python Software Foundation", 104.3, "2026-08-01", "64-bit", False),
    ("ShareX", "17.0.0", "ShareX Team", 41.8, "2026-08-19", "64-bit", False),
    ("Spotify", "1.2.52.442", "Spotify AB", 356.2, "2026-10-31", "User", False),
    ("Steam", "2.10.91.91", "Valve Corporation", 820.4, "2026-09-03", "32-bit", False),
    ("VLC media player", "3.0.21", "VideoLAN", 182.6, "2026-09-15", "64-bit", False),
    ("WinRAR 7.01 (64-bit)", "7.01.0", "win.rar GmbH", 9.8, "2026-02-27", "64-bit", False),
    ("Zoom Workplace", "6.3.0", "Zoom Video Communications, Inc.", 287.5, "2026-10-21", "User", False),
]


def demo_programs(*_a, **_k):
    out = []
    for name, ver, pub, size, date, scope, msi in DEMO_PROGRAMS:
        hive = HKCU if scope == "User" else HKLM
        view = {"64-bit": wu.VIEW_64, "32-bit": wu.VIEW_32}.get(scope, 0)
        folder = name.split(" (")[0].split(" 2")[0]
        out.append(programs.Program(
            name=name, key_name=("{%08X-0000-0000-0000-000000000000}" % abs(hash(name)) if msi else folder),
            hive=hive, view=view, scope=scope, version=ver, publisher=pub,
            install_location=rf"C:\Program Files\{folder}", uninstall_string=rf'"C:\Program Files\{folder}\uninstall.exe"',
            install_date=date, size_bytes=int(size * MB), is_msi=msi))
    return out


def vlc_leftovers():
    L = Leftover
    reg = [
        L("regkey", r"HKEY_CURRENT_USER\Software\VideoLAN", "Publisher key (contains only this program)", True,
          hive=HKCU, sub=r"Software\VideoLAN"),
        L("regkey", r"HKEY_CURRENT_USER\Software\VideoLAN\VLC", "Inside publisher key (exact)", True,
          hive=HKCU, sub=r"Software\VideoLAN\VLC"),
        L("regkey", r"HKEY_LOCAL_MACHINE\SOFTWARE\VideoLAN\VLC", "Inside publisher key (exact)", True,
          hive=HKLM, sub=r"SOFTWARE\VideoLAN\VLC"),
        L("regkey", r"HKEY_LOCAL_MACHINE\SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\vlc.exe",
          "App Paths registration", True, hive=HKLM),
        L("regkey", r"HKEY_LOCAL_MACHINE\SOFTWARE\Classes\Applications\vlc.exe", "'Open with' application registration",
          True, hive=HKLM),
        L("regkey", r"HKEY_LOCAL_MACHINE\SOFTWARE\Classes\VLC.mp4", "File type / ProgID handled by the program", True,
          hive=HKLM),
        L("regkey", r"HKEY_LOCAL_MACHINE\SOFTWARE\Classes\VLC.mkv", "File type / ProgID handled by the program", True,
          hive=HKLM),
        L("regkey", r"HKEY_LOCAL_MACHINE\SOFTWARE\Classes\VLC.mp3", "File type / ProgID handled by the program", True,
          hive=HKLM),
        L("regkey", r"HKEY_LOCAL_MACHINE\SOFTWARE\Classes\Directory\shell\AddToPlaylistVLC",
          "Key name matches (partial)", False, hive=HKLM),
        L("regvalue", r"HKEY_LOCAL_MACHINE\SOFTWARE\Classes\.mp4\OpenWithProgids", "'Open with' entry for .mp4", True,
          hive=HKLM, value_name="VLC.mp4"),
        L("regvalue", r"HKEY_LOCAL_MACHINE\SOFTWARE\Classes\.mkv\OpenWithProgids", "'Open with' entry for .mkv", True,
          hive=HKLM, value_name="VLC.mkv"),
        L("regvalue", r"HKEY_CURRENT_USER\Software\Classes\Local Settings\Software\Microsoft\Windows\Shell\MuiCache",
          "Windows usage/compatibility record", True, hive=HKCU,
          value_name=r"C:\Program Files\VideoLAN\VLC\vlc.exe.FriendlyAppName",
          extra={"data": "VLC media player"}),
        L("regkey", r"HKEY_LOCAL_MACHINE\SOFTWARE\Clients\Media", "Shared media clients key", False, True, hive=HKLM),
    ]
    fs = [
        L("folder", r"C:\Program Files\VideoLAN", "Publisher folder (contains only this program)", True, size=int(182.4 * MB)),
        L("folder", r"C:\Program Files\VideoLAN\VLC", "Install folder", True, size=int(182.4 * MB)),
        L("folder", r"C:\Users\User\AppData\Roaming\vlc", "Name matches (exact)", True, size=int(2.3 * MB)),
        L("folder", r"C:\ProgramData\Microsoft\Windows\Start Menu\Programs\VideoLAN",
          "Start Menu folder that becomes empty", True, size=4096),
        L("file", r"C:\ProgramData\Microsoft\Windows\Start Menu\Programs\VideoLAN\VLC media player.lnk",
          "Shortcut to program", True, size=2048),
        L("file", r"C:\Users\Public\Desktop\VLC media player.lnk", "Shortcut to program", True, size=2048),
        L("folder", r"C:\Users\User\Documents\VLC Playlists", "Name matches (partial)", False, size=int(0.1 * MB)),
    ]
    return reg, fs


def demo_autoruns(*_a, **_k):
    A = autorun.AutorunItem
    rows = [
        ("Discord", r'"C:\Users\User\AppData\Local\Discord\Update.exe" --processStart Discord.exe', "registry",
         r"HKCU\Run", False, "Discord Inc.", "Discord", False),
        ("Steam", r'"C:\Program Files (x86)\Steam\steam.exe" -silent', "registry", r"HKCU\Run", False,
         "Valve Corporation", "Steam", False),
        ("Spotify", r'"C:\Users\User\AppData\Roaming\Spotify\Spotify.exe" --autostart', "registry", r"HKCU\Run",
         False, "Spotify AB", "Spotify", False),
        ("OneDrive", r'"C:\Program Files\Microsoft OneDrive\OneDrive.exe" /background', "registry", r"HKCU\Run",
         True, "Microsoft Corporation", "Microsoft OneDrive", True),
        ("SecurityHealth", r"%windir%\system32\SecurityHealthSystray.exe", "registry", r"HKLM\Run", True,
         "Microsoft Corporation", "Windows Security notification icon", True),
        ("ShareX", r'"C:\Program Files\ShareX\ShareX.exe" -silent', "folder", "Startup folder", True,
         "ShareX Team", "ShareX", True),
        ("Google Updater Service", r'"C:\Program Files (x86)\Google\GoogleUpdater\updater.exe" --system --windows-service',
         "service", "Services", True, "Google LLC", "Google Updater", False),
        ("Zoom Sharing Service", r'"C:\Program Files\Common Files\Zoom\Support\CptService.exe"', "service",
         "Services", False, "Zoom Video Communications, Inc.", "Zoom Sharing Service", False),
        ("Docker Desktop Service", r'"C:\Program Files\Docker\Docker\com.docker.service"', "service", "Services",
         True, "Docker Inc.", "Docker Desktop Service", True),
        ("Adobe Acrobat Update Task", r'"C:\Program Files (x86)\Common Files\Adobe\ARM\1.0\AdobeARM.exe"', "task",
         "Task Scheduler", False, "Adobe Inc.", "Adobe Acrobat Update Service", False),
        ("OBS Studio", r'"C:\Program Files\obs-studio\bin\64bit\obs64.exe" --minimize-to-tray', "registry",
         r"HKCU\Run", False, "OBS Project", "OBS Studio", False),
    ]
    out = []
    for name, cmd, kind, loc, enabled, pub, desc, running in rows:
        it = A(name, cmd, kind, loc, enabled, pub, desc, exe=cmd.split('"')[1] if '"' in cmd else cmd,
               extra={"demo_running": running, "hive": HKCU, "sub": "", "view": 0, "approved": "Run"})
        out.append(it)
    return out


def demo_history():
    return [
        {"id": "d1", "date": "2026-11-01 18:42:10", "operation": "Uninstall", "scan_mode": "moderate",
         "program": {"name": "VLC media player", "version": "3.0.21"}, "ok": 19, "failed": 0, "items": []},
        {"id": "d2", "date": "2026-10-30 09:15:51", "operation": "Quick Uninstall", "scan_mode": "moderate",
         "program": {"name": "Skype", "version": "8.131"}, "ok": 27, "failed": 1, "items": []},
        {"id": "d3", "date": "2026-10-27 21:03:33", "operation": "Forced Uninstall", "scan_mode": "advanced",
         "program": {"name": "Old Toolbar", "version": ""}, "ok": 14, "failed": 0, "items": []},
        {"id": "d4", "date": "2026-10-25 12:30:07", "operation": "Junk Files Cleaner", "scan_mode": None,
         "program": {"name": "Junk files", "version": ""}, "ok": 312, "failed": 6, "items": []},
    ]


# ---------------------------------------------------------------- patch data sources

programs.list_programs = demo_programs
autorun.list_autoruns = demo_autoruns
autorun.AutorunItem.valid = property(lambda s: True)
autorun.AutorunItem.running = property(lambda s: s.extra.get("demo_running", False))
backup.list_history = demo_history
backup.list_backups = lambda: []
wu.is_admin = lambda: True                    # hide the "not administrator" notes

from openuninstaller.gui import app as appmod  # noqa: E402  (after patching)
from openuninstaller.gui import pages_uninstall  # noqa: E402
from openuninstaller.gui.wizard import UninstallWizard  # noqa: E402

from openuninstaller.gui import pages_tools  # noqa: E402
from PySide6.QtGui import QIcon  # noqa: E402

pages_uninstall.programs.list_programs = demo_programs
# no real file icons: they would reveal which programs exist on the machine taking the screenshots
pages_uninstall.file_icon = pages_tools.file_icon = lambda _path: QIcon()


def main():
    os.makedirs(OUT, exist_ok=True)
    qapp = QApplication(sys.argv)
    saved_theme = settings.data.get("theme")

    def pump(s):
        end = time.time() + s
        while time.time() < end:
            qapp.processEvents()
            time.sleep(0.02)

    def shot(widget, name):
        path = os.path.join(OUT, name + ".png")
        widget.grab().save(path)
        print("saved", path)

    win = None
    for theme in ("light", "dark"):
        settings.data["theme"] = theme                       # in memory only
        appmod.apply_theme(qapp)
        if win is None:
            win = appmod.MainWindow()
            win.setWindowTitle("OpenUninstaller")
            win.resize(1280, 760)
            win.show()
            pump(1.5)
        win.goto("programs")
        win.pages["programs"].refresh()
        pump(1.0)
        shot(win, f"all-programs-{theme}")

        vlc = next(p for p in win.pages["programs"].progs if p.name == "VLC media player")
        w = UninstallWizard(win, "program", program=vlc)
        w.resize(1100, 700)
        w.show()
        reg, fs = vlc_leftovers()
        w.reg_tree.load(reg, check_created=True)
        w.fs_tree.load(fs, check_created=True)
        w.reg_page.count_label.setText(f"{len(reg)} registry items found, "
                                       f"{sum(1 for i in reg if i.created and not i.excluded)} created by the program.")
        w.fs_page.count_label.setText(f"{len(fs)} files/folders/other items found, "
                                      f"{sum(1 for i in fs if i.created and not i.excluded)} belong to the program.")
        pump(0.3)
        shot(w, f"wizard-setup-{theme}")
        w._set_step(2)
        pump(0.3)
        shot(w, f"leftovers-registry-{theme}")
        w._set_step(3)
        pump(0.3)
        shot(w, f"leftovers-files-{theme}")
        w._recorded = True                                # never write history from a screenshot run
        w.close()

        win.goto("autorun")
        win.pages["autorun"].refresh()
        pump(1.0)
        shot(win, f"autorun-{theme}")
        win.goto("uninstall_history")
        pump(0.5)
        shot(win, f"history-{theme}")
        win.goto("history_cleaner")
        pump(0.3)
        shot(win, f"history-cleaner-{theme}")
    settings.data["theme"] = saved_theme


if __name__ == "__main__":
    main()
