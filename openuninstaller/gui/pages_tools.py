"""Tools: Autorun Manager, Junk Files Cleaner, History Cleaner, Evidence Remover, Unrecoverable Delete,
Windows Tools, Backup Manager, Uninstall History."""

from __future__ import annotations

import os
import shutil

from PySide6.QtCore import Qt, QDate
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDateEdit, QDialog, QFileDialog, QGridLayout, QHBoxLayout,
                               QInputDialog, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMenu,
                               QPlainTextEdit, QProgressBar, QPushButton, QTreeWidget,
                               QTreeWidgetItem, QVBoxLayout, QWidget, QAbstractItemView)

from .. import autorun, backup, tools, winutil as wu
from ..config import settings
from ..leftovers import is_protected_path
from .common import (PageHeader, SearchTable, button, confirm, info, menu_button, run_bg, search_box, toolbar,
                     web_search, file_icon)


# ================================================================ Autorun Manager


class AutorunPage(QWidget):
    def __init__(self):
        super().__init__()
        v = QVBoxLayout(self)
        v.addWidget(PageHeader("Autorun Manager", "Programs, services and scheduled tasks that start with Windows. "
                                                  "Uncheck an item to stop it starting (easily reversed); remove it "
                                                  "only when you are sure. Removed items are backed up."))
        self.table = SearchTable(["Name", "Status", "Type", "Location", "Publisher", "Description", "Command"],
                                 checkable=True)
        self.table.model.itemChanged.connect(self._toggled)
        self.cb_ms = QCheckBox("Show Microsoft items")
        self.cb_ms.toggled.connect(self.refresh)
        v.addLayout(toolbar(
            button("Remove", self._remove), button("Add...", self._add),
            menu_button("More", [("Run process", lambda: self._each(autorun.run)),
                                 ("Kill process", lambda: self._each(autorun.kill)),
                                 ("Open containing folder", lambda: [wu.open_folder(i.exe) for i in self.table.selected()[:1]]),
                                 ("Go to location", self._goto), ("Properties", self._props),
                                 ("Search the web", lambda: [web_search(i.name) for i in self.table.selected()[:1]]),
                                 None, ("Remove all invalid entries", self._remove_invalid),
                                 ("Remove all disabled entries", self._remove_disabled),
                                 None, ("Open Windows Services", lambda: tools.launch_tool("services.msc")),
                                 ("Refresh", self.refresh)]),
            self.cb_ms, "stretch", search_box(self.table)))
        v.addWidget(self.table, 1)
        self.status = QLabel()
        v.addWidget(self.status)
        self._loading = False
        self.loaded = False

    def showEvent(self, e):
        super().showEvent(e)
        if not self.loaded:
            self.loaded = True
            self.refresh()

    def refresh(self):
        self.status.setText("Loading...")
        inc = self.cb_ms.isChecked()
        run_bg(self, lambda p, c: autorun.list_autoruns(include_microsoft=inc), self._loaded)

    def _loaded(self, items):
        self._loading = True
        rows = []
        for it in items:
            status = ("Running" if it.running else "Not running") if it.valid else "Invalid (file missing)"
            rows.append((it, [it.name, status, it.kind.title(), it.location, it.publisher, it.description,
                              it.command], file_icon(it.exe)))
        self.table.set_rows(rows)
        self.table.view.sortByColumn(0, Qt.AscendingOrder)
        for it in items:
            row = self.table.row_item(it)
            row.setCheckState(Qt.Checked if it.enabled else Qt.Unchecked)
        self._loading = False
        self.status.setText(f"{len(items)} entries, {sum(1 for i in items if i.enabled)} enabled")

    def _toggled(self, item):
        if self._loading or item.column() != 0:
            return
        obj = self.table.objects[item.data(Qt.UserRole + 1)]
        want = item.checkState() == Qt.Checked
        if want == obj.enabled:
            return
        ok, err = autorun.set_enabled(obj, want)
        if not ok:
            info(self, f"Could not change {obj.name}: {err}")
            self._loading = True
            item.setCheckState(Qt.Checked if obj.enabled else Qt.Unchecked)
            self._loading = False

    def _each(self, fn):
        for it in self.table.selected():
            fn(it)

    def _remove_items(self, items):
        if items and confirm(self, f"Remove {len(items)} autorun entr{'y' if len(items) == 1 else 'ies'}?\n"
                                   "(A backup is kept in the Backup Manager.)"):
            m = autorun.remove(items)
            failed = [i for i in m["items"] if i["status"] == "failed"]
            if failed:
                info(self, "Some entries could not be removed:\n" + "\n".join(f"{i['path']}: {i['detail']}" for i in failed))
            self.refresh()

    def _remove(self):
        self._remove_items(self.table.selected())

    def _remove_invalid(self):
        self._remove_items([i for i in self.table.objects if not i.valid and i.kind in ("registry", "folder")])

    def _remove_disabled(self):
        self._remove_items([i for i in self.table.objects if not i.enabled])

    def _goto(self):
        it = self.table.current()
        if not it:
            return
        if it.kind == "registry":
            wu.open_in_regedit(wu.wow_display(it.extra["hive"], it.extra["sub"], it.extra["view"]))
        elif it.kind == "folder":
            wu.open_folder(it.extra["file"])
        elif it.kind == "service":
            tools.launch_tool("services.msc")
        else:
            tools.launch_tool("taskschd.msc")

    def _props(self):
        it = self.table.current()
        if it and it.valid:
            wu.show_properties(it.exe)

    def _add(self):
        d = QDialog(self)
        d.setWindowTitle("Add autorun entry")
        v = QVBoxLayout(d)
        name = QLineEdit()
        cmd = QLineEdit()
        cmd.setPlaceholderText('"C:\\Path\\Program.exe" /args')
        v.addWidget(QLabel("Name:"))
        v.addWidget(name)
        v.addWidget(QLabel("Command (full path, quote it when adding arguments):"))
        row = QHBoxLayout()
        row.addWidget(cmd)
        row.addWidget(button("Browse...", lambda: cmd.setText('"' + os.path.normpath(
            QFileDialog.getOpenFileName(d, "Program", "", "Programs (*.exe)")[0] or "") + '"')))
        v.addLayout(row)
        all_users = QCheckBox("For all users (needs administrator)")
        v.addWidget(all_users)
        where = QComboBox()
        where.addItems(["Registry: Run (every startup)", "Registry: RunOnce (next startup only)", "Startup folder"])
        v.addWidget(where)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(button("Cancel", d.reject))
        row.addWidget(button("Add", d.accept, primary=True))
        v.addLayout(row)
        if d.exec() and name.text() and cmd.text().strip('"'):
            try:
                autorun.add(name.text(), cmd.text(), all_users.isChecked(),
                            ["run", "runonce", "folder"][where.currentIndex()])
            except OSError as e:
                info(self, f"Could not add: {e}")
            self.refresh()


