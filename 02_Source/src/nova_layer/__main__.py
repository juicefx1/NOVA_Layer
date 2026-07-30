from __future__ import annotations

import os
import sys

from PySide6.QtWidgets import QApplication

from nova_layer.ui.main_window import MainWindow


def main() -> int:
    os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")
    app = QApplication(sys.argv)
    app.setApplicationName("NOVA Layer")
    app.setOrganizationName("Supernova Studios")
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
