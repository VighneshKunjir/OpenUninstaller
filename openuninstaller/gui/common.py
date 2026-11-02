"""Shared GUI pieces: background workers, the leftovers tree, small helpers."""

from __future__ import annotations

import os
import traceback
import webbrowser
from typing import Callable
from urllib.parse import quote_plus

from PySide6.QtCore import QObject, QThread, Qt, Signal, QFileInfo, QSortFilterProxyModel
from PySide6.QtGui import QBrush, QFont, QIcon, QStandardItem, QStandardItemModel, QAction
from PySide6.QtWidgets import (QAbstractItemView, QFileIconProvider, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
                               QMenu, QMessageBox, QPushButton, QTableView, QTreeWidget, QTreeWidgetItem,
                               QVBoxLayout, QWidget, QToolButton)

from .. import winutil as wu
from ..config import settings
from ..leftovers import Leftover
from . import theme

# ---------------------------------------------------------------- workers


class Worker(QThread):
    """Runs fn(progress, cancelled) on a thread. Emits progress(str), done(result), failed(str)."""
    progress = Signal(str)
    done = Signal(object)
    failed = Signal(str)

    def __init__(self, fn: Callable, parent: QObject | None = None):
        super().__init__(parent)
        self.fn = fn
        self._cancel = False

    def cancel(self):
        self._cancel = True

    def run(self):
        try:
            import pythoncom
            pythoncom.CoInitialize()
        except Exception:
            pass
        try:
            res = self.fn(self.progress.emit, lambda: self._cancel)
            self.done.emit(res)
        except Exception as e:
            self.failed.emit(f"{e}\n\n{traceback.format_exc()}")


_workers: set[Worker] = set()


def run_bg(parent: QObject, fn: Callable, on_done: Callable | None = None, on_progress: Callable | None = None,
           on_error: Callable | None = None) -> Worker:
    w = Worker(fn, parent)
    _workers.add(w)
    if on_done:
        w.done.connect(on_done)
    if on_progress:
        w.progress.connect(on_progress)
    w.failed.connect(on_error or (lambda msg: error(parent if isinstance(parent, QWidget) else None, msg)))
    w.finished.connect(lambda: _workers.discard(w))
    w.start()
    return w


# ---------------------------------------------------------------- helpers

_icon_provider: QFileIconProvider | None = None


def file_icon(path: str) -> QIcon:
    global _icon_provider
    if not path or not os.path.exists(path):
        return QIcon()
    if path.lower().endswith(".ico"):
        return QIcon(path)
    if _icon_provider is None:
        _icon_provider = QFileIconProvider()
    return _icon_provider.icon(QFileInfo(path))


def error(parent, msg: str):
    box = QMessageBox(QMessageBox.Critical, "OpenUninstaller", msg.split("\n\n")[0], parent=parent)
    if "\n\n" in msg:
        box.setDetailedText(msg)
    box.exec()


def info(parent, msg: str):
    QMessageBox.information(parent, "OpenUninstaller", msg)


def confirm(parent, msg: str) -> bool:
    return QMessageBox.question(parent, "OpenUninstaller", msg) == QMessageBox.Yes


def web_search(text: str):
    webbrowser.open("https://www.google.com/search?q=" + quote_plus(text))


def button(text: str, slot=None, tip: str = "", primary: bool = False) -> QPushButton:
    b = QPushButton(text)
    if slot:
        b.clicked.connect(slot)
    if tip:
        b.setToolTip(tip)
    if primary:
        b.setObjectName("primary")
    return b


def menu_button(text: str, actions: list[tuple[str, Callable] | None]) -> QToolButton:
    b = QToolButton()
    b.setText(text)
    b.setPopupMode(QToolButton.InstantPopup)
    m = QMenu(b)
    for a in actions:
        if a is None:
            m.addSeparator()
        else:
            m.addAction(a[0], a[1])
    b.setMenu(m)
    return b