# ================================================================ Junk Files Cleaner


class JunkPage(QWidget):
    def __init__(self):
        super().__init__()
        v = QVBoxLayout(self)
        v.addWidget(PageHeader("Junk Files Cleaner", "Find temporary and leftover junk files. Choose drives (or a "
                                                     "folder) and press Scan. Patterns, exclusions and always-clean "
                                                     "folders are set in Options."))
        self.drives = QHBoxLayout()
        self.drive_boxes = []
        for d in tools.fixed_drives():
            cb = QCheckBox(d)
            cb.setChecked(d.upper().startswith(os.environ.get("SystemDrive", "C:").upper()))
            self.drive_boxes.append(cb)
            self.drives.addWidget(cb)
        self.drives.addStretch(1)
        self.cb_cloud = QCheckBox("Include phone / cloud folders")
        self.cb_cloud.setToolTip("Phone Link, OneDrive, Dropbox... Deleting there deletes on the device / in the "
                                 "cloud. Same setting as in Options.")
        self.cb_cloud.setChecked(settings["include_cloud_folders"])
        self.cb_cloud.toggled.connect(self._toggle_cloud)
        self.drives.addWidget(self.cb_cloud)
        v.addLayout(self.drives)
        self.table = SearchTable(["File", "Size", "Type", "Pattern"], checkable=True)
        self.scan_btn = button("Scan", self._scan, primary=True)
        v.addLayout(toolbar(self.scan_btn, button("Scan folder...", self._scan_folder),
                            button("Cancel", self._cancel), button("Delete checked", self._delete),
                            button("Check all", lambda: self.table.check_all(True)),
                            button("Uncheck all", lambda: self.table.check_all(False)),
                            "stretch", search_box(self.table)))
        v.addWidget(self.table, 1)
        self.status = QLabel()
        v.addWidget(self.status)
        self.worker = None
        self.table.view.customContextMenuRequested.connect(self._menu)

    def _scan(self, roots=None):
        roots = roots or [cb.text() for cb in self.drive_boxes if cb.isChecked()]
        if not roots:
            return
        self.scan_btn.setEnabled(False)
        self.skipped: list[str] = []
        self.worker = run_bg(self, lambda p, c: tools.scan_junk(roots, p, c, skipped=self.skipped), self._done,
                             lambda s: self.status.setText("Scanning " + s[:120]))

    def showEvent(self, e):
        super().showEvent(e)
        self.cb_cloud.blockSignals(True)          # the setting may have changed in Options
        self.cb_cloud.setChecked(settings["include_cloud_folders"])
        self.cb_cloud.blockSignals(False)

    def _toggle_cloud(self, on: bool):
        if on and not confirm(self, "Include phone and cloud storage folders?\n\nFiles deleted there are deleted on "
                                    "your phone / in your cloud account too. Cloud files will be listed but left "
                                    "unchecked."):
            self.cb_cloud.blockSignals(True)
            self.cb_cloud.setChecked(False)
            self.cb_cloud.blockSignals(False)
            return
        settings["include_cloud_folders"] = on

    def _scan_folder(self):
        d = QFileDialog.getExistingDirectory(self, "Folder to scan")
        if d:
            self._scan([os.path.normpath(d)])

    def _cancel(self):
        if self.worker:
            self.worker.cancel()

    def _done(self, found, skipped_note: bool = True):
        self.scan_btn.setEnabled(True)
        cloud = {f.path for f in found if wu.is_cloud_path(f.path)}
        self.table.set_rows([(f, [f.path, (wu.human_size(f.size), f.size),
                                  f.description + ("  (phone / cloud)" if f.path in cloud else ""), f.pattern], None)
                             for f in found])
        self.table.check_all(True)
        for f in found:                      # phone / cloud files are never pre-checked
            if f.path in cloud:
                self.table.set_checked(f, False)
        msg = f"{len(found)} junk files, {wu.human_size(sum(f.size for f in found))}"
        if skipped_note and getattr(self, "skipped", None):
            msg += "  ·  Skipped phone/cloud folders: " + "; ".join(self.skipped)
        self.status.setText(msg)

    def _delete(self):
        sel = self.table.checked()
        if not sel or not confirm(self, f"Delete {len(sel)} files?" + (" They go to the Recycle Bin."
                                                                        if settings["junk_recycle"] else "")):
            return
        results = tools.delete_files([f.path for f in sel], settings["junk_recycle"])
        backup.add_history({"name": "Junk files", "version": ""}, "Junk Files Cleaner", None, {"items": results})
        ok = sum(1 for r in results if r["status"] in ("deleted", "recycled"))
        skipped = sum(1 for r in results if r["status"] == "skipped")
        failed = sum(1 for r in results if r["status"] == "failed")
        info(self, f"{ok} deleted, {failed} could not be deleted (in use or protected)"
                   + (f", {skipped} skipped (phone/cloud storage)" if skipped else "")
                   + ".\n\nThe full list is in Uninstall History.")
        self._done([f for f in self.table.objects if os.path.exists(f.path)], skipped_note=False)

    def _menu(self, pos):
        f = self.table.current()
        if not f:
            return
        m = QMenu(self)
        m.addAction("Open", lambda: os.startfile(f.path))
        m.addAction("Open containing folder", lambda: wu.open_folder(f.path))
        m.addAction("Search the web", lambda: web_search(os.path.basename(f.path)))
        m.addAction("Properties", lambda: wu.show_properties(f.path))
        m.addSeparator()
        m.addAction("Check selected", lambda: [self.table.set_checked(o, True) for o in self.table.selected()])
        m.addAction("Uncheck selected", lambda: [self.table.set_checked(o, False) for o in self.table.selected()])
        m.exec(self.table.view.viewport().mapToGlobal(pos))


