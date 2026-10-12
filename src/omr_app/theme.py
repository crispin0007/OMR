"""Colour tokens, the user's display preferences, and the Settings page (spec 002 UI-004, UI-005).

Every colour on every screen comes from `tokens()`, so light, dark and the
accent colour reach all of them at once.
"""

from dataclasses import asdict, dataclass

from PySide6.QtCore import QSettings, Qt, Signal
from PySide6.QtGui import QColor, QGuiApplication, QPalette
from PySide6.QtWidgets import (QApplication, QColorDialog, QComboBox, QFormLayout, QHBoxLayout,
                               QLabel, QPushButton, QVBoxLayout, QWidget)

LIGHT = dict(bg="#f4f5fa", card="#ffffff", border="#e2e4ee", text="#1d1f2c", muted="#6b6f85",
             good="#1f9d55", warn="#c27c00", warn_bg="#fff1d6", bad="#d64545")
DARK = dict(bg="#12131c", card="#1c1e2b", border="#2c2f42", text="#e8e9f2", muted="#9a9db3",
            good="#35c47a", warn="#f5b041", warn_bg="#4a3a14", bad="#ff6b6b")
ACCENTS = {"Violet": "#7c5cff", "Blue": "#2f80ed", "Teal": "#14a39a", "Green": "#2e9d4f",
           "Orange": "#f2994a", "Pink": "#e0457b"}
THEMES = ("System", "Light", "Dark")
FONT_PT = {"Small": 9, "Normal": 10, "Large": 12}
PAD_PX = {"Compact": 4, "Comfortable": 8}


@dataclass
class Prefs:
    theme: str = "System"
    accent: str = ACCENTS["Violet"]
    font: str = "Normal"
    density: str = "Comfortable"


def settings() -> QSettings:
    return QSettings(QSettings.IniFormat, QSettings.UserScope, "OMR", "OMR")  # %APPDATA%\OMR\OMR.ini on Windows


def load_prefs() -> Prefs:
    s, p = settings(), Prefs()
    # The file can be edited by hand; anything unknown falls back to the default.
    theme, accent = s.value("theme", p.theme), s.value("accent", p.accent)
    font, density = s.value("font", p.font), s.value("density", p.density)
    return Prefs(theme if theme in THEMES else p.theme,
                 accent if isinstance(accent, str) and QColor.isValidColorName(accent) else p.accent,
                 font if font in FONT_PT else p.font, density if density in PAD_PX else p.density)


def save_prefs(p: Prefs):
    s = settings()
    for k, v in asdict(p).items():
        s.setValue(k, v)


def is_dark(p: Prefs) -> bool:
    if p.theme != "System":
        return p.theme == "Dark"
    return QGuiApplication.styleHints().colorScheme() == Qt.ColorScheme.Dark


_current = dict(LIGHT, accent=ACCENTS["Violet"])


def tokens() -> dict[str, str]:
    """The colours in use now, for widgets that paint themselves."""
    return _current


