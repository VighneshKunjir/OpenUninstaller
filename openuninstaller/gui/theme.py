"""Light / dark / system themes.

Three layers are needed for a consistent look with the Fusion style:
1. a QPalette (Fusion paints scrollbars, check marks, tabs, spin boxes and dialogs from it),
2. small SVG icons for check boxes, radio buttons and arrows, written per theme to the data folder,
3. a stylesheet using the same colour tokens.
Item colours that code sets directly (e.g. grey/red rows in the leftover tree) come from color().
"""

from __future__ import annotations

import os
import winreg

from PySide6.QtCore import QEvent, QObject
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication, QWidget

from .. import winutil as wu
from ..config import DATA_DIR, settings

LIGHT = {
    "bg": "#f4f6fa", "panel": "#ffffff", "alt": "#f7f9fc", "fg": "#1d2433", "muted": "#5f6b80",
    "faint": "#8a94a6", "border": "#d3dae6", "border_strong": "#9aa6ba", "accent": "#2f7bf6",
    "accent_hover": "#1f66db", "accent_fg": "#ffffff", "side": "#1f2a3c", "side_fg": "#c9d3e3",
    "side_head": "#7f8ca3", "danger": "#c62828", "warn": "#9a6700", "success": "#2e7d32",
    "scroll": "#c3cbd8", "scroll_hover": "#9aa6ba", "hover": "#eef3fd", "sel_inactive": "#dbe6fb",
    "tooltip": "#1f2a3c", "tooltip_fg": "#ffffff",
}
DARK = {
    "bg": "#161a22", "panel": "#1e232d", "alt": "#232936", "fg": "#e3e8f1", "muted": "#9aa5b8",
    "faint": "#7d889c", "border": "#2f3644", "border_strong": "#566075", "accent": "#4b8ef8",
    "accent_hover": "#6aa2fa", "accent_fg": "#ffffff", "side": "#10141b", "side_fg": "#b4bfd1",
    "side_head": "#6c788d", "danger": "#ff6b6b", "warn": "#e3b341", "success": "#5fd38d",
    "scroll": "#3a4252", "scroll_hover": "#566075", "hover": "#262d3a", "sel_inactive": "#2c3a55",
    "tooltip": "#2a3140", "tooltip_fg": "#e3e8f1",
}

_current = LIGHT


def windows_uses_dark() -> bool:
    v = wu.get_value(winreg.HKEY_CURRENT_USER,
                     r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize", "AppsUseLightTheme")
    return v == 0


def resolved_theme() -> str:
    t = settings["theme"]
    if t == "system":
        return "dark" if windows_uses_dark() else "light"
    return "dark" if t == "dark" else "light"


def color(name: str) -> QColor:
    """A colour token of the active theme, for code that paints items directly."""
    return QColor(_current[name])


def is_dark() -> bool:
    return _current is DARK


# ---------------------------------------------------------------- palette


def _palette(c: dict) -> QPalette:
    p = QPalette()
    roles = {
        QPalette.Window: c["bg"], QPalette.WindowText: c["fg"], QPalette.Base: c["panel"],
        QPalette.AlternateBase: c["alt"], QPalette.Text: c["fg"], QPalette.Button: c["panel"],
        QPalette.ButtonText: c["fg"], QPalette.Highlight: c["accent"], QPalette.HighlightedText: c["accent_fg"],
        QPalette.ToolTipBase: c["tooltip"], QPalette.ToolTipText: c["tooltip_fg"], QPalette.Link: c["accent"],
        QPalette.LinkVisited: c["accent"], QPalette.PlaceholderText: c["faint"], QPalette.BrightText: c["danger"],
        QPalette.Light: c["border"], QPalette.Midlight: c["border"], QPalette.Mid: c["border_strong"],
        QPalette.Dark: c["border_strong"], QPalette.Shadow: "#000000",
    }
    for role, value in roles.items():
        p.setColor(role, QColor(value))
    for role in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText):
        p.setColor(QPalette.Disabled, role, QColor(c["faint"]))
    p.setColor(QPalette.Disabled, QPalette.Base, QColor(c["alt"]))
    p.setColor(QPalette.Disabled, QPalette.Button, QColor(c["alt"]))
    p.setColor(QPalette.Inactive, QPalette.Highlight, QColor(c["sel_inactive"]))
    p.setColor(QPalette.Inactive, QPalette.HighlightedText, QColor(c["fg"]))
    return p


# ---------------------------------------------------------------- icons