# ================================================================ History Cleaner


class HistoryCleanerPage(QWidget):
    def __init__(self):
        super().__init__()
        v = QVBoxLayout(self)
        v.addWidget(PageHeader("History Cleaner", "Erase traces of your activity in Windows, web browsers and "
                                                  "Microsoft Office. Close browsers before cleaning them."))
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["What to clean"])
        self.cleaners = tools.history_cleaners()
        for group, items in self.cleaners.items():
            g = QTreeWidgetItem(self.tree, [group])
            g.setFlags(g.flags() | Qt.ItemIsUserCheckable | Qt.ItemIsAutoTristate)
            for name in items:
                c = QTreeWidgetItem(g, [name])
                c.setFlags(c.flags() | Qt.ItemIsUserCheckable)
                c.setCheckState(0, Qt.Unchecked if name in ("Cookies", "Session", "Empty Recycle Bin") else Qt.Checked)
                c.setData(0, Qt.UserRole, (group, name))
        self.tree.expandAll()
        v.addLayout(toolbar(button("Clear checked", self._clear, primary=True), "stretch"))
        v.addWidget(self.tree, 1)
        self.status = QLabel()
        v.addWidget(self.status)

    def _clear(self):
        jobs = []
        for i in range(self.tree.topLevelItemCount()):
            g = self.tree.topLevelItem(i)
            for j in range(g.childCount()):
                c = g.child(j)
                if c.checkState(0) == Qt.Checked:
                    jobs.append(c.data(0, Qt.UserRole))
        if not jobs or not confirm(self, f"Clear {len(jobs)} item(s)? This cannot be undone."):
            return

        def work(prog, c):
            n = 0
            for group, name in jobs:
                prog(f"{group}: {name}")
                try:
                    n += self.cleaners[group][name]() or 0
                except Exception:
                    pass
            return n
        run_bg(self, work, lambda n: self.status.setText(f"Done - {n} items cleared."), self.status.setText)


