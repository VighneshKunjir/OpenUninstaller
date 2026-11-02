"""Uninstaller modules: All Programs, Traced Programs, Windows Apps, Browser Extensions."""

from __future__ import annotations

import os
import subprocess

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QComboBox, QDialog, QFileDialog, QHBoxLayout, QInputDialog, QLabel, QLineEdit,
                               QMenu, QPlainTextEdit, QTabWidget, QVBoxLayout, QWidget)

from .. import appx, browser_ext, programs, tracer, winutil as wu
from ..config import settings
from .common import (PageHeader, SearchTable, button, confirm, error, file_icon, info, menu_button, run_bg,
                     search_box, toolbar, web_search)
from .wizard import QuickUninstallDialog, UninstallWizard


# ================================================================ All Programs


class AllProgramsPage(QWidget):
    go_history = Signal()
    go_traced = Signal()

    def __init__(self):
        super().__init__()
        v = QVBoxLayout(self)
        v.addWidget(PageHeader("All Programs", "Every desktop program installed for this computer and your "
                                               "account. Uninstall runs the program's own uninstaller and then "
                                               "scans for everything it left behind."))
        self.table = SearchTable(["Name", "Size", "Version", "Publisher", "Install date", "Type", "Comment"])
        self.filter = QComboBox()
        self.filter.setMinimumWidth(190)
        self.filter.currentIndexChanged.connect(self._apply_filter)
        self.search = search_box(self.table, "Search by name, publisher or comment")
        more = menu_button("More", [
            ("Install a program with tracing...", self.go_traced.emit),
            None,
            ("Change / modify", self._change), ("Repair", self._repair),
            ("Forced MSI uninstall", lambda: self._wizard("forced_msi")),
            None,
            ("Calculate real folder sizes", self._sizes),
            ("Show / hide system components", self._toggle_components),
            ("Show / hide Windows updates", self._toggle_updates),
            ("Show hidden programs", self._unhide_all),
            None,
            ("Export list...", self._export),
            ("Uninstall History", self.go_history.emit),
            ("Refresh", self.refresh),
        ])
        v.addLayout(toolbar(button("Uninstall", lambda: self._wizard("program"), primary=True),
                            button("Quick Uninstall", self._quick, "Silent uninstall + automatic leftover removal; "
                                                                   "works on several selected programs"),
                            button("Forced Uninstall", self._forced, "Remove leftovers of a program that is broken, "
                                                                     "partly uninstalled or not listed"),
                            more, "stretch", self.filter, self.search))
        v.addWidget(self.table, 1)
        self.status = QLabel()
        v.addWidget(self.status)
        self.table.view.doubleClicked.connect(lambda _i: self._wizard("program"))
        self.table.view.customContextMenuRequested.connect(self._menu)
        self.progs: list[programs.Program] = []
        self.refresh()

    def refresh(self):
        self.status.setText("Loading...")
        run_bg(self, lambda p, c: programs.list_programs(), self._loaded)

    def _loaded(self, progs):
        self.progs = progs
        cur = self.filter.currentText()
        self.filter.blockSignals(True)
        self.filter.clear()
        self.filter.addItems(["All programs", "New programs", "64-bit", "32-bit", "Per user", "Windows Installer (MSI)",
                              "Large (>500 MB)"] + [f"Group: {g}" for g in settings["groups"]])
        if cur:
            self.filter.setCurrentText(cur)
        self.filter.blockSignals(False)
        self._apply_filter()

    def _apply_filter(self):
        f = self.filter.currentText()
        groups = settings["program_groups"]
        comments = settings["program_comments"]

        def keep(p: programs.Program) -> bool:
            if p.extra.get("hidden"):
                return False
            if f == "New programs":
                return programs.is_new(p)
            if f in ("64-bit", "32-bit"):
                return p.scope == f
            if f == "Per user":
                return p.scope == "User"
            if f.startswith("Windows Installer"):
                return p.is_msi
            if f.startswith("Large"):
                return (p.size_bytes or 0) > 500 * 1024 * 1024
            if f.startswith("Group: "):
                return groups.get(p.uid) == f[7:]
            return True

        shown = [p for p in self.progs if keep(p)]
        rows = []
        for p in shown:
            kind = ("MSI" if p.is_msi else "EXE") + (" · component" if p.system_component else "") + \
                   (" · update" if p.is_update else "")
            rows.append((p, [(p.name, p.name), (wu.human_size(p.size_bytes), p.size_bytes or 0), p.version,
                             p.publisher, p.install_date, f"{p.scope} {kind}", comments.get(p.uid, "")],
                         file_icon(p.display_icon)))
        self.table.set_rows(rows)
        self.table.view.sortByColumn(0, Qt.AscendingOrder)
        total = sum(p.size_bytes or 0 for p in shown)
        self.status.setText(f"{len(shown)} programs shown ({len(self.progs)} installed) · {wu.human_size(total)}"
                            + ("" if wu.is_admin() else "  ·  Not running as administrator: some programs cannot "
                                                         "be fully removed"))

    # ---- actions -------------------------------------------------------------

    def _wizard(self, kind: str):
        p = self.table.current()
        if not p:
            return
        if kind == "forced_msi" and not p.product_code:
            info(self, "This program is not a Windows Installer (MSI) package.")
            return
        UninstallWizard(self, kind, program=p).exec()
        self.refresh()

    def _quick(self):
        sel = self.table.selected()
        if not sel:
            return
        QuickUninstallDialog(self, progs=sel).exec()
        self.refresh()

    def _forced(self, names: str = "", paths: list[str] | None = None):
        UninstallWizard(self, "forced", forced_names=names if isinstance(names, str) else "",
                        forced_paths=paths).exec()
        self.refresh()

    def _change(self):
        p = self.table.current()
        cmd = p and programs.modify_command(p)
        if cmd:
            subprocess.Popen(cmd)
        elif p:
            info(self, "This program offers no Change option.")

    def _repair(self):
        p = self.table.current()
        cmd = p and programs.modify_command(p, repair=True)
        if cmd:
            subprocess.Popen(cmd)
        elif p:
            info(self, "This program offers no Repair option.")

    def _sizes(self):
        progs = list(self.progs)
        self.status.setText("Calculating folder sizes...")

        def work(prog, c):
            for p in progs:
                size = programs.compute_size(p)
                if size:
                    p.size_bytes = size
            return progs
        run_bg(self, work, lambda _r: self._apply_filter())

    def _toggle_components(self):
        settings["show_system_components"] = not settings["show_system_components"]
        self.refresh()

    def _toggle_updates(self):
        settings["show_updates"] = not settings["show_updates"]
        self.refresh()

    def _unhide_all(self):
        if settings["hidden_programs"] and confirm(self, f"Show {len(settings['hidden_programs'])} hidden program(s) again?"):
            settings["hidden_programs"] = []
            self.refresh()

    def _export(self):
        path, flt = QFileDialog.getSaveFileName(self, "Export program list", "programs.csv",
                                                "CSV (*.csv);;HTML (*.html);;Text (*.txt);;JSON (*.json)")
        if path:
            fmt = os.path.splitext(path)[1].lstrip(".").lower() or "csv"
            programs.export_list([self.table.obj_at(r) for r in range(self.table.proxy.rowCount())], path, fmt)
            info(self, f"Exported to {path}")

    def _menu(self, pos):
        p = self.table.current()
        if not p:
            return
        m = QMenu(self)
        m.addAction("Uninstall", lambda: self._wizard("program"))
        m.addAction("Quick Uninstall", self._quick)
        if p.product_code:
            m.addAction("Forced MSI Uninstall", lambda: self._wizard("forced_msi"))
        m.addAction("Forced Uninstall (leftovers only)",
                    lambda: self._forced(p.name, [p.guess_install_dir()] if p.guess_install_dir() else []))
        m.addSeparator()
        if programs.modify_command(p):
            m.addAction("Change", self._change)
        if programs.modify_command(p, repair=True):
            m.addAction("Repair", self._repair)
        d = p.guess_install_dir()
        if d and os.path.isdir(d):
            m.addAction("Open install folder", lambda: wu.open_folder(d))
        m.addAction("Open registry key", lambda: wu.open_in_regedit(p.reg_display))
        if p.url:
            m.addAction("Open publisher website", lambda: os.startfile(p.url))
        m.addAction("Search the web for name", lambda: web_search(p.name))
        m.addAction("Search the web for publisher", lambda: web_search(p.publisher))
        m.addSeparator()
        m.addAction("Add / edit comment...", lambda: self._comment(p))
        g = m.addMenu("Assign to group")
        for grp in settings["groups"]:
            g.addAction(grp, lambda grp=grp: self._group(p, grp))
        g.addAction("(none)", lambda: self._group(p, None))
        m.addAction("Hide from list", lambda: self._hide(p))
        m.addAction("Copy name", lambda: _clip(p.name))
        m.exec(self.table.view.viewport().mapToGlobal(pos))

    def _comment(self, p):
        cur = settings["program_comments"].get(p.uid, "")
        text, ok = QInputDialog.getText(self, "Comment", f"Comment for {p.name}:", text=cur)
        if ok:
            c = dict(settings["program_comments"])
            c[p.uid] = text
            settings["program_comments"] = c
            self._apply_filter()

    def _group(self, p, grp):
        g = dict(settings["program_groups"])
        if grp:
            g[p.uid] = grp
        else:
            g.pop(p.uid, None)
        settings["program_groups"] = g

    def _hide(self, p):
        settings["hidden_programs"] = list(settings["hidden_programs"]) + [p.uid]
        p.extra["hidden"] = True
        self._apply_filter()