def _icons(name: str, c: dict) -> dict[str, str]:
    """Write the SVG icons for a theme and return {icon: path with forward slashes}."""
    folder = os.path.join(DATA_DIR, "theme", name)
    os.makedirs(folder, exist_ok=True)
    fg, muted, faint = c["accent_fg"], c["muted"], c["faint"]
    svgs = {
        "check": f'<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16"><path d="M3.5 8.2l3 3 6-6.4" '
                 f'fill="none" stroke="{fg}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>',
        "partial": f'<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16"><rect x="4" y="7" width="8" '
                   f'height="2" rx="1" fill="{fg}"/></svg>',
        "dot": f'<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16"><circle cx="8" cy="8" r="3.5" '
               f'fill="{fg}"/></svg>',
        "down": f'<svg xmlns="http://www.w3.org/2000/svg" width="12" height="12"><path d="M2.5 4.5l3.5 3.5 3.5-3.5" '
                f'fill="none" stroke="{muted}" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg>',
        "up": f'<svg xmlns="http://www.w3.org/2000/svg" width="12" height="12"><path d="M2.5 7.5l3.5-3.5 3.5 3.5" '
              f'fill="none" stroke="{muted}" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg>',
        "down_disabled": f'<svg xmlns="http://www.w3.org/2000/svg" width="12" height="12"><path d="M2.5 4.5l3.5 '
                         f'3.5 3.5-3.5" fill="none" stroke="{faint}" stroke-width="1.6" stroke-linecap="round"/></svg>',
        "branch_closed": f'<svg xmlns="http://www.w3.org/2000/svg" width="12" height="12"><path d="M4.5 2.5l3.5 3.5'
                         f'-3.5 3.5" fill="none" stroke="{muted}" stroke-width="1.6" stroke-linecap="round" '
                         f'stroke-linejoin="round"/></svg>',
        "branch_open": f'<svg xmlns="http://www.w3.org/2000/svg" width="12" height="12"><path d="M2.5 4.5l3.5 3.5 '
                       f'3.5-3.5" fill="none" stroke="{muted}" stroke-width="1.6" stroke-linecap="round" '
                       f'stroke-linejoin="round"/></svg>',
    }
    out = {}
    for key, svg in svgs.items():
        path = os.path.join(folder, key + ".svg")
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(svg)
        except OSError:
            pass
        out[key] = path.replace("\\", "/")
    return out


# ---------------------------------------------------------------- stylesheet