# ================================================================ Evidence Remover / Unrecoverable Delete


class EvidenceRemoverPage(QWidget):
    def __init__(self):
        super().__init__()
        v = QVBoxLayout(self)
        v.addWidget(PageHeader("Evidence Remover", "Overwrites the free space of a drive with random data three "
                                                   "times, so previously deleted files cannot be recovered. Slow; "
                                                   "free space temporarily drops to zero. On SSDs, TRIM already "
                                                   "makes most deleted data unrecoverable."))
        self.boxes = []
        row = QHBoxLayout()
        for d in tools.fixed_drives():
            cb = QCheckBox(f"{d}  ({wu.human_size(shutil.disk_usage(d).free)} free)")
            cb.setProperty("drive", d)
            self.boxes.append(cb)
            row.addWidget(cb)
        row.addStretch(1)
        v.addLayout(row)
        self.bar = QProgressBar()
        self.label = QLabel()
        v.addLayout(toolbar(button("Execute", self._run, primary=True), button("Cancel", self._cancel), "stretch"))
        v.addWidget(self.label)
        v.addWidget(self.bar)
        v.addStretch(1)
        self.worker = None

    def _run(self):
        drives = [b.property("drive") for b in self.boxes if b.isChecked()]
        if not drives or not confirm(self, "Wipe free space on " + ", ".join(drives) + "? This can take hours."):
            return

        def work(prog, cancelled):
            for d in drives:
                tools.wipe_free_space(d, lambda s, f: prog(f"{d} {s}|{f}"), cancelled)
            return True

        def on_prog(s):
            text, _, frac = s.rpartition("|")
            self.label.setText(text)
            self.bar.setValue(int(float(frac) * 100))
        self.worker = run_bg(self, work, lambda _r: self.label.setText("Finished."), on_prog)

    def _cancel(self):
        if self.worker:
            self.worker.cancel()


