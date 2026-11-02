"""Uninstall wizard: Analyze -> Built-in uninstaller -> Scan -> Registry leftovers -> Files -> Summary."""

from __future__ import annotations

import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QDialog, QFileDialog, QGroupBox, QHBoxLayout, QLabel,
                               QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QPlainTextEdit, QProgressBar,
                               QRadioButton, QStackedWidget, QVBoxLayout, QWidget)

from .. import appx, backup, programs, tracer, winutil as wu
from ..config import settings
from ..leftovers import Leftover, Target, scan
from ..uninstall import run_uninstaller
from . import theme
from .common import LeftoverTree, button, confirm, info, run_bg


class UninstallWizard(QDialog):
    """kind: program | forced | forced_msi | traced | custom_traced | appx"""

    def __init__(self, parent, kind: str, program: programs.Program | None = None,
                 app: appx.WinApp | None = None, log: dict | None = None, forced_names: str = "",
                 forced_paths: list[str] | None = None):
        super().__init__(parent)
        self.kind, self.program, self.app, self.log = kind, program, app, log
        self.worker = None
        self.manifests: list[dict] = []
        self.found_items: list[Leftover] = []
        self.target: Target | None = None
        self.uninstall_result: dict | None = None
        self.setWindowTitle("Uninstall wizard")
        self.resize(1000, 700)
        if settings["open_wizard_maximized"]:
            self.setWindowState(Qt.WindowMaximized)
        lay = QVBoxLayout(self)
        self.title = QLabel()
        self.title.setObjectName("pageTitle")
        self.steps = QLabel()
        self.steps.setObjectName("pageDesc")
        lay.addWidget(self.title)
        lay.addWidget(self.steps)
        self.stack = QStackedWidget()
        lay.addWidget(self.stack, 1)
        self._build_setup(forced_names, forced_paths or [])
        self._build_progress()
        self.reg_tree, self.reg_page = self._build_tree_page(
            "Leftover registry items", "Bold items were created by the program. Red items are protected and "
            "will never be deleted. Check what you want removed - only checked bold items are deleted, and "
            "everything deleted from the registry is backed up first.")
        self.fs_tree, self.fs_page = self._build_tree_page(
            "Leftover files and folders", "Bold items belong to the program. Files go to the "
            + {"recycle": "Recycle Bin", "backup": "backup folder", "permanent": "void (permanent delete)"}
            [settings["file_delete_mode"]] + " (change in Options).")
        self._build_summary()
        self._set_step(0)

    # ---- pages --------------------------------------------------------------

    def _program_label(self) -> str:
        if self.program:
            return f"{self.program.name} {self.program.version}".strip()
        if self.app:
            return self.app.display_name
        if self.log:
            return self.log["name"]
        return "Forced uninstall"

    def _build_setup(self, forced_names: str, forced_paths: list[str]):
        page = QWidget()
        v = QVBoxLayout(page)
        p = self.program
        if p:
            v.addWidget(QLabel(f"<b>{p.name}</b> {p.version}<br>Publisher: {p.publisher or '-'}<br>"
                               f"Install location: {p.guess_install_dir() or '-'}<br>"
                               f"Uninstaller: {programs.uninstall_command(p, forced_msi=self.kind == 'forced_msi') or 'none'}"))
            log = tracer.log_for_program(p)
            if log:
                self.log = log
        if self.app:
            a = self.app
            v.addWidget(QLabel(f"<b>{a.display_name}</b> {a.version}<br>Publisher: {a.publisher}<br>"
                               f"Package: {a.full_name}"))
        if self.kind == "forced":
            box = QGroupBox("What should be removed?")
            g = QVBoxLayout(box)
            g.addWidget(QLabel("Exact program name(s), separated by ';' - an incomplete name may find unrelated "
                               "items:"))
            self.forced_name = QLineEdit(forced_names)
            g.addWidget(self.forced_name)
            g.addWidget(QLabel("Install folder or main .exe (optional, recommended):"))
            row = QHBoxLayout()
            self.forced_path = QLineEdit(";".join(forced_paths))
            row.addWidget(self.forced_path)
            row.addWidget(button("Folder...", self._browse_folder))
            row.addWidget(button("File...", self._browse_file))
            g.addLayout(row)
            g.addWidget(button("Find matching uninstallers", self._find_forced))
            self.forced_found = QListWidget()
            self.forced_found.setMaximumHeight(120)
            g.addWidget(self.forced_found)
            v.addWidget(box)
            if forced_names or forced_paths:
                self._find_forced()
        opts = QGroupBox("Options")
        g = QVBoxLayout(opts)
        self.cb_restore = QCheckBox("Create a System Restore point first")
        self.cb_restore.setChecked(settings["create_restore_point"] and wu.is_admin())
        self.cb_restore.setEnabled(wu.is_admin())
        if not wu.is_admin():
            self.cb_restore.setToolTip("Needs administrator rights - restart OpenUninstaller as administrator")
        g.addWidget(self.cb_restore)
        self.cb_fullreg = QCheckBox("Create a full registry backup first (slow, large)")
        self.cb_fullreg.setChecked(settings["full_registry_backup"])
        g.addWidget(self.cb_fullreg)
        has_uninstaller = bool(p and programs.uninstall_command(p)) or self.kind in ("forced", "appx")
        self.cb_run = QCheckBox("Run the built-in uninstaller" if self.kind != "appx" else "Remove the app package")
        self.cb_run.setChecked(has_uninstaller)
        self.cb_run.setEnabled(has_uninstaller)
        g.addWidget(self.cb_run)
        self.cb_quiet = QCheckBox("Silent (try to run the uninstaller without its UI)")
        g.addWidget(self.cb_quiet)
        self.cb_all_users_app = QCheckBox("Remove for all user accounts")
        self.cb_all_users_app.setVisible(self.kind == "appx")
        g.addWidget(self.cb_all_users_app)
        self.cb_use_log = QCheckBox("Use the traced log for a complete removal")
        self.cb_use_log.setVisible(bool(self.log) and self.kind not in ("traced", "custom_traced"))
        self.cb_use_log.setChecked(bool(self.log))
        g.addWidget(self.cb_use_log)
        v.addWidget(opts)
        modes = QGroupBox("Leftover scan mode")
        mh = QVBoxLayout(modes)
        self.mode_group = QButtonGroup(self)
        descs = {"safe": "Safe - fastest; only items that certainly belong to the program",
                 "moderate": "Moderate - recommended; also the most common extra places",
                 "advanced": "Advanced - deep scan of registry and disk; review results carefully"}
        for i, m in enumerate(("safe", "moderate", "advanced")):
            rb = QRadioButton(descs[m])
            rb.setProperty("mode", m)
            rb.setChecked(m == settings["default_scan_mode"])
            self.mode_group.addButton(rb, i)
            mh.addWidget(rb)
        self.cb_all_users = QCheckBox("Scan all Windows accounts for leftovers")
        self.cb_all_users.setChecked(settings["scan_all_users"])
        mh.addWidget(self.cb_all_users)
        modes.setVisible(self.kind not in ("traced",))
        v.addWidget(modes)
        v.addStretch(1)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(button("Cancel", self.reject))
        row.addWidget(button("Next", self._start, primary=True))
        v.addLayout(row)
        self.stack.addWidget(page)

    def _build_progress(self):
        page = QWidget()
        v = QVBoxLayout(page)
        self.prog_label = QLabel("Working...")
        v.addWidget(self.prog_label)
        self.bar = QProgressBar()
        self.bar.setRange(0, 0)
        v.addWidget(self.bar)
        self.logbox = QPlainTextEdit()
        self.logbox.setReadOnly(True)
        v.addWidget(self.logbox, 1)
        row = QHBoxLayout()
        self.hint = QLabel("Tip: the uninstaller window may open behind this one - use Alt+Tab.")
        row.addWidget(self.hint)
        row.addStretch(1)
        self.btn_continue = button("Continue to scan", self._skip_wait,
                                   "Stop waiting for the built-in uninstaller and scan for leftovers now")
        row.addWidget(self.btn_continue)
        v.addLayout(row)
        self.stack.addWidget(page)

    def _build_tree_page(self, title: str, desc: str):
        page = QWidget()
        v = QVBoxLayout(page)
        lbl = QLabel(f"<b>{title}</b><br>{desc}")
        lbl.setWordWrap(True)
        v.addWidget(lbl)
        tree = LeftoverTree()
        v.addWidget(tree, 1)
        count = QLabel()
        v.addWidget(count)
        row = QHBoxLayout()
        row.addWidget(button("Select all", lambda: tree.set_all(True)))
        row.addWidget(button("Deselect all", lambda: tree.set_all(False)))
        row.addStretch(1)
        back = button("Back", lambda: self._set_step(2), "Return to the registry leftovers")
        row.addWidget(back)
        row.addWidget(button("Delete", lambda: self._delete(tree), primary=True))
        row.addWidget(button("Next", self._next_from_tree))
        v.addLayout(row)
        page.count_label = count
        page.back_button = back
        self.stack.addWidget(page)
        return tree, page

    def _build_summary(self):
        page = QWidget()
        v = QVBoxLayout(page)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        v.addWidget(self.summary)
        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        self.details.hide()
        v.addWidget(self.details, 10)
        v.addStretch(1)
        row = QHBoxLayout()
        row.addWidget(button("Show details", lambda: self.details.setVisible(not self.details.isVisible())))
        row.addStretch(1)
        self.summary_back = button("Back to leftovers", self._back_from_summary,
                                   "Go back and delete leftovers that are still on the system")
        row.addWidget(self.summary_back)
        row.addWidget(button("Finish", self.accept, primary=True))
        v.addLayout(row)
        self.stack.addWidget(page)

    def _set_step(self, idx: int):
        names = ["Analyze", "Uninstall & scan", "Registry leftovers", "File leftovers", "Summary"]
        self.title.setText(self._program_label())
        self.steps.setText("  ›  ".join(f"<b>{n}</b>" if i == idx else n for i, n in enumerate(names)))
        self.stack.setCurrentIndex(idx)
        if idx == 3:
            self.fs_page.back_button.setVisible(bool(self.reg_tree.items))

    # ---- forced uninstall helpers ------------------------------------------

    def _browse_folder(self):
        d = QFileDialog.getExistingDirectory(self, "Program folder")
        if d:
            self.forced_path.setText(os.path.normpath(d))
            if not self.forced_name.text():
                self.forced_name.setText(os.path.basename(d))

    def _browse_file(self):
        f, _ = QFileDialog.getOpenFileName(self, "Program executable", "", "Programs (*.exe);;All files (*)")
        if f:
            self.forced_path.setText(os.path.normpath(f))
            if not self.forced_name.text():
                info_ = wu.file_version_info(f)
                self.forced_name.setText(info_.get("ProductName") or os.path.splitext(os.path.basename(f))[0])

    def _find_forced(self):
        self.forced_found.clear()
        seen = set()
        for path in filter(None, self.forced_path.text().split(";")):
            for p in programs.find_by_location(path):
                seen.add(p.uid)
                self._add_found(p)
        for name in filter(None, (n.strip() for n in self.forced_name.text().split(";"))):
            for p in programs.find_by_name(name):
                if p.uid not in seen:
                    seen.add(p.uid)
                    self._add_found(p)
        if not seen:
            self.forced_found.addItem("No built-in uninstaller found - the leftover scan will still run.")

    def _add_found(self, p: programs.Program):
        it = QListWidgetItem(f"{p.name} {p.version}  -  {programs.uninstall_command(p)}")
        it.setData(Qt.UserRole, p)
        it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
        it.setCheckState(Qt.Unchecked)
        self.forced_found.addItem(it)

    # ---- flow ----------------------------------------------------------------

    def _mode(self) -> str:
        return self.mode_group.checkedButton().property("mode")

    def log_line(self, s: str):
        self.logbox.appendPlainText(s)
        self.prog_label.setText(s[:160])

    def _start(self):
        if self.kind == "forced":
            names = [n for n in self.forced_name.text().split(";") if n.strip()]
            paths = [p for p in self.forced_path.text().split(";") if p.strip()]
            if not names and not paths:
                info(self, "Enter a program name or a path.")
                return
            self.target = Target.forced(names, paths)
            chosen = [self.forced_found.item(i).data(Qt.UserRole) for i in range(self.forced_found.count())
                      if self.forced_found.item(i).checkState() == Qt.Checked]
            self.program = chosen[0] if chosen else None
            if self.program:
                self.target.uninstall_reg = (self.program.hive, self.program.reg_sub, self.program.view)
                self.target.product_code = self.program.product_code
        elif self.program:
            self.target = Target.from_program(self.program)
        elif self.app:
            self.target = Target(names=[self.app.display_name, self.app.name], publisher=self.app.publisher,
                                 install_dirs=[])
        self._set_step(1)
        opts = dict(restore=self.cb_restore.isChecked(), fullreg=self.cb_fullreg.isChecked(),
                    run=self.cb_run.isChecked() and (self.program is not None or self.app is not None),
                    quiet=self.cb_quiet.isChecked(), mode=self._mode(), all_users=self.cb_all_users.isChecked(),
                    use_log=self.cb_use_log.isChecked() or self.kind in ("traced", "custom_traced"),
                    app_all_users=self.cb_all_users_app.isChecked())
        if settings["only_builtin_uninstaller"] and self.kind == "program":
            opts["mode"] = None
        self.btn_continue.setEnabled(opts["run"])
        self.worker = run_bg(self, lambda prog, cancelled: self._work(opts, prog, cancelled), self._work_done,
                             self.log_line)

    def _work(self, o: dict, progress, cancelled) -> list[Leftover]:
        label = self._program_label()
        if o["restore"]:
            progress("Creating a System Restore point...")
            ok, msg = backup.create_restore_point(f"OpenUninstaller: before removing {label}")
            progress(msg)
        if o["fullreg"]:
            progress("Creating a full registry backup...")
            progress("Saved to " + backup.full_registry_backup(progress))
        if o["run"]:
            if self.app:
                progress(f"Removing package {self.app.full_name}...")
                ok, err = appx.uninstall(self.app, o["app_all_users"])
                progress("Package removed." if ok else f"Removal failed: {err}")
            else:
                self.uninstall_result = run_uninstaller(self.program, quiet=o["quiet"],
                                                        forced_msi=self.kind == "forced_msi",
                                                        progress=progress, cancelled=cancelled)
                r = self.uninstall_result
                if r.get("error"):
                    progress("Uninstaller error: " + r["error"])
                else:
                    progress(f"Built-in uninstaller finished after {r['seconds']} s (exit code {r['exit_code']}). "
                             + ("The program still appears to be installed." if r["still_installed"] else ""))
        items: list[Leftover] = []
        if o["use_log"] and self.log:
            progress(f"Reading traced log '{self.log['name']}'...")
            items += tracer.log_items(self.log)
        if o["mode"] and self.target:
            progress(f"Scanning for leftovers ({o['mode']} mode)...")
            # 'Continue' cancels only the wait for the uninstaller, never the scan
            items += scan(self.target, o["mode"], all_users=o["all_users"], progress=progress)
        if self.app:
            items += appx.leftovers(self.app)
        seen, uniq = set(), []
        for it in items:
            if it.ident not in seen:
                seen.add(it.ident)
                uniq.append(it)
        return uniq

    def _skip_wait(self):
        if self.worker:
            self.worker.cancel()
            self.btn_continue.setEnabled(False)
            self.log_line("Skipping the wait for the built-in uninstaller...")

    def _work_done(self, items: list[Leftover]):
        self.found_items = items
        self.bar.setRange(0, 1)
        self.bar.setValue(1)
        if self.kind == "traced" or (settings["auto_delete_leftovers"] and self.kind == "program"):
            targets = [i for i in items if i.created and not i.excluded]
            self.log_line(f"Removing {len(targets)} items automatically...")
            run_bg(self, lambda prog, c: backup.delete_items(targets, self._operation(), self._program_label(), prog),
                   self._auto_deleted, self.log_line)
            return
        reg = [i for i in items if i.is_registry]
        fs = [i for i in items if not i.is_registry]
        self.reg_tree.load(reg)
        self.fs_tree.load(fs)
        self.reg_page.count_label.setText(f"{len(reg)} registry items found, "
                                          f"{sum(1 for i in reg if i.created and not i.excluded)} created by the program.")
        self.fs_page.count_label.setText(f"{len(fs)} files/folders/other items found, "
                                         f"{sum(1 for i in fs if i.created and not i.excluded)} belong to the program.")
        if reg:
            self._set_step(2)
        elif fs:
            self._set_step(3)
        else:
            self._finish("No leftovers were found.")

    def _auto_deleted(self, manifest):
        self.manifests.append(manifest)
        self._finish()

    def _operation(self) -> str:
        return {"program": "Uninstall", "forced": "Forced Uninstall", "forced_msi": "Forced MSI Uninstall",
                "traced": "Traced Uninstall", "custom_traced": "Custom Uninstall", "appx": "Windows App"}[self.kind]

    def _delete(self, tree: LeftoverTree, items: list[Leftover] | None = None, then=None, ask: bool = True):
        """Delete the checked bold items (or `items`), then call `then()` if given."""
        sel = items if items is not None else tree.checked_items()
        if not sel:
            info(self, "Nothing selected. Check the bold items you want to delete.")
            return
        if ask and not confirm(self, f"Delete {len(sel)} selected item(s)?"):
            return
        self.setEnabled(False)

        def done(manifest):
            self.setEnabled(True)
            self.manifests.append(manifest)
            ok_paths = {(i["kind"], i["path"].lower(), i.get("value_name")) for i in manifest["items"]
                        if i["status"] not in ("failed", "skipped")}
            remaining = [i for i in tree.items if (i.kind, i.path.lower(), i.value_name) not in ok_paths]
            failed = sum(1 for i in manifest["items"] if i["status"] == "failed")
            tree.load(remaining, check_created=False)
            if failed:
                info(self, f"{failed} item(s) could not be deleted - see the summary for details.")
            if then:
                then()
        run_bg(self, lambda prog, c: backup.delete_items(sel, self._operation(), self._program_label(), prog), done)

    @staticmethod
    def _remaining(tree: LeftoverTree) -> list[Leftover]:
        """Bold (created, not excluded) leftovers still shown on a page, i.e. not deleted yet."""
        return [i for i in tree.items if i.created and not i.excluded]

    def _next_from_tree(self):
        tree = self.reg_tree if self.stack.currentIndex() == 2 else self.fs_tree
        go_next = (lambda: self._set_step(3)) if (self.stack.currentIndex() == 2 and self.fs_tree.items) \
            else self._show_summary
        remaining = self._remaining(tree)
        if not remaining:
            go_next()
            return
        # Leaving a page with undeleted leftovers - make sure that is intended
        checked = tree.checked_items()
        what = "registry items" if tree is self.reg_tree else "files and folders"
        box = QMessageBox(QMessageBox.Warning, "Leftovers not deleted",
                          f"{len(remaining)} leftover {what} created by {self._program_label()} have not been "
                          f"deleted yet.\n\nNothing is removed unless you click Delete. What do you want to do?",
                          parent=self)
        if checked:
            b_del = box.addButton(f"Delete {len(checked)} checked and continue", QMessageBox.AcceptRole)
        else:
            b_del = box.addButton(f"Delete all {len(remaining)} and continue", QMessageBox.AcceptRole)
        b_skip = box.addButton("Continue without deleting", QMessageBox.DestructiveRole)
        b_stay = box.addButton("Stay on this page", QMessageBox.RejectRole)
        box.setDefaultButton(b_stay)
        box.exec()
        clicked = box.clickedButton()
        if clicked is b_del:
            self._delete(tree, checked or remaining, then=go_next, ask=False)
        elif clicked is b_skip:
            go_next()

    def _finish(self, note: str = ""):
        self._show_summary(note)

    def _show_summary(self, note: str | None = None):
        if note is not None:
            self._note = note
        note = getattr(self, "_note", "")
        items = [i for m in self.manifests for i in m["items"]]
        ok = [i for i in items if i["status"] in ("deleted", "recycled", "backed_up")]
        reboot = [i for i in items if i["status"] == "reboot"]
        failed = [i for i in items if i["status"] == "failed"]
        left = len(self._remaining(self.reg_tree)) + len(self._remaining(self.fs_tree))
        self.summary_back.setVisible(bool(self.reg_tree.items or self.fs_tree.items))
        left_note = (f"<p style='color:{theme.color('danger').name()}'><b>{left} leftover item(s) were not deleted.</b> Click "
                     f"<b>Back to leftovers</b> to remove them before finishing.</p>" if left else "")
        self.summary.setText(
            f"<h3>Summary</h3>{note}<p>Removed: <b>{len(ok)}</b> &nbsp; Pending restart: <b>{len(reboot)}</b>"
            f" &nbsp; Failed: <b>{len(failed)}</b></p>{left_note}<p>Deleted registry items are in the Backup "
            f"Manager. Click Finish to record this uninstall in Uninstall History.</p>")
        self.details.setPlainText("\n".join(
            f"[{i['status']}] {i['kind']}: {i['path']}" + (f" -> {i['value_name']}" if i.get("value_name") is not None
                                                          else "") + (f"  ({i['detail']})" if i.get("detail") else "")
            for i in items) or "Nothing was deleted.")
        self._set_step(4)

    def _back_from_summary(self):
        # Prefer the page that still has undeleted leftovers
        if self._remaining(self.fs_tree) or (self.fs_tree.items and not self._remaining(self.reg_tree)):
            self._set_step(3)
        else:
            self._set_step(2)

    def done(self, result: int):
        """Record Uninstall History exactly once, when the wizard closes after something happened."""
        if not getattr(self, "_recorded", False) and (self.manifests or self.stack.currentIndex() == 4):
            self._recorded = True
            items = [i for m in self.manifests for i in m["items"]]
            program = self.program.to_dict() if self.program else (
                {"name": self._program_label(), "version": self.app.version if self.app else ""})
            combined = {"id": self.manifests[-1]["id"] if self.manifests else None, "items": items}
            left = len(self._remaining(self.reg_tree)) + len(self._remaining(self.fs_tree))
            note = getattr(self, "_note", "") + (f" {left} leftover item(s) were left in place." if left else "")
            if self.kind == "traced" and self.log and settings["delete_log_after_uninstall"]:
                tracer.delete_log(self.log["id"])
            backup.add_history(program, self._operation(), self._mode() if self.kind != "traced" else "log",
                               combined, note.strip())
        super().done(result)