def apply(app: QApplication, p: Prefs):
    global _current
    t = _current = dict(DARK if is_dark(p) else LIGHT, accent=p.accent)
    pt, pad = FONT_PT[p.font], PAD_PX[p.density]
    app.setStyle("Fusion")  # draws scrollbars, menus and dialogs from the palette below
    pal = QPalette()
    for role, key in ((QPalette.Window, "bg"), (QPalette.Base, "card"), (QPalette.AlternateBase, "bg"),
                      (QPalette.Button, "card"), (QPalette.Text, "text"), (QPalette.WindowText, "text"),
                      (QPalette.ButtonText, "text"), (QPalette.PlaceholderText, "muted"),
                      (QPalette.Highlight, "accent"), (QPalette.ToolTipBase, "card"), (QPalette.ToolTipText, "text")):
        pal.setColor(role, QColor(t[key]))
    pal.setColor(QPalette.HighlightedText, QColor("#ffffff"))
    app.setPalette(pal)
    font = app.font()
    font.setPointSize(pt)
    app.setFont(font)
    app.setStyleSheet(f"""
        QMainWindow, QDialog {{ background: {t['bg']}; }}
        QWidget {{ color: {t['text']}; font-size: {pt}pt; }}
        QLabel {{ background: transparent; }}
        QLabel#muted {{ color: {t['muted']}; }}
        QLabel#error {{ color: {t['bad']}; }}
        QLabel#title {{ font-size: {pt + 8}pt; font-weight: 600; }}
        QLabel#value {{ font-size: {pt + 10}pt; font-weight: 700; }}
        #card, #sidebar {{ background: {t['card']}; border: 1px solid {t['border']}; border-radius: 14px; }}
        QPushButton {{ background: {t['card']}; border: 1px solid {t['border']}; border-radius: 8px;
                       padding: {pad}px {2 * pad + 4}px; }}
        QPushButton:hover {{ border-color: {t['accent']}; }}
        QPushButton:disabled {{ color: {t['muted']}; }}
        QPushButton#primary {{ background: {t['accent']}; color: #ffffff; border: none; }}
        QPushButton#nav {{ text-align: left; border: none; background: transparent; padding: {2 * pad}px {3 * pad}px; }}
        QPushButton#nav:hover {{ background: {t['bg']}; }}
        QPushButton#nav:checked {{ background: {t['accent']}; color: #ffffff; }}
        QPushButton#nav:disabled {{ color: {t['muted']}; background: transparent; }}
        QTableWidget, QListWidget, QPlainTextEdit, QScrollArea {{ background: {t['card']};
            border: 1px solid {t['border']}; border-radius: 10px; gridline-color: {t['border']}; }}
        QTableWidget::item, QListWidget::item {{ padding: {pad // 2}px {pad}px; }}
        QTableWidget::item:selected, QListWidget::item:selected {{ background: {t['accent']}; color: #ffffff; }}
        QHeaderView::section {{ background: {t['card']}; color: {t['muted']}; border: none;
            border-bottom: 1px solid {t['border']}; padding: {pad}px; font-weight: 600; }}
        QTableCornerButton::section {{ background: {t['card']}; border: none; }}
        QDoubleSpinBox, QComboBox {{ background: {t['card']}; border: 1px solid {t['border']}; border-radius: 6px;
            padding: {pad // 2}px {pad}px; }}
        QSplitter::handle {{ background: transparent; }}
        QCheckBox {{ background: transparent; }}
    """)


class SettingsPage(QWidget):
    changed = Signal(Prefs)

    def __init__(self, prefs: Prefs):
        super().__init__()
        self.prefs = prefs
        self.theme = self._combo(THEMES, prefs.theme, "theme")
        self.font = self._combo(FONT_PT, prefs.font, "font")
        self.density = self._combo(PAD_PX, prefs.density, "density")
        swatches = QHBoxLayout()
        self.swatches = []
        for name, colour in ACCENTS.items():
            b = QPushButton(toolTip=name, checkable=True, checked=colour == prefs.accent)
            b.setFixedSize(32, 32)
            b.setStyleSheet(f"QPushButton {{ background: {colour}; border-radius: 16px; border: 2px solid transparent; }}"
                            f"QPushButton:checked {{ border-color: palette(text); }}")
            b.clicked.connect(lambda _=False, c=colour: self._set(accent=c))
            self.swatches.append((colour, b))
            swatches.addWidget(b)
        custom = QPushButton("Other colour…")
        custom.clicked.connect(self.pick_colour)
        swatches.addWidget(custom)
        swatches.addStretch()

        card = QWidget(objectName="card")
        form = QFormLayout(card)
        form.setContentsMargins(20, 20, 20, 20)
        form.setVerticalSpacing(14)
        form.setFieldGrowthPolicy(QFormLayout.FieldsStayAtSizeHint)
        card.setMaximumWidth(720)
        form.addRow("Theme", self.theme)
        form.addRow("Accent colour", swatches)
        form.addRow("Text size", self.font)
        form.addRow("Density", self.density)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Settings", objectName="title"))
        layout.addWidget(QLabel("Changes apply at once and are kept for next time.", objectName="muted"))
        layout.addWidget(card)
        layout.addStretch()

    def _combo(self, items, current: str, field: str) -> QComboBox:
        box = QComboBox(minimumWidth=180)
        box.addItems(list(items))
        box.setCurrentText(current)
        box.currentTextChanged.connect(lambda v: self._set(**{field: v}))
        return box

    def pick_colour(self):
        colour = QColorDialog.getColor(QColor(self.prefs.accent), self, "Accent colour")
        if colour.isValid():
            self._set(accent=colour.name())

    def _set(self, **change):
        self.prefs = Prefs(**{**asdict(self.prefs), **change})
        for colour, b in self.swatches:
            b.setChecked(colour == self.prefs.accent)
        save_prefs(self.prefs)
        self.changed.emit(self.prefs)
