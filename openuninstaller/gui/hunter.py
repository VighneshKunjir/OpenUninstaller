"""Hunter Mode: drag the target onto any window to uninstall, stop, kill or locate its program."""

from __future__ import annotations

import os

import psutil
from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtGui import QColor, QCursor, QPainter, QPen
from PySide6.QtWidgets import QMenu, QToolTip, QWidget

from .. import autorun, winutil as wu
from . import theme
from .common import confirm, info, web_search


def process_at(pos: QPoint) -> psutil.Process | None:
    import win32gui
    import win32process
    hwnd = win32gui.WindowFromPoint((pos.x(), pos.y()))
    if not hwnd:
        return None
    root = win32gui.GetAncestor(hwnd, 2)  # GA_ROOT
    _tid, pid = win32process.GetWindowThreadProcessId(root or hwnd)
    if pid == os.getpid():
        return None
    try:
        return psutil.Process(pid)
    except psutil.Error:
        return None


class HunterWindow(QWidget):
    open_main = Signal()
    forced_uninstall = Signal(str, str)   # name, exe path

    def __init__(self):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setWindowOpacity(0.85)
        self.resize(72, 72)
        geo = self.screen().availableGeometry()
        self.move(geo.right() - 110, geo.top() + 40)
        self.dragging = False
        self.offset = None
        self.setToolTip("Hunter Mode - drag the target onto a program window.\nRight-click for options.")

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        c = theme.color("accent")
        fill = QColor(c)
        fill.setAlpha(60)
        p.setBrush(fill)
        p.setPen(QPen(c, 3))
        r = self.rect().adjusted(6, 6, -6, -6)
        p.drawEllipse(r)
        p.drawEllipse(r.adjusted(16, 16, -16, -16))
        cx, cy = self.width() // 2, self.height() // 2
        p.drawLine(cx, 2, cx, self.height() - 2)
        p.drawLine(2, cy, self.width() - 2, cy)

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            if e.modifiers() & Qt.ShiftModifier:          # Shift+drag moves the target window itself
                self.offset = e.position().toPoint()
                return
            self.dragging = True
            self.grabMouse(QCursor(Qt.CrossCursor))
        elif e.button() == Qt.RightButton:
            m = QMenu(self)
            m.addAction("Open main window", self._open_main)
            m.addAction("Exit Hunter Mode", self._open_main)
            m.exec(e.globalPosition().toPoint())

    def mouseMoveEvent(self, e):
        if self.offset is not None:
            self.move(e.globalPosition().toPoint() - self.offset)
            return
        if self.dragging:
            proc = process_at(e.globalPosition().toPoint())
            if proc:
                try:
                    QToolTip.showText(e.globalPosition().toPoint() + QPoint(16, 16), f"{proc.name()}\n{proc.exe()}")
                except psutil.Error:
                    pass

    def mouseReleaseEvent(self, e):
        if self.offset is not None:
            self.offset = None
            return
        if not self.dragging:
            return
        self.dragging = False
        self.releaseMouse()
        pos = e.globalPosition().toPoint()
        proc = process_at(pos)
        if not proc:
            return
        try:
            exe, name = proc.exe(), proc.name()
        except psutil.Error:
            return
        if name.lower() == "explorer.exe":
            info(self, "That is Windows Explorer (desktop / taskbar). For desktop icons, right-click the "
                       "shortcut and choose 'Uninstall with OpenUninstaller' (enable it in Options).")
            return
        meta = wu.file_version_info(exe)
        title = meta.get("ProductName") or meta.get("FileDescription") or name
        m = QMenu(self)
        m.addSection(title)
        m.addAction("Uninstall", lambda: self.forced_uninstall.emit(title, exe))
        m.addAction("Stop auto starting", lambda: self._stop_autostart(exe))
        m.addAction("Kill", lambda: self._kill(proc))
        m.addAction("Kill and delete", lambda: self._kill_delete(proc, exe))
        m.addAction("Open containing folder", lambda: wu.open_folder(exe))
        m.addAction("Search the web", lambda: web_search(title))
        m.addAction("Properties", lambda: wu.show_properties(exe))
        m.addAction("Cancel", lambda: None)
        m.exec(pos)

    def _open_main(self):
        self.hide()
        self.open_main.emit()

    def _stop_autostart(self, exe: str):
        n = 0
        for it in autorun.list_autoruns(include_microsoft=True):
            if it.exe and wu.norm_path(it.exe) == wu.norm_path(exe) and it.enabled:
                if autorun.set_enabled(it, False)[0]:
                    n += 1
        info(self, f"Disabled {n} autorun entr{'y' if n == 1 else 'ies'}." if n else
             "This program does not start automatically.")

    def _kill(self, proc):
        try:
            proc.kill()
        except psutil.Error as e:
            info(self, f"Could not stop it: {e}")

    def _kill_delete(self, proc, exe):
        if not confirm(self, f"Stop the program and move\n{exe}\nto the Recycle Bin?"):
            return
        self._kill(proc)
        try:
            proc.wait(5)
        except psutil.Error:
            pass
        try:
            from send2trash import send2trash
            send2trash(exe)
        except Exception as e:
            info(self, f"Could not delete: {e}")
