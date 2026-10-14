import multiprocessing
import sys
from pathlib import Path

from PySide6.QtCore import QSettings
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from omr_app.paths import portable_dir
from omr_app.window import MainWindow


def main() -> int:
    multiprocessing.freeze_support()  # the packaged app starts its page readers by running itself again
    app = QApplication(sys.argv)
    app.setApplicationName("OMR")  # names the data folders; keep it so existing exams are found
    app.setWindowIcon(QIcon(str(Path(__file__).with_name("icon.png"))))
    if portable_dir():  # the portable copy keeps its settings with its exams
        QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, str(portable_dir()))
    window = MainWindow()
    if not window.log_in():
        return 0
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