class DropList(QListWidget):
    def __init__(self):
        super().__init__()
        self.setAcceptDrops(True)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    dragMoveEvent = dragEnterEvent

    def dropEvent(self, e):
        for u in e.mimeData().urls():
            self.addItem(os.path.normpath(u.toLocalFile()))


class UnrecoverableDeletePage(QWidget):
    def __init__(self):
        super().__init__()
        v = QVBoxLayout(self)
        v.addWidget(PageHeader("Unrecoverable Delete", "Files and folders added here are overwritten with random "
                                                       "data three times before being deleted, so no recovery tool "
                                                       "can bring them back. Drag and drop is supported."))
        self.list = DropList()
        v.addLayout(toolbar(button("Add file(s)...", self._files), button("Add folder...", self._folder),
                            button("Remove from list", lambda: [self.list.takeItem(self.list.row(i))
                                                                for i in self.list.selectedItems()]),
                            "stretch", button("Delete forever", self._run, primary=True)))
        v.addWidget(self.list, 1)
        self.status = QLabel()
        v.addWidget(self.status)

    def _files(self):
        for f in QFileDialog.getOpenFileNames(self, "Files to erase")[0]:
            self.list.addItem(os.path.normpath(f))

    def _folder(self):
        d = QFileDialog.getExistingDirectory(self, "Folder to erase")
        if d:
            self.list.addItem(os.path.normpath(d))

    def _run(self):
        paths = [self.list.item(i).text() for i in range(self.list.count())]
        bad = [p for p in paths if is_protected_path(p)
               and os.path.isdir(p)]
        if bad:
            info(self, "These are protected system folders and cannot be erased:\n" + "\n".join(bad))
            return
        if not paths or not confirm(self, f"Permanently erase {len(paths)} item(s)? This CANNOT be undone."):
            return
        run_bg(self, lambda p, c: tools.shred_paths(paths, p, c), self._done, lambda s: self.status.setText(s[:150]))

    def _done(self, res):
        done, errors = res
        self.list.clear()
        self.status.setText(f"{done} files erased." + (f" {len(errors)} errors." if errors else ""))
        if errors:
            info(self, "\n".join(errors[:30]))


# ================================================================ Windows Tools


