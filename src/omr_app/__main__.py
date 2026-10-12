import sys

from PySide6.QtWidgets import QApplication, QLabel, QMainWindow


def main() -> int:
    app = QApplication(sys.argv)
    window = QMainWindow()
    window.setWindowTitle("OMR")
    window.setCentralWidget(QLabel("OMR checking: phase 1 in progress"))
    window.resize(960, 640)
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
