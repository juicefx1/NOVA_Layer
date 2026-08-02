"""Read-only Color Pipeline Diagnostics dialog (Phase 9B)."""

from __future__ import annotations

from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from nova_layer.app.color_pipeline_diagnostics import (
    ColorPipelineDiagnostics,
    format_color_pipeline_diagnostics,
    format_hit_rate,
    format_mib,
)
from nova_layer.app.project_controller import ProjectController


def _text(value: object | None) -> str:
    if value is None:
        return "—"
    text = str(value).strip()
    return text if text else "—"


class ColorPipelineDiagnosticsDialog(QDialog):
    def __init__(
        self,
        controller: ProjectController,
        *,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.controller = controller
        self.setObjectName("colorPipelineDiagnosticsDialog")
        self.setWindowTitle("Color Pipeline Diagnostics — NOVA Layer")
        self.resize(560, 640)

        root = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        body = QWidget()
        body_layout = QVBoxLayout(body)

        self._color_form = QFormLayout()
        color_box = QGroupBox("Color")
        color_box.setLayout(self._color_form)
        self.backend_label = self._add_row(self._color_form, "Backend")
        self.input_label = self._add_row(self._color_form, "Input Color Space")
        self.display_label = self._add_row(self._color_form, "Display")
        self.view_label = self._add_row(self._color_form, "View")
        self.exposure_label = self._add_row(self._color_form, "Exposure")
        self.identity_label = self._add_row(self._color_form, "Transform Identity")
        self.fallback_label = self._add_row(self._color_form, "Fallback")
        self.warnings_label = self._add_row(self._color_form, "Resolve warnings")
        self.shot_label = self._add_row(self._color_form, "Shot")
        self.media_label = self._add_row(self._color_form, "Media")
        body_layout.addWidget(color_box)

        self._cache_form = QFormLayout()
        cache_box = QGroupBox("Caches")
        cache_box.setLayout(self._cache_form)
        self.raw_cache_label = self._add_row(self._cache_form, "Raw")
        self.preview_cache_label = self._add_row(self._cache_form, "Preview")
        self.source_cache_label = self._add_row(self._cache_form, "Source")
        body_layout.addWidget(cache_box)

        self._pipeline_form = QFormLayout()
        pipeline_box = QGroupBox("Pipeline")
        pipeline_box.setLayout(self._pipeline_form)
        self.raw_decodes_label = self._add_row(self._pipeline_form, "Raw decodes")
        self.preview_gens_label = self._add_row(self._pipeline_form, "Preview generations")
        self.raw_prefetch_label = self._add_row(self._pipeline_form, "Raw prefetch skips")
        self.preview_prefetch_label = self._add_row(
            self._pipeline_form, "Preview prefetch skips"
        )
        self.last_render_policy_label = self._add_row(
            self._pipeline_form, "Last render color policy"
        )
        body_layout.addWidget(pipeline_box)
        body_layout.addStretch()

        scroll.setWidget(body)
        root.addWidget(scroll)

        footer = QHBoxLayout()
        self.refresh_button = QPushButton("Refresh")
        self.refresh_button.setObjectName("colorPipelineDiagnosticsRefresh")
        self.refresh_button.clicked.connect(self.refresh)
        footer.addWidget(self.refresh_button)
        self.copy_button = QPushButton("Copy")
        self.copy_button.setObjectName("colorPipelineDiagnosticsCopy")
        self.copy_button.clicked.connect(self.copy_to_clipboard)
        footer.addWidget(self.copy_button)
        footer.addStretch()
        close_button = QPushButton("Close")
        close_button.clicked.connect(self.accept)
        footer.addWidget(close_button)
        root.addLayout(footer)

        self._last_snapshot: ColorPipelineDiagnostics | None = None
        self.refresh()

    @staticmethod
    def _add_row(form: QFormLayout, title: str) -> QLabel:
        label = QLabel("—")
        label.setWordWrap(True)
        label.setObjectName(f"diag{title.replace(' ', '')}")
        form.addRow(title, label)
        return label

    def refresh(self) -> None:
        snapshot = self.controller.color_pipeline_diagnostics
        self._last_snapshot = snapshot
        self._apply_snapshot(snapshot)

    def _apply_snapshot(self, snap: ColorPipelineDiagnostics) -> None:
        self.backend_label.setText(_text(snap.active_backend))
        self.input_label.setText(_text(snap.input_color_space))
        self.display_label.setText(_text(snap.display))
        self.view_label.setText(_text(snap.view))
        self.exposure_label.setText(f"{snap.exposure:g}")
        self.identity_label.setText(_text(snap.transform_identity))
        self.fallback_label.setText(_text(snap.fallback_reason))
        if snap.warnings:
            self.warnings_label.setText("\n".join(snap.warnings))
        else:
            self.warnings_label.setText("—")
        self.shot_label.setText(_text(snap.shot_name))
        self.media_label.setText(_text(snap.media_path))

        self.raw_cache_label.setText(self._cache_text(snap, "raw"))
        self.preview_cache_label.setText(self._cache_text(snap, "preview"))
        self.source_cache_label.setText(self._cache_text(snap, "source"))

        self.raw_decodes_label.setText(str(snap.raw_decode_count))
        self.preview_gens_label.setText(str(snap.preview_generation_count))
        self.raw_prefetch_label.setText(str(snap.pipeline.raw_prefetch_skips))
        self.preview_prefetch_label.setText(str(snap.pipeline.preview_prefetch_skips))
        self.last_render_policy_label.setText(_text(snap.last_render_color_policy))

    @staticmethod
    def _cache_text(snap: ColorPipelineDiagnostics, kind: str) -> str:
        if kind == "raw":
            stats, rate, cur, mx = (
                snap.raw_cache,
                snap.raw_hit_rate,
                snap.raw_cache_mib,
                snap.raw_cache_max_mib,
            )
        elif kind == "preview":
            stats, rate, cur, mx = (
                snap.preview_cache,
                snap.preview_hit_rate,
                snap.preview_cache_mib,
                snap.preview_cache_max_mib,
            )
        else:
            stats, rate, cur, mx = (
                snap.source_cache,
                snap.source_hit_rate,
                snap.source_cache_mib,
                snap.source_cache_max_mib,
            )
        return (
            f"{stats.count} entries · "
            f"{format_mib(cur)} / {format_mib(mx)} MiB · "
            f"hit {format_hit_rate(rate)} · "
            f"evictions {stats.evictions}"
        )

    def copy_text(self) -> str:
        snapshot = self._last_snapshot or self.controller.color_pipeline_diagnostics
        return format_color_pipeline_diagnostics(snapshot)

    def copy_to_clipboard(self) -> None:
        QGuiApplication.clipboard().setText(self.copy_text())