class SearchTable(QWidget):
    """A sortable, filterable table on top of a QStandardItemModel."""

    def __init__(self, headers: list[str], parent=None, checkable: bool = False):
        super().__init__(parent)
        self.model = QStandardItemModel(0, len(headers), self)
        self.model.setHorizontalHeaderLabels(headers)
        self.proxy = QSortFilterProxyModel(self)
        self.proxy.setSourceModel(self.model)
        self.proxy.setFilterCaseSensitivity(Qt.CaseInsensitive)
        self.proxy.setFilterKeyColumn(-1)
        self.proxy.setSortRole(Qt.UserRole + 2)
        self.view = QTableView()
        self.view.setModel(self.proxy)
        self.view.setSortingEnabled(True)
        self.view.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.view.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.view.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.view.verticalHeader().hide()
        self.view.setAlternatingRowColors(True)
        self.view.setWordWrap(False)
        self.view.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.view.horizontalHeader().setStretchLastSection(True)
        self.view.setContextMenuPolicy(Qt.CustomContextMenu)
        self.checkable = checkable
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.view)
        self.objects: list = []

    def set_rows(self, rows: list[tuple[object, list, QIcon | None]]):
        """rows: (object, [cell values], icon). Cell values may be (display, sort_key)."""
        self.model.removeRows(0, self.model.rowCount())
        self.objects = []
        for obj, cells, icon in rows:
            items = []
            for i, c in enumerate(cells):
                disp, key = c if isinstance(c, tuple) else (c, c)
                it = QStandardItem("" if disp is None else str(disp))
                it.setData(key if key is not None else "", Qt.UserRole + 2)
                if isinstance(key, str):
                    it.setData(key.lower(), Qt.UserRole + 2)
                if i == 0:
                    it.setData(len(self.objects), Qt.UserRole + 1)
                    if icon is not None:
                        it.setIcon(icon)
                    if self.checkable:
                        it.setCheckable(True)
                items.append(it)
            self.objects.append(obj)
            self.model.appendRow(items)
        self.view.resizeColumnsToContents()
        if not rows:
            self.view.setColumnWidth(0, 420)
        for col in range(self.model.columnCount()):
            if self.view.columnWidth(col) > 380:
                self.view.setColumnWidth(col, 380)

    def obj_at(self, proxy_row: int):
        idx = self.proxy.index(proxy_row, 0)
        return self.objects[self.proxy.data(idx, Qt.UserRole + 1)]

    def selected(self) -> list:
        rows = sorted({i.row() for i in self.view.selectionModel().selectedRows()})
        return [self.obj_at(r) for r in rows]

    def current(self):
        s = self.selected()
        return s[0] if s else None

    def checked(self) -> list:
        out = []
        for r in range(self.model.rowCount()):
            it = self.model.item(r, 0)
            if it.checkState() == Qt.Checked:
                out.append(self.objects[it.data(Qt.UserRole + 1)])
        return out

    def set_checked(self, obj, state: bool):
        for r in range(self.model.rowCount()):
            it = self.model.item(r, 0)
            if self.objects[it.data(Qt.UserRole + 1)] is obj:
                it.setCheckState(Qt.Checked if state else Qt.Unchecked)

    def check_all(self, state: bool):
        for r in range(self.model.rowCount()):
            self.model.item(r, 0).setCheckState(Qt.Checked if state else Qt.Unchecked)

    def row_item(self, obj) -> QStandardItem | None:
        for r in range(self.model.rowCount()):
            it = self.model.item(r, 0)
            if self.objects[it.data(Qt.UserRole + 1)] is obj:
                return it
        return None


def search_box(table: SearchTable, placeholder: str = "Search...") -> QLineEdit:
    e = QLineEdit()
    e.setPlaceholderText(placeholder)
    e.setClearButtonEnabled(True)
    e.setMinimumWidth(260)
    e.textChanged.connect(table.proxy.setFilterFixedString)
    return e


class PageHeader(QWidget):
    def __init__(self, title: str, description: str):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 4)
        t = QLabel(title)
        t.setObjectName("pageTitle")
        d = QLabel(description)
        d.setWordWrap(True)
        d.setObjectName("pageDesc")
        lay.addWidget(t)
        lay.addWidget(d)


def toolbar(*widgets) -> QHBoxLayout:
    lay = QHBoxLayout()
    for w in widgets:
        if w == "stretch":
            lay.addStretch(1)
        else:
            lay.addWidget(w)
    return lay


# ---------------------------------------------------------------- leftovers tree

ROLE_ITEM = Qt.UserRole + 10