def stylesheet(c: dict, i: dict) -> str:
    return f"""
    QWidget {{ font-family: 'Segoe UI'; font-size: 10pt; color: {c['fg']}; }}
    QMainWindow, QDialog, QMessageBox {{ background: {c['bg']}; }}
    QLabel {{ background: transparent; }}
    #content {{ background: {c['bg']}; }}

    /* sidebar */
    #sideFooter {{ background: {c['side']}; }}
    #sidebar {{ background: {c['side']}; border: none; outline: 0; }}
    #sidebar::item {{ padding: 7px 14px; color: {c['side_fg']}; border-radius: 6px; margin: 1px 6px; }}
    #sidebar::item:disabled {{ color: {c['side_head']}; padding-top: 12px; }}
    #sidebar::item:selected {{ background: {c['accent']}; color: {c['accent_fg']}; }}
    #sidebar::item:hover:!selected:enabled {{ background: rgba(255,255,255,0.07); }}
    #brand {{ background: {c['side']}; color: #ffffff; font-size: 13pt; font-weight: 600; padding: 14px 16px 8px 16px; }}
    #sideFooter QPushButton {{ background: rgba(255,255,255,0.06); color: {c['side_fg']};
        border: 1px solid rgba(255,255,255,0.10); }}
    #sideFooter QPushButton:hover {{ background: rgba(255,255,255,0.12); border-color: {c['accent']}; color: #ffffff; }}

    #pageTitle {{ font-size: 16pt; font-weight: 600; }}
    #pageDesc {{ color: {c['muted']}; }}
    #warning {{ color: {c['warn']}; }}

    /* inputs and views */
    QTableView, QTreeView, QTreeWidget, QListView, QListWidget, QPlainTextEdit, QTextEdit {{
        background: {c['panel']}; alternate-background-color: {c['alt']}; border: 1px solid {c['border']};
        border-radius: 6px; selection-background-color: {c['accent']}; selection-color: {c['accent_fg']};
        outline: 0; }}
    QTableView {{ gridline-color: {c['border']}; }}
    QTableView::item:hover, QTreeView::item:hover, QListView::item:hover {{ background: {c['hover']}; }}
    QTableView::item:selected, QTreeView::item:selected, QListView::item:selected {{
        background: {c['accent']}; color: {c['accent_fg']}; }}
    QTableView::item:selected:!active, QTreeView::item:selected:!active, QListView::item:selected:!active {{
        background: {c['sel_inactive']}; color: {c['fg']}; }}
    QTreeView::branch:has-children:closed {{ image: url({i['branch_closed']}); }}
    QTreeView::branch:has-children:open {{ image: url({i['branch_open']}); }}
    QLineEdit, QComboBox, QSpinBox, QDateEdit {{ background: {c['panel']}; border: 1px solid {c['border']};
        border-radius: 6px; padding: 4px 8px; min-height: 22px; selection-background-color: {c['accent']};
        selection-color: {c['accent_fg']}; }}
    QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDateEdit:focus {{ border-color: {c['accent']}; }}
    QComboBox::drop-down, QDateEdit::drop-down {{ border: none; width: 24px; }}
    QComboBox::down-arrow, QDateEdit::down-arrow {{ image: url({i['down']}); width: 12px; height: 12px; }}
    QComboBox QAbstractItemView {{ background: {c['panel']}; border: 1px solid {c['border']}; padding: 4px;
        selection-background-color: {c['accent']}; selection-color: {c['accent_fg']}; outline: 0; }}
    QSpinBox {{ padding-right: 22px; }}
    QSpinBox::up-button, QSpinBox::down-button {{ subcontrol-origin: border; width: 20px; border: none;
        background: transparent; }}
    QSpinBox::up-button {{ subcontrol-position: top right; }}
    QSpinBox::down-button {{ subcontrol-position: bottom right; }}
    QSpinBox::up-arrow {{ image: url({i['up']}); width: 10px; height: 10px; }}
    QSpinBox::down-arrow {{ image: url({i['down']}); width: 10px; height: 10px; }}

    QHeaderView {{ background: {c['panel']}; border: none; }}
    QHeaderView::section {{ background: {c['panel']}; color: {c['muted']}; border: none;
        border-bottom: 1px solid {c['border']}; border-right: 1px solid {c['border']}; padding: 5px 8px;
        font-weight: 600; }}
    QHeaderView::section:last {{ border-right: none; }}
    QHeaderView::down-arrow {{ image: url({i['down']}); width: 10px; height: 10px; }}
    QHeaderView::up-arrow {{ image: url({i['up']}); width: 10px; height: 10px; }}
    QTableCornerButton::section {{ background: {c['panel']}; border: none; }}

    /* check boxes and radio buttons (stand-alone and inside item views) */
    QCheckBox, QRadioButton {{ spacing: 7px; background: transparent; }}
    QCheckBox::indicator, QTreeView::indicator, QTableView::indicator, QListView::indicator {{
        width: 14px; height: 14px; border: 1px solid {c['border_strong']}; border-radius: 3px;
        background: {c['panel']}; }}
    QCheckBox::indicator:hover, QTreeView::indicator:hover, QTableView::indicator:hover,
    QListView::indicator:hover {{ border-color: {c['accent']}; }}
    QCheckBox::indicator:checked, QTreeView::indicator:checked, QTableView::indicator:checked,
    QListView::indicator:checked {{ background: {c['accent']}; border-color: {c['accent']};
        image: url({i['check']}); }}
    QCheckBox::indicator:indeterminate, QTreeView::indicator:indeterminate,
    QTableView::indicator:indeterminate, QListView::indicator:indeterminate {{ background: {c['accent']};
        border-color: {c['accent']}; image: url({i['partial']}); }}
    QCheckBox::indicator:disabled {{ background: {c['alt']}; border-color: {c['border']}; }}
    QCheckBox::indicator:checked:disabled {{ background: {c['border_strong']}; border-color: {c['border_strong']}; }}
    QRadioButton::indicator {{ width: 14px; height: 14px; border: 1px solid {c['border_strong']};
        border-radius: 8px; background: {c['panel']}; }}
    QRadioButton::indicator:hover {{ border-color: {c['accent']}; }}
    QRadioButton::indicator:checked {{ background: {c['accent']}; border-color: {c['accent']}; image: url({i['dot']}); }}

    /* buttons */
    QPushButton, QToolButton {{ background: {c['panel']}; border: 1px solid {c['border']}; border-radius: 6px;
        padding: 5px 14px; min-height: 22px; color: {c['fg']}; }}
    QPushButton:hover, QToolButton:hover {{ border-color: {c['accent']}; background: {c['hover']}; }}
    QPushButton:pressed, QToolButton:pressed {{ background: {c['sel_inactive']}; }}
    QPushButton:disabled, QToolButton:disabled {{ color: {c['faint']}; background: {c['alt']}; border-color: {c['border']}; }}
    QPushButton#primary {{ background: {c['accent']}; color: {c['accent_fg']}; border: 1px solid {c['accent']};
        font-weight: 600; }}
    QPushButton#primary:hover {{ background: {c['accent_hover']}; border-color: {c['accent_hover']}; }}
    QPushButton#primary:disabled {{ background: {c['border_strong']}; border-color: {c['border_strong']}; }}
    QToolButton[popupMode="2"] {{ padding-right: 26px; }}
    QToolButton::menu-indicator {{ image: url({i['down']}); subcontrol-origin: padding;
        subcontrol-position: center right; right: 8px; width: 12px; height: 12px; }}

    /* containers */
    QGroupBox {{ border: 1px solid {c['border']}; border-radius: 8px; margin-top: 12px; padding: 10px;
        background: transparent; }}
    QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 4px; font-weight: 600; color: {c['fg']}; }}
    QTabWidget::pane {{ border: 1px solid {c['border']}; border-radius: 6px; background: {c['panel']}; top: -1px; }}
    QTabBar::tab {{ background: transparent; color: {c['muted']}; border: none; border-bottom: 2px solid transparent;
        padding: 7px 14px; margin-right: 2px; }}
    QTabBar::tab:hover {{ color: {c['fg']}; }}
    QTabBar::tab:selected {{ color: {c['fg']}; border-bottom: 2px solid {c['accent']}; font-weight: 600; }}
    QProgressBar {{ border: 1px solid {c['border']}; border-radius: 6px; text-align: center; background: {c['panel']};
        color: {c['fg']}; min-height: 18px; }}
    QProgressBar::chunk {{ background: {c['accent']}; border-radius: 5px; }}

    /* scroll bars */
    QScrollBar:vertical {{ background: transparent; width: 12px; margin: 2px; }}
    QScrollBar:horizontal {{ background: transparent; height: 12px; margin: 2px; }}
    QScrollBar::handle:vertical {{ background: {c['scroll']}; border-radius: 4px; min-height: 28px; }}
    QScrollBar::handle:horizontal {{ background: {c['scroll']}; border-radius: 4px; min-width: 28px; }}
    QScrollBar::handle:hover {{ background: {c['scroll_hover']}; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; border: none; background: none; }}
    QScrollBar::add-page, QScrollBar::sub-page {{ background: none; }}
    QAbstractScrollArea::corner {{ background: transparent; border: none; }}

    /* menus and tooltips */
    QMenu {{ background: {c['panel']}; border: 1px solid {c['border']}; padding: 4px; }}
    QMenu::item {{ padding: 6px 24px 6px 14px; border-radius: 4px; color: {c['fg']}; }}
    QMenu::item:selected {{ background: {c['accent']}; color: {c['accent_fg']}; }}
    QMenu::item:disabled {{ color: {c['faint']}; }}
    QMenu::separator {{ height: 1px; background: {c['border']}; margin: 4px 6px; }}
    QToolTip {{ background: {c['tooltip']}; color: {c['tooltip_fg']}; border: 1px solid {c['border']};
        padding: 4px 6px; }}
    QCalendarWidget QWidget {{ alternate-background-color: {c['alt']}; }}
    """


