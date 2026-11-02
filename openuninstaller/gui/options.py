"""Options dialog."""

from __future__ import annotations

import winreg

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QFormLayout, QHBoxLayout, QInputDialog, QLabel,
                               QListWidget, QListWidgetItem, QSpinBox, QTabWidget, QVBoxLayout, QWidget)

from .. import winutil as wu
from ..config import DEFAULT_JUNK_PATTERNS, settings
from .common import button, confirm

CTX_KEYS = [r"Software\Classes\Directory\shell\OpenUninstaller", r"Software\Classes\lnkfile\shell\OpenUninstaller",
            r"Software\Classes\exefile\shell\OpenUninstaller"]
CTX_INSTALL_KEY = r"Software\Classes\exefile\shell\OpenUninstallerTrace"


def context_menu_installed() -> bool:
    return wu.key_exists(winreg.HKEY_CURRENT_USER, CTX_KEYS[0])


def set_context_menu(enabled: bool) -> None:
    for sub in CTX_KEYS + [CTX_INSTALL_KEY]:
        try:
            wu.delete_key_tree(winreg.HKEY_CURRENT_USER, sub)
        except OSError:
            pass
    if not enabled:
        return
    command = " ".join(f'"{part}"' for part in wu.self_command())
    entries = [(sub, "Uninstall with OpenUninstaller", "--forced") for sub in CTX_KEYS]
    entries.append((CTX_INSTALL_KEY, "Install with OpenUninstaller (trace)", "--trace"))
    for sub, label, flag in entries:
        wu.set_value(winreg.HKEY_CURRENT_USER, sub, "", winreg.REG_SZ, label)
        wu.set_value(winreg.HKEY_CURRENT_USER, sub, "Icon", winreg.REG_SZ, "shell32.dll,31")
        wu.set_value(winreg.HKEY_CURRENT_USER, sub + r"\command", "", winreg.REG_SZ,
                     f'{command} {flag} "%1"')


class ListEditor(QWidget):
    """Editable list of strings, optionally with check boxes."""

    def __init__(self, items, checks: dict | None = None, defaults=None, hint: str = ""):
        super().__init__()
        self.defaults = defaults
        v = QVBoxLayout(self)
        if hint:
            lbl = QLabel(hint)
            lbl.setWordWrap(True)
            v.addWidget(lbl)
        self.list = QListWidget()
        v.addWidget(self.list, 1)
        self.checkable = checks is not None
        self._fill(items, checks)
        row = QHBoxLayout()
        row.addWidget(button("Add...", self._add))
        row.addWidget(button("Remove", lambda: [self.list.takeItem(self.list.row(i)) for i in self.list.selectedItems()]))
        if defaults is not None:
            row.addWidget(button("Reset defaults", self._reset))
        row.addStretch(1)
        v.addLayout(row)

    def _fill(self, items, checks=None):
        self.list.clear()
        for s in items:
            it = QListWidgetItem(s)
            it.setFlags(it.flags() | Qt.ItemIsEditable)
            if self.checkable:
                it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
                it.setCheckState(Qt.Checked if (checks or {}).get(s, True) else Qt.Unchecked)
            self.list.addItem(it)

    def _add(self):
        text, ok = QInputDialog.getText(self, "Add", "Value (wildcards * and ? allowed):")
        if ok and text:
            self._fill(self.values() + [text], self.checks())

    def _reset(self):
        if confirm(self, "Restore the default list?"):
            d = self.defaults
            self._fill(list(d) if not isinstance(d, dict) else list(d.keys()), None)

    def values(self) -> list[str]:
        return [self.list.item(i).text() for i in range(self.list.count())]

    def checks(self) -> dict:
        return {self.list.item(i).text(): self.list.item(i).checkState() == Qt.Checked
                for i in range(self.list.count())}


class OptionsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        from ..config import DEFAULT_FOLDER_EXCLUDES, DEFAULT_JUNK_EXCLUDES, DEFAULT_REG_EXCLUDES
        self.setWindowTitle("Options")
        self.resize(820, 600)
        v = QVBoxLayout(self)
        tabs = QTabWidget()
        v.addWidget(tabs, 1)
        self.checks: dict[str, QCheckBox] = {}

        def cb(form, key, text):
            c = QCheckBox(text)
            c.setChecked(bool(settings[key]))
            self.checks[key] = c
            form.addRow(c)

        g = QWidget()
        f = QFormLayout(g)
        self.theme = QComboBox()
        self.theme.addItems(["system", "light", "dark"])
        self.theme.setToolTip("system follows the Windows light/dark app setting")
        self.theme.setCurrentText(settings["theme"])
        f.addRow("Theme:", self.theme)
        self.ctx = QCheckBox("Show 'Uninstall with / Install with OpenUninstaller' in the Explorer context menu")
        self.ctx.setChecked(context_menu_installed())
        f.addRow(self.ctx)
        self.days = QSpinBox()
        self.days.setRange(1, 365)
        self.days.setValue(settings["new_program_days"])
        f.addRow("Show programs as 'new' for (days):", self.days)
        cb(f, "include_cloud_folders", "Include phone and cloud storage folders (Phone Link, OneDrive, Dropbox...) "
                                       "in scans and deletions")
        roots = wu.sync_roots(refresh=True)
        note = QLabel("Off (recommended): these folders are skipped everywhere - Junk Cleaner, leftover scans, "
                      "install tracing, shredder - because deleting there deletes on the phone / in the cloud.\n"
                      "Detected: " + ("; ".join(f"{name} ({path})" for path, name in roots) if roots else "none"))
        note.setWordWrap(True)
        note.setObjectName("pageDesc")
        f.addRow(note)
        tabs.addTab(g, "General")

        u = QWidget()
        f = QFormLayout(u)
        cb(f, "create_restore_point", "Create a System Restore point before uninstalling")
        cb(f, "full_registry_backup", "Create a full registry backup before uninstalling")
        cb(f, "backup_registry_items", "Back up deleted registry items (restore them in the Backup Manager)")
        cb(f, "kill_running_exes", "Force-close running programs whose folder is being deleted")
        cb(f, "check_all_leftovers", "Check all leftovers created by the program by default")
        cb(f, "scan_all_users", "Scan all Windows accounts for leftovers by default")
        cb(f, "only_builtin_uninstaller", "Only run the built-in uninstaller (no leftover scan)")
        cb(f, "auto_delete_leftovers", "Automatically delete all leftovers created by the program")
        cb(f, "open_wizard_maximized", "Open the uninstall wizard maximized")
        cb(f, "delete_log_after_uninstall", "Delete a trace log after its program is uninstalled")
        cb(f, "show_system_components", "Show system components in All Programs")
        cb(f, "show_updates", "Show Windows updates in All Programs")
        self.mode = QComboBox()
        self.mode.addItems(["safe", "moderate", "advanced"])
        self.mode.setCurrentText(settings["default_scan_mode"])
        f.addRow("Default scan mode:", self.mode)
        self.fmode = QComboBox()
        self.fmode.addItems(["recycle", "backup", "permanent"])
        self.fmode.setCurrentText(settings["file_delete_mode"])
        f.addRow("Delete leftover files to:", self.fmode)
        tabs.addTab(u, "Uninstaller")

        self.reg_ex = ListEditor(settings["reg_excludes"], defaults=DEFAULT_REG_EXCLUDES,
                                 hint="Registry keys that are never deleted. Full paths, e.g. "
                                      "HKEY_LOCAL_MACHINE\\SOFTWARE\\Classes. Wildcards: ? one character, "
                                      "* anything (add \\* to also protect all sub keys).")
        tabs.addTab(self.reg_ex, "Excluded registry keys")
        self.dir_ex = ListEditor(settings["folder_excludes"], defaults=DEFAULT_FOLDER_EXCLUDES,
                                 hint="Folders that are never deleted. Environment variables and wildcards allowed.")
        tabs.addTab(self.dir_ex, "Excluded folders")

        j = QWidget()
        jv = QVBoxLayout(j)
        jf = QFormLayout()
        cb(jf, "junk_recycle", "Delete junk files to the Recycle Bin")
        cb(jf, "junk_skip_recent", "Ignore files accessed in the last 24 hours")
        jv.addLayout(jf)
        jt = QTabWidget()
        self.junk_pats = ListEditor(list(settings["junk_patterns"].keys()), checks=settings["junk_patterns"],
                                    defaults=DEFAULT_JUNK_PATTERNS)
        self.junk_ex = ListEditor(settings["junk_excludes"], defaults=DEFAULT_JUNK_EXCLUDES,
                                  hint="Folders skipped by the junk scan.")
        self.junk_inc = ListEditor(settings["junk_includes"], defaults=[],
                                   hint="Folders whose entire content is junk. Only add folders with no personal data!")
        jt.addTab(self.junk_pats, "Patterns")
        jt.addTab(self.junk_ex, "Exclude")
        jt.addTab(self.junk_inc, "Include")
        jv.addWidget(jt, 1)
        tabs.addTab(j, "Junk Files Cleaner")

        grp = ListEditor(settings["groups"], defaults=["Internet", "Games", "Multimedia", "Utilities"],
                         hint="Groups you can assign programs to (All Programs > right-click > Assign to group).")
        self.groups = grp
        tabs.addTab(grp, "Groups")

        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(button("Cancel", self.reject))
        row.addWidget(button("OK", self._save, primary=True))
        v.addLayout(row)

    def _save(self):
        for key, c in self.checks.items():
            settings.data[key] = c.isChecked()
        settings.data.update({
            "theme": self.theme.currentText(), "new_program_days": self.days.value(),
            "default_scan_mode": self.mode.currentText(), "file_delete_mode": self.fmode.currentText(),
            "reg_excludes": self.reg_ex.values(), "folder_excludes": self.dir_ex.values(),
            "junk_patterns": self.junk_pats.checks(), "junk_excludes": self.junk_ex.values(),
            "junk_includes": self.junk_inc.values(), "groups": self.groups.values(),
        })
        settings.save()
        if self.ctx.isChecked() != context_menu_installed():
            set_context_menu(self.ctx.isChecked())
        self.accept()