def _clip(text):
    from PySide6.QtWidgets import QApplication
    QApplication.clipboard().setText(text)


# ================================================================ Traced Programs


class TraceBar(QDialog):
    """Small always-on-top bar shown while an installer is being traced."""

    def __init__(self, parent, session: tracer.TraceSession, default_name: str):
        super().__init__(parent, Qt.Tool | Qt.WindowStaysOnTopHint)
        self.session = session
        self.setWindowTitle("Tracing installation")
        h = QHBoxLayout(self)
        h.addWidget(QLabel("● Tracing - install, run and configure the program, close it, then click Stop."))
        self.name = QLineEdit(default_name)
        self.name.setPlaceholderText("Log name")
        self.name.setMinimumWidth(220)
        h.addWidget(self.name)
        self.stop_btn = button("Stop && Save", self._stop, primary=True)
        h.addWidget(self.stop_btn)
        h.addWidget(button("Cancel", self._cancel))
        self.log = None

    def _stop(self):
        self.stop_btn.setEnabled(False)
        self.stop_btn.setText("Comparing...")
        run_bg(self, lambda p, c: self.session.stop(self.name.text().strip(), p), self._saved,
               lambda s: self.stop_btn.setText(s[:40]))

    def _saved(self, log):
        self.log = log
        self.accept()

    def _cancel(self):
        if confirm(self, "Discard this trace?"):
            try:
                os.remove(tracer.PENDING)
            except OSError:
                pass
            self.reject()