class WindowsToolsPage(QWidget):
    def __init__(self):
        super().__init__()
        v = QVBoxLayout(self)
        v.addWidget(PageHeader("Windows Tools", "One-click access to useful tools built into Windows."))
        self.grid = QGridLayout()
        v.addLayout(self.grid)
        v.addLayout(toolbar(button("Add custom tool...", self._add), "stretch"))
        v.addStretch(1)
        self._fill()

    def _fill(self):
        while self.grid.count():
            self.grid.takeAt(0).widget().deleteLater()
        all_tools = tools.WINDOWS_TOOLS + [tuple(t) for t in settings["custom_tools"]]
        for i, (name, cmd) in enumerate(all_tools):
            b = QPushButton(name)
            b.setToolTip(cmd)
            b.setMinimumHeight(38)
            b.clicked.connect(lambda _=False, c=cmd: tools.launch_tool(c))
            if (name, cmd) in [tuple(t) for t in settings["custom_tools"]]:
                b.setContextMenuPolicy(Qt.CustomContextMenu)
                b.customContextMenuRequested.connect(lambda _p, n=name, c=cmd: self._remove(n, c))
            self.grid.addWidget(b, i // 4, i % 4)

    def _add(self):
        name, ok = QInputDialog.getText(self, "Custom tool", "Name:")
        if not ok or not name:
            return
        cmd, ok = QInputDialog.getText(self, "Custom tool", "Command line:")
        if ok and cmd:
            settings["custom_tools"] = list(settings["custom_tools"]) + [[name, cmd]]
            self._fill()

    def _remove(self, name, cmd):
        if confirm(self, f"Delete the custom tool '{name}'?"):
            settings["custom_tools"] = [t for t in settings["custom_tools"] if tuple(t) != (name, cmd)]
            self._fill()


# ================================================================ Backup Manager


class BackupManagerPage(QWidget):
    def __init__(self):
        super().__init__()
        v = QVBoxLayout(self)
        v.addWidget(PageHeader("Backup Manager", "Everything deleted from the registry (and files, if you chose the "
                                                 "backup folder option) is kept here. Restore a whole backup or just "
                                                 "some of its items."))
        self.table = SearchTable(["Date", "Operation", "Program", "Items", "Size", "ID"])
        v.addLayout(toolbar(button("Restore", self._restore, primary=True), button("Custom restore...", self._custom),
                            button("Delete", self._delete),
                            menu_button("More", [("Delete backups older than...", self._delete_by_time),
                                                 ("Delete all", self._delete_all),
                                                 ("Open backup folder", lambda: os.startfile(backup.BACKUP_DIR)
                                                  if os.path.isdir(backup.BACKUP_DIR) else None),
                                                 ("Windows System Restore", lambda: tools.launch_tool("rstrui.exe")),
                                                 ("Refresh", self.refresh)]),
                            "stretch", search_box(self.table)))
        v.addWidget(self.table, 1)

    def showEvent(self, e):
        super().showEvent(e)
        self.refresh()

    def refresh(self):
        bs = backup.list_backups()
        self.table.set_rows([(b, [b["created"], b["operation"], b["program"], b["count"],
                                  (wu.human_size(b["size"]), b["size"]), b["id"]], None) for b in bs])

    def _restore(self):
        b = self.table.current()
        if b and confirm(self, f"Restore all {b['count']} backed up items of '{b['program']}'?"):
            self._show_results(backup.restore_backup(b["id"]))

    def _custom(self):
        b = self.table.current()
        if not b:
            return
        d = QDialog(self)
        d.setWindowTitle("Custom restore")
        d.resize(900, 500)
        v = QVBoxLayout(d)
        lst = QListWidget()
        for idx, it in enumerate(b["items"]):
            if not backup.restorable(it):
                continue
            w = QListWidgetItem(f"{it['kind']}: {it['path']}" + (f" -> {it['value_name'] or '(Default)'}"
                                                                 if it["kind"] == "regvalue" else ""))
            w.setData(Qt.UserRole, idx)
            w.setFlags(w.flags() | Qt.ItemIsUserCheckable)
            w.setCheckState(Qt.Unchecked)
            lst.addItem(w)
        v.addWidget(lst)
        row = QHBoxLayout()
        row.addWidget(button("Select all", lambda: [lst.item(i).setCheckState(Qt.Checked) for i in range(lst.count())]))
        row.addStretch(1)
        row.addWidget(button("Cancel", d.reject))
        row.addWidget(button("Restore", d.accept, primary=True))
        v.addLayout(row)
        if d.exec():
            idx = [lst.item(i).data(Qt.UserRole) for i in range(lst.count()) if lst.item(i).checkState() == Qt.Checked]
            if idx:
                self._show_results(backup.restore_backup(b["id"], idx))

    def _show_results(self, res):
        ok = sum(1 for r in res if r[1])
        failed = [f"{p}: {e}" for p, s, e in res if not s]
        info(self, f"{ok} item(s) restored." + ("\n\nFailed:\n" + "\n".join(failed[:20]) if failed else ""))

    def _delete(self):
        sel = self.table.selected()
        if sel and confirm(self, f"Delete {len(sel)} backup(s)? They are moved to the Recycle Bin."):
            for b in sel:
                backup.delete_backup(b["id"])
            self.refresh()

    def _delete_by_time(self):
        d = QDialog(self)
        d.setWindowTitle("Delete by time")
        v = QVBoxLayout(d)
        v.addWidget(QLabel("Delete all backups created before:"))
        date = QDateEdit(QDate.currentDate().addMonths(-1))
        date.setCalendarPopup(True)
        v.addWidget(date)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(button("Cancel", d.reject))
        row.addWidget(button("Delete", d.accept, primary=True))
        v.addLayout(row)
        if d.exec():
            n = backup.delete_backups_before(date.date().toPython())
            info(self, f"{n} backup(s) deleted.")
            self.refresh()

    def _delete_all(self):
        if confirm(self, "Delete ALL backups?"):
            for b in self.table.objects:
                backup.delete_backup(b["id"])
            self.refresh()


# ================================================================ Uninstall History


class UninstallHistoryPage(QWidget):
    def __init__(self):
        super().__init__()
        v = QVBoxLayout(self)
        v.addWidget(PageHeader("Uninstall History", "A record of every uninstall, with each leftover that was or "
                                                    "was not removed."))
        self.table = SearchTable(["Date", "Operation", "Program", "Version", "Scan mode", "Removed", "Failed"])
        v.addLayout(toolbar(button("Details", self._details, primary=True), button("Export...", self._export),
                            button("Delete", self._delete), button("Delete all", self._delete_all),
                            "stretch", search_box(self.table)))
        v.addWidget(self.table, 1)
        self.table.view.doubleClicked.connect(lambda _i: self._details())

    def showEvent(self, e):
        super().showEvent(e)
        self.refresh()

    def refresh(self):
        hs = backup.list_history()
        self.table.set_rows([(h, [h["date"], h["operation"], (h.get("program") or {}).get("name", ""),
                                  (h.get("program") or {}).get("version", ""), h.get("scan_mode") or "",
                                  h["ok"], h["failed"]], None) for h in hs])

    def _details(self):
        h = self.table.current()
        if not h:
            return
        d = QDialog(self)
        d.setWindowTitle("Uninstall details")
        d.resize(900, 600)
        v = QVBoxLayout(d)
        p = h.get("program") or {}
        v.addWidget(QLabel(f"<b>{p.get('name', '')}</b> {p.get('version', '')}<br>{h['operation']} on {h['date']}"
                           f"<br>Publisher: {p.get('publisher', '-')}<br>Install location: "
                           f"{p.get('install_location', '-')}"))
        t = QPlainTextEdit("\n".join(f"[{i['status']}] {i['kind']}: {i['path']}" +
                                     (f" -> {i['value_name']}" if i.get("value_name") is not None else "") +
                                     (f"  ({i['detail']})" if i.get("detail") else "") for i in h["items"])
                           or "No leftovers were removed.")
        t.setReadOnly(True)
        v.addWidget(t)
        d.exec()

    def _export(self):
        h = self.table.current()
        if h:
            path, _ = QFileDialog.getSaveFileName(self, "Export", "uninstall-report.txt", "Text (*.txt)")
            if path:
                backup.export_history(h, path)

    def _delete(self):
        for h in self.table.selected():
            backup.delete_history(h["id"])
        self.refresh()

    def _delete_all(self):
        if confirm(self, "Delete the whole uninstall history?"):
            backup.delete_history()
            self.refresh()
