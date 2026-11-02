"""Main window."""

from __future__ import annotations

import os
import sys

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QIcon, QKeySequence, QShortcut
from PySide6.QtWidgets import (QApplication, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QMainWindow,
                               QMessageBox, QStackedWidget, QVBoxLayout, QWidget)

from .. import APP_NAME, __version__, winutil as wu
from ..config import settings
from .common import button
from .hunter import HunterWindow
from .options import OptionsDialog
from .theme import apply_theme
from .pages_tools import (AutorunPage, BackupManagerPage, EvidenceRemoverPage, HistoryCleanerPage, JunkPage,
                          UninstallHistoryPage, UnrecoverableDeletePage, WindowsToolsPage)
from .pages_uninstall import AllProgramsPage, BrowserExtensionsPage, TracedProgramsPage, WindowsAppsPage
from .wizard import UninstallWizard

SECTIONS = [
    ("UNINSTALLER", None),
    ("All Programs", "programs"), ("Traced Programs", "traced"), ("Windows Apps", "apps"),
    ("Browser Extensions", "extensions"),
    ("TOOLS", None),
    ("Autorun Manager", "autorun"), ("Junk Files Cleaner", "junk"), ("History Cleaner", "history_cleaner"),
    ("Evidence Remover", "evidence"), ("Unrecoverable Delete", "shred"), ("Windows Tools", "wintools"),
    ("Backup Manager", "backups"), ("Uninstall History", "uninstall_history"),
]


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} {__version__}" + ("" if wu.is_admin() else "  (limited - not administrator)"))
        self.resize(1280, 800)
        root = QWidget()
        h = QHBoxLayout(root)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(0)
        side_w = QWidget()
        side_w.setObjectName("sideFooter")
        side_w.setFixedWidth(230)
        side = QVBoxLayout(side_w)
        side.setContentsMargins(0, 0, 0, 0)
        side.setSpacing(0)
        brand = QLabel(f"{APP_NAME}")
        brand.setObjectName("brand")
        side.addWidget(brand)
        self.nav = QListWidget()
        self.nav.setObjectName("sidebar")
        self.nav.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        side.addWidget(self.nav, 1)
        footer = QWidget()
        footer.setObjectName("sideFooter")
        fl = QVBoxLayout(footer)
        fl.addWidget(button("Hunter Mode", self.hunter_mode, "Drag a target onto any window to manage its program"))
        fl.addWidget(button("Options", self.options))
        fl.addWidget(button("About", self.about))
        side.addWidget(footer)
        h.addWidget(side_w)
        self.stack = QStackedWidget()
        self.stack.setObjectName("content")
        wrap = QWidget()
        wl = QVBoxLayout(wrap)
        wl.setContentsMargins(18, 14, 18, 12)
        wl.addWidget(self.stack)
        h.addWidget(wrap, 1)
        self.setCentralWidget(root)

        self.pages = {
            "programs": AllProgramsPage(), "traced": TracedProgramsPage(), "apps": WindowsAppsPage(),
            "extensions": BrowserExtensionsPage(), "autorun": AutorunPage(), "junk": JunkPage(),
            "history_cleaner": HistoryCleanerPage(), "evidence": EvidenceRemoverPage(),
            "shred": UnrecoverableDeletePage(), "wintools": WindowsToolsPage(), "backups": BackupManagerPage(),
            "uninstall_history": UninstallHistoryPage(),
        }
        self.page_index = {}
        for title, key in SECTIONS:
            it = QListWidgetItem(title)
            if key is None:
                it.setFlags(Qt.NoItemFlags)
                f = it.font()
                f.setPointSize(8)
                f.setBold(True)
                it.setFont(f)
            else:
                it.setData(Qt.UserRole, key)
                self.page_index[key] = self.stack.addWidget(self.pages[key])
            self.nav.addItem(it)
        self.nav.currentItemChanged.connect(self._nav)
        self.pages["programs"].go_history.connect(lambda: self.goto("uninstall_history"))
        self.pages["programs"].go_traced.connect(self._trace_from_programs)
        self.goto("programs")
        QShortcut(QKeySequence("F5"), self, self._refresh_current)
        QShortcut(QKeySequence("Ctrl+F"), self, self._focus_search)
        self.hunter = None

    def _nav(self, cur, _prev):
        key = cur.data(Qt.UserRole) if cur else None
        if key:
            self.stack.setCurrentIndex(self.page_index[key])

    def goto(self, key: str):
        for i in range(self.nav.count()):
            if self.nav.item(i).data(Qt.UserRole) == key:
                self.nav.setCurrentRow(i)

    def _refresh_current(self):
        page = self.stack.currentWidget()
        if hasattr(page, "refresh"):
            page.refresh()

    def _focus_search(self):
        from PySide6.QtWidgets import QLineEdit
        edits = self.stack.currentWidget().findChildren(QLineEdit)
        if edits:
            edits[-1].setFocus()

    def _trace_from_programs(self):
        self.goto("traced")
        self.pages["traced"].trace_install()

    def hunter_mode(self):
        if self.hunter is None:
            self.hunter = HunterWindow()
            self.hunter.open_main.connect(self._from_hunter)
            self.hunter.forced_uninstall.connect(self._hunter_uninstall)
        self.hide()
        self.hunter.show()

    def _from_hunter(self):
        self.showNormal()
        self.activateWindow()

    def _hunter_uninstall(self, name: str, exe: str):
        from .. import programs
        progs = programs.find_by_location(exe)
        if progs:
            UninstallWizard(None, "program", program=progs[0]).exec()
        else:
            UninstallWizard(None, "forced", forced_names=name, forced_paths=[exe]).exec()

    def options(self):
        if OptionsDialog(self).exec():
            apply_theme(QApplication.instance())
            self.pages["programs"].refresh()

    def about(self):
        QMessageBox.about(self, f"About {APP_NAME}",
                          f"<h3>{APP_NAME} {__version__}</h3><p>A free, open-source uninstaller for Windows: "
                          f"removes programs completely, including leftover files, folders and registry "
                          f"entries.</p><p>MIT licensed. No subscription, no telemetry.</p>"
                          f"<p>Data folder: {os.path.dirname(settings.path)}</p>")