# ---------------------------------------------------------------- dark title bars


class _TitleBarFilter(QObject):
    """Ask Windows (DWM) for a dark/light title bar on every top-level window as it is shown."""

    def eventFilter(self, obj, ev):
        if ev.type() == QEvent.Show and isinstance(obj, QWidget) and obj.isWindow():
            set_title_bar(obj)
        return False


def set_title_bar(w: QWidget) -> None:
    try:
        import ctypes
        hwnd = int(w.winId())
        value = ctypes.c_int(1 if is_dark() else 0)
        for attr in (20, 19):   # DWMWA_USE_IMMERSIVE_DARK_MODE (Win10 20H1+ = 20, older builds = 19)
            if ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(value), ctypes.sizeof(value)) == 0:
                break
    except Exception:
        pass


_filter: _TitleBarFilter | None = None


def apply_theme(app: QApplication) -> None:
    global _current, _filter
    name = resolved_theme()
    _current = DARK if name == "dark" else LIGHT
    app.setStyle("Fusion")
    app.setPalette(_palette(_current))
    app.setStyleSheet(stylesheet(_current, _icons(name, _current)))
    if _filter is None:
        _filter = _TitleBarFilter(app)
        app.installEventFilter(_filter)
    for w in app.topLevelWidgets():
        if w.isVisible():
            set_title_bar(w)