class QuickUninstallDialog(QDialog):
    """Uninstall several programs in a row: silent uninstaller, moderate scan, automatic removal."""

    def __init__(self, parent, progs: list = (), apps: list = ()):
        super().__init__(parent)
        self.progs, self.apps = list(progs), list(apps)
        self.setWindowTitle("Quick uninstall")
        self.resize(820, 560)
        v = QVBoxLayout(self)
        names = [p.name for p in self.progs] + [a.display_name for a in self.apps]
        v.addWidget(QLabel("<b>Quick uninstall</b><br>" + "<br>".join(names)))
        row = QHBoxLayout()
        row.addWidget(QLabel("Scan mode:"))
        self.mode_group = QButtonGroup(self)
        for i, m in enumerate(("safe", "moderate", "advanced")):
            rb = QRadioButton(m.title())
            rb.setProperty("mode", m)
            rb.setChecked(m == "moderate")
            self.mode_group.addButton(rb, i)
            row.addWidget(rb)
        row.addStretch(1)
        v.addLayout(row)
        self.logbox = QPlainTextEdit()
        self.logbox.setReadOnly(True)
        v.addWidget(self.logbox, 1)
        row = QHBoxLayout()
        self.btn_skip = button("Continue", self._skip, "Stop waiting for the current uninstaller")
        self.btn_skip.setEnabled(False)
        row.addWidget(self.btn_skip)
        row.addStretch(1)
        self.btn_start = button("Start", self._start, primary=True)
        row.addWidget(self.btn_start)
        self.btn_close = button("Close", self.accept)
        row.addWidget(self.btn_close)
        v.addLayout(row)
        self.worker = None
        self.skip_flag = False

    def _skip(self):
        self.skip_flag = True

    def _start(self):
        if not confirm(self, f"Uninstall {len(self.progs) + len(self.apps)} program(s) and delete their leftovers?"):
            return
        self.btn_start.setEnabled(False)
        self.btn_close.setEnabled(False)
        self.btn_skip.setEnabled(True)
        mode = self.mode_group.checkedButton().property("mode")
        self.worker = run_bg(self, lambda prog, c: self._work(mode, prog), self._done, self.logbox.appendPlainText)

    def _work(self, mode, progress):
        if settings["create_restore_point"] and wu.is_admin():
            progress(backup.create_restore_point("OpenUninstaller: before quick uninstall")[1])
        results = []
        for p in self.progs:
            progress(f"\n=== {p.name} ===")
            target = Target.from_program(p)
            self.skip_flag = False
            r = run_uninstaller(p, quiet=True, progress=progress, cancelled=lambda: self.skip_flag)
            progress(r.get("error") or f"Uninstaller done ({r.get('seconds')} s).")
            items = [i for i in scan(target, mode, progress=progress) if i.created and not i.excluded]
            m = backup.delete_items(items, "Quick Uninstall", p.name, progress)
            backup.add_history(p.to_dict(), "Quick Uninstall", mode, m)
            results.append((p.name, m))
        for a in self.apps:
            progress(f"\n=== {a.display_name} ===")
            ok, err = appx.uninstall(a)
            progress("Removed." if ok else f"Failed: {err}")
            t = Target(names=[a.display_name, a.name], publisher=a.publisher)
            items = [i for i in scan(t, mode, progress=progress) + appx.leftovers(a) if i.created and not i.excluded]
            m = backup.delete_items(items, "Quick Uninstall", a.display_name, progress)
            backup.add_history({"name": a.display_name, "version": a.version}, "Quick Uninstall", mode, m)
            results.append((a.display_name, m))
        return results

    def _done(self, results):
        self.btn_close.setEnabled(True)
        self.btn_skip.setEnabled(False)
        self.logbox.appendPlainText("\n=== Summary ===")
        for name, m in results:
            ok = sum(1 for i in m["items"] if i["status"] != "failed")
            self.logbox.appendPlainText(f"{name}: {ok} leftovers removed, {len(m['items']) - ok} failed")
        self.logbox.appendPlainText("Finished.")
