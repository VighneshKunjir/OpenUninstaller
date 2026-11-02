"""Render every page and the main dialogs in light and dark theme to PNG files (read-only).

Run:  .venv\\Scripts\\python tests\\ui_screenshots.py [output_folder]
"""
import os
import sys
import time

os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication, QMessageBox, QMenu  # noqa: E402

from openuninstaller.config import settings  # noqa: E402
from openuninstaller.gui import app as appmod  # noqa: E402
from openuninstaller.gui.options import OptionsDialog  # noqa: E402
from openuninstaller.gui.wizard import UninstallWizard  # noqa: E402
from openuninstaller.leftovers import Target, scan  # noqa: E402

OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(os.path.abspath(__file__)), "screenshots")
os.makedirs(OUT, exist_ok=True)
qapp = QApplication(sys.argv)


def pump(s):
    end = time.time() + s
    while time.time() < end:
        qapp.processEvents()
        time.sleep(0.02)


saved_theme = settings.data.get("theme")
win = None
for theme in ("light", "dark"):
    settings.data["theme"] = theme                       # in memory only
    appmod.apply_theme(qapp)
    if win is None:
        win = appmod.MainWindow()
        win.resize(1280, 800)
        win.show()
        for key in win.pages:                            # trigger lazy loads once
            win.goto(key)
            pump(0.2)
        pump(8)
    for key in win.pages:
        win.goto(key)
        pump(0.4)
        win.grab().save(os.path.join(OUT, f"{theme}_{key}.png"))
    progs = win.pages["programs"].progs
    p = next((x for x in progs if x.name == "Discord"), progs[0])
    w = UninstallWizard(win, "program", program=p)
    w.resize(1100, 720)
    w.show()
    pump(0.4)
    w.grab().save(os.path.join(OUT, f"{theme}_wizard_setup.png"))
    items = scan(Target.from_program(p), "advanced")      # read-only
    w.reg_tree.load([i for i in items if i.is_registry])
    w.fs_tree.load([i for i in items if not i.is_registry])
    w._set_step(2)
    pump(0.3)
    w.grab().save(os.path.join(OUT, f"{theme}_wizard_registry.png"))
    w._set_step(3)
    pump(0.3)
    w.grab().save(os.path.join(OUT, f"{theme}_wizard_files.png"))
    w._show_summary()
    pump(0.3)
    w.grab().save(os.path.join(OUT, f"{theme}_wizard_summary.png"))
    w._recorded = True                                    # do not write history from a screenshot run
    w.close()
    d = OptionsDialog(win)
    d.resize(820, 600)
    d.show()
    pump(0.3)
    d.grab().save(os.path.join(OUT, f"{theme}_options.png"))
    d.close()
    mb = QMessageBox(QMessageBox.Warning, "Leftovers not deleted", "5 leftover items have not been deleted yet.",
                     parent=win)
    mb.addButton("Delete 5 checked and continue", QMessageBox.AcceptRole)
    mb.addButton("Stay on this page", QMessageBox.RejectRole)
    mb.show()
    pump(0.3)
    mb.grab().save(os.path.join(OUT, f"{theme}_messagebox.png"))
    mb.close()
    m = QMenu(win)
    for t in ("Uninstall", "Quick Uninstall", "Open install folder"):
        m.addAction(t)
    m.popup(win.mapToGlobal(win.rect().center()))
    pump(0.3)
    m.grab().save(os.path.join(OUT, f"{theme}_menu.png"))
    m.close()
settings.data["theme"] = saved_theme
print("saved to", OUT)