def main():
    argv = sys.argv[1:]
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    icon = os.path.join(os.path.dirname(os.path.abspath(__file__)), "resources", "app.ico")
    if os.path.exists(icon):
        app.setWindowIcon(QIcon(icon))
    try:   # own taskbar group + icon instead of python.exe's
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("OpenUninstaller.App")
    except Exception:
        pass
    apply_theme(app)
    if not wu.is_admin() and "--no-elevate" not in argv:
        ans = QMessageBox.question(
            None, APP_NAME, "OpenUninstaller works best as administrator (needed to remove programs installed for "
                            "all users, services, and to create restore points).\n\nRestart as administrator?",
            QMessageBox.Yes | QMessageBox.No)
        # The elevated process starts in System32, so relaunch through absolute paths
        script = wu.self_command()[1:]          # [] for the .exe, [launcher.pyw] from source
        if ans == QMessageBox.Yes and wu.relaunch_as_admin(script + ["--no-elevate"] + argv):
            return
    win = MainWindow()
    win.show()
    selftest = os.environ.get("OPENUNINSTALLER_SELFTEST")
    if selftest:   # build check: render the window to a PNG and exit (used to verify the packaged .exe)
        QTimer.singleShot(4000, lambda: (win.grab().save(selftest), app.quit()))
    if "--forced" in argv:
        target = argv[argv.index("--forced") + 1] if len(argv) > argv.index("--forced") + 1 else ""
        from .. import programs
        target_exe = target
        if target.lower().endswith(".lnk"):
            target_exe = wu.resolve_shortcut(target) or target
        progs = programs.find_by_location(target_exe) if target_exe else []
        QTimer.singleShot(200, lambda: (UninstallWizard(win, "program", program=progs[0]) if progs else
                                        UninstallWizard(win, "forced", forced_names=os.path.splitext(
                                            os.path.basename(target_exe.rstrip("\\")))[0],
                                                        forced_paths=[target_exe])).exec())
    elif "--trace" in argv:
        installer = argv[argv.index("--trace") + 1]
        from .. import tracer
        win.goto("traced")
        page = win.pages["traced"]
        session = tracer.TraceSession(installer, os.path.splitext(os.path.basename(installer))[0])
        from .common import run_bg
        QTimer.singleShot(200, lambda: run_bg(page, lambda p, c: session.start(p),
                                              lambda _r: page._show_bar(session, session.name)))
    sys.exit(app.exec())
