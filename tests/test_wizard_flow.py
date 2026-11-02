"""Wizard navigation test: the 'leftovers not deleted' popup, Back from the summary, history written once.

Uses its own throw-away HKCU key and temp folder (OUWizTest*). The popup is scripted.
Run:  .venv\\Scripts\\python tests\\test_wizard_flow.py
"""
import os
import shutil
import sys
import tempfile
import time
import winreg

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication  # noqa: E402

from openuninstaller import backup, winutil as wu  # noqa: E402
from openuninstaller.config import settings  # noqa: E402
from openuninstaller.gui import wizard as wz  # noqa: E402
from openuninstaller.leftovers import Leftover  # noqa: E402

HKCU = winreg.HKEY_CURRENT_USER
KEY = r"Software\OUWizTest"


class FakeBox:
    """Stands in for QMessageBox: records the offered buttons and 'clicks' the scripted one."""
    script: list[str] = []
    shown: list[list[str]] = []
    Warning = AcceptRole = DestructiveRole = RejectRole = 0

    def __init__(self, *a, **k):
        self.buttons = {}

    def addButton(self, text, _role):
        token = object()
        self.buttons[token] = text
        return token

    def setDefaultButton(self, _b):
        pass

    def exec(self):
        FakeBox.shown.append(list(self.buttons.values()))
        want = FakeBox.script.pop(0)
        self.choice = next(t for t, label in self.buttons.items() if label.lower().startswith(want))

    def clickedButton(self):
        return self.choice


results = []


def check(label, cond):
    results.append(bool(cond))
    print(("PASS " if cond else "FAIL ") + label)


def main():
    app = QApplication(sys.argv)
    wz.QMessageBox = FakeBox
    wz.confirm = lambda *a: True
    wz.info = lambda *a: None
    settings.data["file_delete_mode"] = "permanent"     # in memory only
    folder = tempfile.mkdtemp(prefix="OUWizTest")
    wu.set_value(HKCU, KEY + r"\App", "x", winreg.REG_SZ, "1")
    before = {h["id"] for h in backup.list_history()}

    def pump(sec=0.2, until=None):
        end = time.time() + 15
        while time.time() < end:
            app.processEvents()
            time.sleep(0.02)
            if until is None and time.time() > end - 15 + sec:
                return
            if until is not None and until():
                return

    w = wz.UninstallWizard(None, "forced", forced_names="OUWizTest")
    try:
        w.show()
        reg = [Leftover("regkey", wu.join_reg_path(HKCU, KEY), "test", True, hive=HKCU, sub=KEY)]
        fs = [Leftover("folder", folder, "test", True)]
        w.reg_tree.load(reg)
        w.fs_tree.load(fs)
        w._set_step(2)

        FakeBox.script = ["stay"]
        w._next_from_tree()
        check("popup shown when leaving with undeleted leftovers", len(FakeBox.shown) == 1)
        check("popup offers delete / continue / stay",
              [b.split()[0] for b in FakeBox.shown[0]] == ["Delete", "Continue", "Stay"])
        check("'Stay' keeps you on the registry page", w.stack.currentIndex() == 2)

        FakeBox.script = ["continue"]
        w._next_from_tree()
        check("'Continue without deleting' goes to files page", w.stack.currentIndex() == 3)
        check("files page has a Back button", w.fs_page.back_button.isVisible())
        check("registry key still exists", wu.key_exists(HKCU, KEY))

        FakeBox.script = ["delete"]
        w._next_from_tree()
        pump(until=lambda: w.stack.currentIndex() == 4)
        check("'Delete ... and continue' deleted the folder", not os.path.exists(folder))
        check("...and moved on to the summary", w.stack.currentIndex() == 4)
        check("summary warns about the leftover left behind", "1 leftover item(s) were not deleted" in w.summary.text())
        check("summary has Back to leftovers", w.summary_back.isVisible())

        w._back_from_summary()
        check("Back returns to the page with the remaining leftover", w.stack.currentIndex() == 2)
        w.reg_tree.set_all(True)
        w._delete(w.reg_tree, ask=False)
        pump(until=lambda: not w.reg_tree.items)
        check("registry key deleted after going back", not wu.key_exists(HKCU, KEY))
        w._next_from_tree()          # nothing left anywhere -> straight to the summary, no popup
        pump(0.3)
        check("no popup once everything is deleted", len(FakeBox.shown) == 3)
        check("summary no longer warns", w.stack.currentIndex() == 4 and "were not deleted" not in w.summary.text())

        w.accept()
        new = [h for h in backup.list_history() if h["id"] not in before]
        check("history recorded exactly once on Finish", len(new) == 1)
        check("history contains both deletions", new and new[0]["ok"] == 2)
    finally:
        try:
            wu.delete_key_tree(HKCU, KEY)
        except OSError:
            pass
        shutil.rmtree(folder, ignore_errors=True)
        for h in backup.list_history():
            if h["id"] not in before:
                backup.delete_history(h["id"])
        for m in backup.list_backups():
            if m["program"] == "Forced uninstall":
                shutil.rmtree(os.path.join(backup.BACKUP_DIR, m["id"]), ignore_errors=True)
    print("\nALL PASSED" if all(results) else "\nSOME CHECKS FAILED")
    return all(results)


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