class TracedProgramsPage(QWidget):
    def __init__(self):
        super().__init__()
        v = QVBoxLayout(self)
        v.addWidget(PageHeader("Traced Programs", "Install programs through OpenUninstaller to record every file "
                                                  "and registry change they make. A traced program can later be "
                                                  "removed completely, exactly as if it was never installed."))
        self.table = SearchTable(["Name", "Traced on", "Folders", "Files", "Registry keys", "Values", "Installer"])
        manage = menu_button("Manage", [("View log contents", self._view), ("Rename", self._rename),
                                        ("Merge selected logs", self._merge), ("Delete log(s)", self._delete),
                                        None, ("Export log...", self._export), ("Import log...", self._import)])
        v.addLayout(toolbar(button("Trace new install...", self.trace_install, primary=True),
                            button("Uninstall", lambda: self._uninstall("traced"),
                                   "Remove everything recorded in the log automatically"),
                            button("Custom Uninstall", lambda: self._uninstall("custom_traced"),
                                   "Review the logged items and choose what to remove"),
                            manage, "stretch", search_box(self.table)))
        self.pending = QLabel()
        self.pending.setObjectName("warning")
        self.pending.linkActivated.connect(self._finish_pending)
        v.addWidget(self.pending)
        v.addWidget(self.table, 1)
        self.table.view.doubleClicked.connect(lambda _i: self._view())
        self.refresh()

    def refresh(self):
        logs = tracer.list_logs()
        self.table.set_rows([(l, [l["name"], l["created"].replace("T", " "), len(l.get("dirs_created", [])),
                                  len(l.get("files_created", [])), len(l.get("keys_created", [])),
                                  len(l.get("values_created", [])), os.path.basename(l.get("installer") or "")], None)
                             for l in logs])
        if os.path.exists(tracer.PENDING):
            self.pending.setText("An unfinished trace was found (for example after a restart). "
                                 "<a href='#'>Finish it now</a>")
            self.pending.show()
        else:
            self.pending.hide()

    def trace_install(self):
        path, _ = QFileDialog.getOpenFileName(self, "Choose the installer to trace", "",
                                              "Installers (*.exe *.msi);;All files (*)")
        if not path:
            return
        info(self, "Tip: install only one program at a time and avoid starting other programs during the trace.\n\n"
                   "A snapshot of your system is taken first (this takes up to a minute).")
        name = os.path.splitext(os.path.basename(path))[0]
        session = tracer.TraceSession(path, name)
        self.pending.setText("Taking the 'before' snapshot...")
        self.pending.show()
        run_bg(self, lambda p, c: session.start(p), lambda _r: self._show_bar(session, name),
               lambda s: self.pending.setText(s))

    def _finish_pending(self, *_):
        s = tracer.TraceSession.resume_pending()
        if s:
            self._show_bar(s, s.name)

    def _show_bar(self, session, name):
        self.pending.hide()
        bar = TraceBar(self.window(), session, name)
        bar.move(self.screen().availableGeometry().center().x() - 400, 10)
        if bar.exec() and bar.log:
            log = bar.log
            info(self, f"Saved trace '{log['name']}': {len(log['dirs_created'])} folders, "
                       f"{len(log['files_created'])} files, {len(log['keys_created'])} registry keys, "
                       f"{len(log['values_created'])} values.")
        self.refresh()

    def _uninstall(self, kind):
        log = self.table.current()
        if not log:
            return
        prog = next((p for p in programs.list_programs(True, True) if p.key_name in log.get("uninstall_keys", [])),
                    None)
        UninstallWizard(self, kind, program=prog, log=log).exec()
        self.refresh()

    def _view(self):
        log = self.table.current()
        if not log:
            return
        d = QDialog(self)
        d.setWindowTitle(f"Trace log - {log['name']}")
        d.resize(900, 600)
        v = QVBoxLayout(d)
        tabs = QTabWidget()
        props = (f"Name: {log['name']}\nCreated: {log['created']}\nInstaller: {log.get('installer')}\n"
                 f"Windows: {log.get('windows')}\nAuthor: {log.get('author')}\nComment: {log.get('comment')}\n"
                 f"Uninstall entries: {', '.join(log.get('uninstall_keys', [])) or '-'}")
        reg = "\n".join([wu.wow_display(h, s, vw) for h, vw, s in log.get("keys_created", [])] +
                        [f"{wu.wow_display(h, s, vw)} -> {n or '(Default)'}" for h, vw, s, n in log.get("values_created", [])])
        fs = "\n".join(log.get("dirs_created", []) + log.get("files_created", []))
        mod = "\n".join(log.get("files_modified", []) + [f"{wu.wow_display(h, s, vw)} -> {n}" for h, vw, s, n in
                                                         log.get("values_changed", [])])
        for title, text in (("Properties", props), ("Registry", reg), ("Files and folders", fs),
                            ("Modified (not removed)", mod)):
            t = QPlainTextEdit(text)
            t.setReadOnly(True)
            tabs.addTab(t, title)
        v.addWidget(tabs)
        d.exec()

    def _rename(self):
        log = self.table.current()
        if log:
            name, ok = QInputDialog.getText(self, "Rename log", "New name:", text=log["name"])
            if ok and name:
                tracer.rename_log(log, name)
                self.refresh()

    def _merge(self):
        sel = self.table.selected()
        if len(sel) < 2:
            info(self, "Select two or more logs to merge.")
            return
        if confirm(self, f"Merge {len(sel)} logs into '{min(sel, key=lambda l: l['created'])['name']}'?"):
            tracer.merge_logs(sel)
            self.refresh()

    def _delete(self):
        sel = self.table.selected()
        if sel and confirm(self, f"Delete {len(sel)} log(s)? Installed programs are not affected."):
            for l in sel:
                tracer.delete_log(l["id"])
            self.refresh()

    def _export(self):
        log = self.table.current()
        if log:
            path, _ = QFileDialog.getSaveFileName(self, "Export log", log["name"] + ".oulog",
                                                  "OpenUninstaller log (*.oulog)")
            if path:
                tracer.export_log(log, path)

    def _import(self):
        path, _ = QFileDialog.getOpenFileName(self, "Import log", "", "OpenUninstaller log (*.oulog *.json)")
        if path:
            try:
                tracer.import_log(path)
            except (OSError, ValueError, KeyError) as e:
                error(self, f"Could not import: {e}")
            self.refresh()


