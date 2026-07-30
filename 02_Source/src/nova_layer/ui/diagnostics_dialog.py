from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from nova_layer.app.diagnostics import DiagnosticReport, DiagnosticStatus


class DiagnosticsDialog(QDialog):
    def __init__(self, report: DiagnosticReport) -> None:
        super().__init__()
        self.setWindowTitle("Startup Diagnostics — NOVA Layer")
        self.resize(760, 440)
        root = QVBoxLayout(self)

        summary = QLabel(report.summary)
        summary.setObjectName("diagnosticSummary")
        root.addWidget(summary)

        table = QTableWidget(len(report.checks), 4)
        table.setHorizontalHeaderLabels(["Status", "Component", "Version", "Details"])
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        for row, check in enumerate(report.checks):
            status_text = {
                DiagnosticStatus.PASS: "PASS",
                DiagnosticStatus.WARNING: "WARNING",
                DiagnosticStatus.FAIL: "FAIL",
            }[check.status]
            table.setItem(row, 0, QTableWidgetItem(status_text))
            table.setItem(row, 1, QTableWidgetItem(check.name))
            table.setItem(row, 2, QTableWidgetItem(check.version or "—"))
            table.setItem(row, 3, QTableWidgetItem(check.message))
        table.resizeColumnsToContents()
        table.horizontalHeader().setStretchLastSection(True)
        root.addWidget(table)

        footer = QHBoxLayout()
        footer.addStretch()
        close_button = QPushButton("Close")
        close_button.clicked.connect(self.accept)
        footer.addWidget(close_button)
        root.addLayout(footer)
