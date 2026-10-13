"""Getting started steps, shown on an empty Exams page and in Help (F1), with the shortcuts."""

from importlib.metadata import PackageNotFoundError, version

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QScrollArea, QVBoxLayout

STEPS = [
    ("Create the exam", "<b>New exam…</b> on Exams asks for the details, sections, questions and marks, and makes "
                        "the answer sheet. Already print your own sheet? Map it once in <b>Map printed sheet</b>."),
    ("Print the sheet", "<b>Print sheet</b> prints it or saves a PDF for any paper size. <b>Check a printed "
                        "copy…</b> tells you it reads before you print them all."),
    ("Scan the filled sheets", "<b>Start scanning</b> reads them as the scanner feeds them, or from the folder your "
                               "scanner saves into. <b>Import scans…</b> reads PDFs, images and phone photos."),
    ("Give the answer key", "<b>Answer key</b>: click or type each answer, or import a CSV."),
    ("Check and send results", "<b>Review</b> shows only what needs a person: unclear marks and unreadable pages. "
                               "<b>Results</b> exports Excel, CSV and PDF scorecards."),
]

SHORTCUTS = [("Ctrl+N", "New exam"), ("Ctrl+O", "Import scans into the open exam"), ("F1", "This help")]


def steps_html() -> str:
    return "".join(f"<p><b>{n}.&nbsp; {title}</b><br>{text}</p>" for n, (title, text) in enumerate(STEPS, 1))


def app_version() -> str:
    try:
        return version("omr")
    except PackageNotFoundError:  # run from a source checkout without installing
        return "development"


class HelpDialog(QDialog):
    def __init__(self, parent, data_folder: str):
        super().__init__(parent)
        self.setWindowTitle("Help")
        self.resize(620, 660)
        keys = "".join(f"<tr><td><b>{k}</b>&nbsp;&nbsp;&nbsp;</td><td>{what}</td></tr>" for k, what in SHORTCUTS)
        text = QLabel(f"<h3>Getting started</h3>{steps_html()}<h3>Shortcuts</h3><table>{keys}</table>"
                      f"<h3>Your data</h3><p>Exams, scans and corrections are saved as you work in {data_folder}. "
                      "<b>Back up…</b> on Exams copies them into one file for safe keeping or another PC.</p>"
                      f"<p>OMR Checker {app_version()}. Free and open source under the Apache 2.0 licence; works "
                      "fully offline.</p>", wordWrap=True, textFormat=Qt.RichText)
        text.setTextInteractionFlags(Qt.TextSelectableByMouse)
        text.setAlignment(Qt.AlignTop)
        text.setContentsMargins(8, 0, 8, 8)
        scroll = QScrollArea(widgetResizable=True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setWidget(text)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(scroll, 1)
        layout.addWidget(buttons)