# ================================================================ Windows Apps


class WindowsAppsPage(QWidget):
    def __init__(self):
        super().__init__()
        v = QVBoxLayout(self)
        v.addWidget(PageHeader("Windows Apps", "Store and pre-installed (UWP / MSIX) apps. Framework and system "
                                               "packages Windows needs are hidden."))
        self.table = SearchTable(["Name", "Version", "Publisher", "Package"])
        v.addLayout(toolbar(button("Uninstall", self._uninstall, primary=True),
                            button("Quick Uninstall", self._quick),
                            menu_button("More", [("Run", lambda: self._each(appx.run)),
                                                 ("Terminate", lambda: self._each(appx.terminate)),
                                                 ("Reset to defaults", self._reset),
                                                 ("Uninstall for all users", lambda: self._uninstall(all_users=True)),
                                                 None, ("Open data folder", self._data),
                                                 ("Reset Microsoft Store", appx.reset_store),
                                                 ("Refresh", self.refresh)]),
                            "stretch", search_box(self.table)))
        v.addWidget(self.table, 1)
        self.status = QLabel()
        v.addWidget(self.status)
        self.loaded = False

    def showEvent(self, e):
        super().showEvent(e)
        if not self.loaded:
            self.loaded = True
            self.refresh()

    def refresh(self):
        self.status.setText("Loading apps...")
        run_bg(self, lambda p, c: appx.list_apps(), self._loaded)

    def _loaded(self, apps):
        self.table.set_rows([(a, [a.display_name, a.version, a.publisher, a.full_name],
                              None) for a in apps])
        self.status.setText(f"{len(apps)} apps")

    def _uninstall(self, all_users=False):
        a = self.table.current()
        if a:
            w = UninstallWizard(self, "appx", app=a)
            w.cb_all_users_app.setChecked(all_users)
            w.exec()
            self.refresh()

    def _quick(self):
        sel = self.table.selected()
        if sel:
            QuickUninstallDialog(self, apps=sel).exec()
            self.refresh()

    def _each(self, fn):
        for a in self.table.selected():
            fn(a)

    def _reset(self):
        a = self.table.current()
        if a and confirm(self, f"Reset {a.display_name}? All its data and settings will be erased."):
            ok, err = appx.reset(a)
            info(self, "App reset." if ok else f"Failed: {err}")

    def _data(self):
        a = self.table.current()
        if a and os.path.isdir(a.data_folder):
            wu.open_folder(a.data_folder)


