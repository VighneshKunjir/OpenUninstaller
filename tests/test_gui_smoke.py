"""Offscreen GUI smoke test: builds every page, waits for background loads, opens the dialogs.

Read-only - nothing is uninstalled or deleted.
Run:  .venv\\Scripts\\python tests\\test_gui_smoke.py
"""
import os
import sys
import time

os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication  # noqa: E402

from openuninstaller.gui import app as appmod, common  # noqa: E402
from openuninstaller.gui.options import OptionsDialog  # noqa: E402
from openuninstaller.gui.wizard import UninstallWizard  # noqa: E402

errors = []
common.error = lambda parent, msg: errors.append(msg)   # capture worker failures instead of showing popups


def main():
    qapp = QApplication(sys.argv)
    appmod.apply_theme(qapp)
    win = appmod.MainWindow()
    win.show()

    def pump(seconds):
        end = time.time() + seconds
        while time.time() < end:
            qapp.processEvents()
            time.sleep(0.02)

    for key in win.pages:
        win.goto(key)
        pump(0.3)
    pump(8)
    for key, page in win.pages.items():
        tbl = getattr(page, "table", None)
        print(f"{key:<20} rows={tbl.model.rowCount() if tbl else '-'}")
    progs = win.pages["programs"].progs
    for kind, kw in (("program", {"program": progs[0]}), ("forced", {"forced_names": "Discord"}),
                     ("forced_msi", {"program": next(p for p in progs if p.product_code)})):
        w = UninstallWizard(win, kind, **kw)
        w.show()
        pump(0.5)
        w.close()
    d = OptionsDialog(win)
    d.show()
    pump(0.3)
    d.close()
    win.hunter_mode()
    pump(0.3)
    win.hunter._open_main()
    pump(0.3)
    for e in errors:
        print(e[:1500])
    print("SMOKE OK" if not errors else f"SMOKE ERRORS: {len(errors)}")
    return not errors


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
