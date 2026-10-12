import sys
from pathlib import Path

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from omr_app.window import MainWindow


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("OMR")
    app.setWindowIcon(QIcon(str(Path(__file__).with_name("icon.png"))))
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