# ================================================================ Browser Extensions


class BrowserExtensionsPage(QWidget):
    def __init__(self):
        super().__init__()
        v = QVBoxLayout(self)
        v.addWidget(PageHeader("Browser Extensions", "Extensions in Chrome, Edge, Brave, Vivaldi, Opera and "
                                                     "Firefox - including ones silently added by other software "
                                                     "(source 'External' or 'Policy'). Close the browser before "
                                                     "removing."))
        self.table = SearchTable(["Name", "Browser", "Profile", "Version", "Enabled", "Source", "ID", "Description"])
        v.addLayout(toolbar(button("Remove", self._remove, primary=True), button("Refresh", self.refresh),
                            button("Search the web", lambda: [web_search(e.name + " extension")
                                                              for e in self.table.selected()[:1]]),
                            "stretch", search_box(self.table)))
        v.addWidget(self.table, 1)
        self.status = QLabel()
        v.addWidget(self.status)
        self.loaded = False

    def showEvent(self, e):
        super().showEvent(e)
        if not self.loaded:
            self.loaded = True
            self.refresh()

    def refresh(self):
        run_bg(self, lambda p, c: browser_ext.list_extensions(), self._loaded)

    def _loaded(self, exts):
        self.table.set_rows([(e, [e.name, e.browser, e.profile, e.version, "Yes" if e.enabled else "No", e.source,
                                  e.ext_id, e.description], None) for e in exts])
        self.status.setText(f"{len(exts)} extensions")

    def _remove(self):
        sel = self.table.selected()
        if not sel or not confirm(self, f"Remove {len(sel)} extension(s)?"):
            return
        msgs = []
        for e in sel:
            ok, err = browser_ext.remove(e)
            msgs.append(f"{'Removed' if ok else 'Failed'}: {e.name} ({e.browser})" + (f" - {err}" if err else ""))
        info(self, "\n".join(msgs))
        self.refresh()
