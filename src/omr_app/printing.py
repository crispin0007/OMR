"""Print a sheet New exam or Templates made, or save it as a PDF, on any paper; with sheet numbers when it has them."""

import io
from pathlib import Path

import pypdfium2 as pdfium
from PySide6.QtCore import QMarginsF, QRect, QSizeF, QStandardPaths, Qt, Signal
from PySide6.QtGui import QImage, QPageLayout, QPageSize, QPainter
from PySide6.QtPrintSupport import QPrintDialog, QPrinter
from PySide6.QtWidgets import (QApplication, QComboBox, QFileDialog, QHBoxLayout, QLabel, QLineEdit, QMessageBox,
                               QProgressDialog, QPushButton, QSpinBox, QWidget)

from omr_core.sheet import MAX_SHEETS, PAPERS, sheet_numbers, write_pdf

PRINT_DPI = 300


class PrintBar(QWidget):
    """Paper, sheet numbers (for a sheet that prints them) and the Print and Save as PDF buttons."""

    changed = Signal()  # the paper or the first sheet number, for previews to follow

    def __init__(self):
        super().__init__()
        self.template: dict | None = None
        self.name = ""
        self.paper = QComboBox()
        self.paper.addItems(list(PAPERS))
        self.paper.setToolTip("The sheet is scaled to fit the paper; it reads the same on any of them")
        self.paper.currentTextChanged.connect(self.changed)
        self.prefix = QLineEdit(maxLength=6, placeholderText="none")
        self.prefix.setToolTip("Letters before every sheet number, e.g. A- for A-0001; up to 6 letters, digits, - or /")
        self.first = QSpinBox(minimum=0, maximum=999_999, value=1)
        self.prefix.textChanged.connect(self.changed)
        self.first.valueChanged.connect(self.changed)
        self.copies = QSpinBox(minimum=1, maximum=MAX_SHEETS, value=1)
        self.copies.setToolTip("One page per sheet, each with the next number")
        self.numbering = QWidget()
        numbering = QHBoxLayout(self.numbering)
        numbering.setContentsMargins(0, 0, 0, 0)
        for text, w in (("Sheet numbers: prefix", self.prefix), ("from", self.first), ("Copies", self.copies)):
            w.setFixedWidth(90 if w is not self.prefix else 70)
            numbering.addWidget(QLabel(text))
            numbering.addWidget(w)
        self.print_button = QPushButton("Print…", objectName="primary")
        self.print_button.clicked.connect(self.print_sheets)
        self.save = QPushButton("Save as PDF…")
        self.save.clicked.connect(self.save_pdf)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.addStretch()
        row.addWidget(self.numbering)
        row.addWidget(QLabel("Paper"))
        row.addWidget(self.paper)
        row.addWidget(self.print_button)
        row.addWidget(self.save)
        self.set_template(None, "")

    def set_template(self, template: dict | None, name: str):
        self.template, self.name = template, name
        for w in (self.paper, self.print_button, self.save):
            w.setEnabled(template is not None)
        self.numbering.setVisible(bool(template and "serial_mm" in template))

    def numbers(self) -> list[str]:
        """The sheet numbers to print, none for a sheet without them; ValueError says what to change."""
        if "serial_mm" not in self.template:
            return []
        return sheet_numbers(self.prefix.text().strip(), self.first.value(), self.copies.value())

    def first_number(self) -> str:
        """The first sheet's number, for the preview; "" when there is none or it can't be made."""
        try:
            return next(iter(self.numbers()), "")
        except ValueError:
            return ""

    def _numbers_or_say(self) -> list[str] | None:
        try:
            return self.numbers()
        except ValueError as e:
            QMessageBox.warning(self, "Sheet numbers", f"Can't number the sheets: {e}.")
            return None

    def save_pdf(self):
        numbers = self._numbers_or_say()
        if numbers is None:
            return
        docs = Path(QStandardPaths.writableLocation(QStandardPaths.DocumentsLocation))
        safe = "".join(ch if ch.isalnum() or ch in " -_" else "_" for ch in self.name).strip() or "answer"
        path, _ = QFileDialog.getSaveFileName(self, "Save sheet PDF", str(docs / f"{safe} sheet.pdf"), "PDF (*.pdf)")
        if not path:
            return
        try:
            write_pdf(self.template, path, self.paper.currentText(), numbers)
        except OSError as e:  # e.g. the PDF is open in a viewer
            QMessageBox.warning(self, "Couldn't save", f"{path}\n\n{e}")
            return
        self.window().statusBar().showMessage(f"Saved {path}", 5000)

    def print_sheets(self):
        numbers = self._numbers_or_say()
        if numbers is None:
            return
        printer = QPrinter(QPrinter.HighResolution)
        printer.setDocName(f"{self.name} sheet")
        w, h = PAPERS[self.paper.currentText()]
        printer.setPageLayout(QPageLayout(QPageSize(QSizeF(w, h), QPageSize.Millimeter), QPageLayout.Portrait,
                                          QMarginsF()))
        if QPrintDialog(printer, self).exec():
            self.paint(printer, numbers)

    def paint(self, printer: QPrinter, numbers: list[str]):
        """Draw the sheets on the printer, one page each, from the same PDF Save as PDF writes."""
        buf = io.BytesIO()
        write_pdf(self.template, buf, self.paper.currentText(), numbers)
        pdf = pdfium.PdfDocument(buf.getvalue())
        progress = QProgressDialog("Sending the sheets to the printer…", "Stop", 0, len(pdf), self)
        progress.setWindowModality(Qt.WindowModal)
        painter = QPainter()
        try:
            if not painter.begin(printer):
                QMessageBox.warning(self, "Couldn't print", "The printer couldn't be started; check that it is on.")
                return
            for k in range(len(pdf)):
                if progress.wasCanceled():
                    break
                if k:
                    printer.newPage()
                page = pdf[k].render(scale=PRINT_DPI / 72).to_numpy()
                image = QImage(page.data, page.shape[1], page.shape[0], page.strides[0], QImage.Format_BGR888)
                area = painter.viewport()
                fitted = image.size().scaled(area.size(), Qt.KeepAspectRatio)  # the paper's margins may shrink it
                painter.drawImage(QRect(area.x() + (area.width() - fitted.width()) // 2,
                                        area.y() + (area.height() - fitted.height()) // 2, fitted.width(),
                                        fitted.height()), image)
                progress.setValue(k + 1)
                QApplication.processEvents()
        finally:
            if painter.isActive():
                painter.end()
            pdf.close()
            progress.close()