class LeftoverTree(QTreeWidget):
    """Hierarchical, checkable view of leftovers.

    Bold   = created by the program (will be deleted when checked)
    Red    = excluded / protected (never deleted)
    Normal = context only, or uncertain - mark it as created to delete it.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setHeaderLabels(["Item", "Details"])
        self.header().setSectionResizeMode(0, QHeaderView.Interactive)
        self.setColumnWidth(0, 620)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._menu)
        self.items: list[Leftover] = []

    def load(self, items: list[Leftover], check_created: bool | None = None):
        check_created = settings["check_all_leftovers"] if check_created is None else check_created
        self.clear()
        self.items = items
        nodes: dict[str, QTreeWidgetItem] = {}
        # Parents first so children can nest inside an item that is itself a leftover
        ordered = sorted(items, key=lambda i: (len(i.path), i.value_name is not None))
        for it in ordered:
            key_path = it.path
            parent = self._container_for(key_path, nodes, it)
            if it.kind == "regvalue":
                node = QTreeWidgetItem(parent, [it.value_name or "(Default)", it.extra.get("data", "")])
            else:
                label = it.path if parent is self.invisibleRootItem() or parent.data(0, ROLE_ITEM) is None \
                    else it.path[len(parent.data(0, Qt.UserRole + 11)):].lstrip("\\")
                details = it.reason + (f"  -  {wu.human_size(it.size)}" if it.size else "")
                node = QTreeWidgetItem(parent, [label, details])
                node.setData(0, Qt.UserRole + 11, it.path)
                nodes[it.path.lower()] = node
            node.setData(0, ROLE_ITEM, it)
            node.setToolTip(0, f"{it.path}\n{it.reason}")
            node.setFlags(node.flags() | Qt.ItemIsUserCheckable | Qt.ItemIsAutoTristate)
            node.setCheckState(0, Qt.Checked if (check_created and it.created and not it.excluded) else Qt.Unchecked)
            self._style(node, it)
        self.expandAll()

    def _container_for(self, path: str, nodes: dict, it: Leftover) -> QTreeWidgetItem:
        low = path.lower()
        if it.kind == "regvalue":
            if low in nodes:
                return nodes[low]
            # synthetic grey node for the key that holds the value
            node = QTreeWidgetItem(self._container_for(path, {k: v for k, v in nodes.items() if k != low},
                                                       Leftover("regkey", path, "")), [path, "contains values"])
            node.setData(0, Qt.UserRole + 11, path)
            node.setForeground(0, QBrush(theme.color("faint")))
            node.setFlags(node.flags() | Qt.ItemIsUserCheckable | Qt.ItemIsAutoTristate)
            node.setCheckState(0, Qt.Unchecked)
            nodes[low] = node
            return node
        best = None
        for k, node in nodes.items():
            if low.startswith(k + "\\") and (best is None or len(k) > len(best[0])):
                best = (k, node)
        return best[1] if best else self.invisibleRootItem()

    def _style(self, node: QTreeWidgetItem, it: Leftover):
        f = QFont(node.font(0))
        f.setBold(it.created and not it.excluded)
        node.setFont(0, f)
        if it.excluded:
            node.setForeground(0, QBrush(theme.color("danger")))
        elif not it.created:
            node.setForeground(0, QBrush(theme.color("muted")))
        else:
            node.setForeground(0, QBrush())

    def _all_nodes(self):
        stack = [self.invisibleRootItem()]
        while stack:
            n = stack.pop()
            for i in range(n.childCount()):
                c = n.child(i)
                stack.append(c)
                yield c

    def set_all(self, state: bool):
        for i in range(self.topLevelItemCount()):
            self.topLevelItem(i).setCheckState(0, Qt.Checked if state else Qt.Unchecked)

    def checked_items(self) -> list[Leftover]:
        """Only checked + bold (created) + not excluded items are returned for deletion."""
        out = []
        for n in self._all_nodes():
            it: Leftover | None = n.data(0, ROLE_ITEM)
            if it and n.checkState(0) == Qt.Checked and it.created and not it.excluded:
                out.append(it)
        return out

    def _menu(self, pos):
        node = self.itemAt(pos)
        m = QMenu(self)
        m.addAction("Expand all", self.expandAll)
        m.addAction("Collapse all", self.collapseAll)
        m.addAction("Check all", lambda: self.set_all(True))
        m.addAction("Uncheck all", lambda: self.set_all(False))
        it: Leftover | None = node.data(0, ROLE_ITEM) if node else None
        if it:
            m.addSeparator()
            if it.is_registry:
                m.addAction("Open in Registry Editor", lambda: wu.open_in_regedit(it.path))
            elif it.kind in ("file", "folder"):
                m.addAction("Open containing folder", lambda: wu.open_folder(it.path))
                m.addAction("Properties", lambda: wu.show_properties(it.path))
            m.addAction("Search the web", lambda: web_search(os.path.basename(it.path)))
            m.addSeparator()
            if not it.created and not it.excluded:
                m.addAction("Mark as created (allow deletion)", lambda: self._mark(node, it))
            if not it.excluded:
                m.addAction("Add to exclude list", lambda: self._exclude(node, it))
            m.addAction("Copy path", lambda: _copy(it.path + (f"\\{it.value_name}" if it.value_name else "")))
        m.exec(self.viewport().mapToGlobal(pos))

    def _mark(self, node, it: Leftover):
        it.created = True
        self._style(node, it)
        node.setCheckState(0, Qt.Checked)

    def _exclude(self, node, it: Leftover):
        key = "reg_excludes" if it.is_registry else "folder_excludes"
        lst = list(settings[key])
        lst.append(it.path)
        settings[key] = lst
        it.excluded = True
        node.setCheckState(0, Qt.Unchecked)
        self._style(node, it)


def _copy(text: str):
    from PySide6.QtWidgets import QApplication
    QApplication.clipboard().setText(text)


def make_action(parent, text, slot, shortcut=None) -> QAction:
    a = QAction(text, parent)
    a.triggered.connect(slot)
    if shortcut:
        a.setShortcut(shortcut)
    return a
