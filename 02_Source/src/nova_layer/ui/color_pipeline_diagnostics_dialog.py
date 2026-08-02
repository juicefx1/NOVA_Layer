"""Read-only Color Pipeline Diagnostics dialog (Phase 9B-2)."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from nova_layer.app.color_pipeline_diagnostics import (
    CacheDiagnostics,
    ColorPipelineDiagnostics,
    format_color_pipeline_diagnostics,
    format_hit_rate,
    format_mib,
)
from nova_layer.app.project_controller import ProjectController


def _text(value: object | None, *, empty: str = "None") -> str:
    if value is None:
        return empty
    text = str(value).strip()
    return text if text else empty


def _selectable(label: QLabel) -> QLabel:
    label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    label.setWordWrap(True)
    return label


class ColorPipelineDiagnosticsDialog(QDialog):
    """Workspace View → Color Pipeline Diagnostics… (read-only snapshot UI)."""

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
        self.resize(640, 720)

        root = QVBoxLayout(self)
        self.tabs = QTabWidget()
        self.tabs.setObjectName("colorPipelineDiagnosticsTabs")

        self.tabs.addTab(self._build_general_tab(), "General")
        self.tabs.addTab(self._build_caches_tab(), "Caches")
        self.tabs.addTab(self._build_warnings_tab(), "Warnings")
        root.addWidget(self.tabs)

        footer = QHBoxLayout()
        self.refresh_button = QPushButton("Refresh")
        self.refresh_button.setObjectName("colorPipelineDiagnosticsRefresh")
        self.refresh_button.clicked.connect(self.refresh)
        footer.addWidget(self.refresh_button)

        self.copy_button = QPushButton("Copy Report")
        self.copy_button.setObjectName("colorPipelineDiagnosticsCopy")
        self.copy_button.clicked.connect(self.copy_to_clipboard)
        footer.addWidget(self.copy_button)

        self.status_label = QLabel("")
        self.status_label.setObjectName("colorPipelineDiagnosticsStatus")
        footer.addWidget(self.status_label)
        footer.addStretch()

        close_button = QPushButton("Close")
        close_button.setObjectName("colorPipelineDiagnosticsClose")
        close_button.clicked.connect(self.accept)
        footer.addWidget(close_button)
        root.addLayout(footer)

        self._last_snapshot: ColorPipelineDiagnostics | None = None
        self.refresh()

    def _scroll_form(self, groups: list[QGroupBox]) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        body = QWidget()
        layout = QVBoxLayout(body)
        for group in groups:
            layout.addWidget(group)
        layout.addStretch()
        scroll.setWidget(body)
        wrapper = QWidget()
        wrap_layout = QVBoxLayout(wrapper)
        wrap_layout.setContentsMargins(0, 0, 0, 0)
        wrap_layout.addWidget(scroll)
        return wrapper

    def _build_general_tab(self) -> QWidget:
        media_form = QFormLayout()
        media_box = QGroupBox("Media")
        media_box.setLayout(media_form)
        self.project_label = self._add_row(media_form, "Project")
        self.shot_label = self._add_row(media_form, "Shot")
        self.media_label = self._add_row(media_form, "Media Path")
        self.frame_label = self._add_row(media_form, "Active Frame")

        transform_form = QFormLayout()
        transform_box = QGroupBox("Transform")
        transform_box.setLayout(transform_form)
        self.backend_label = self._add_row(transform_form, "Backend")
        self.identity_label = self._add_row(transform_form, "Transform Identity")
        self.input_label = self._add_row(transform_form, "Input Color Space")
        self.display_label = self._add_row(transform_form, "Display")
        self.view_label = self._add_row(transform_form, "View")
        self.exposure_label = self._add_row(transform_form, "Exposure")
        self.fallback_label = self._add_row(transform_form, "Fallback Reason")

        policy_form = QFormLayout()
        policy_box = QGroupBox("Policies")
        policy_box.setLayout(policy_form)
        self.viewer_policy_label = self._add_row(policy_form, "Viewer")
        self.processing_policy_label = self._add_row(policy_form, "Processing")
        self.render_policy_label = self._add_row(policy_form, "Render Default")
        self.source_version_label = self._add_row(
            policy_form, "Source Transform Version"
        )
        self.last_render_policy_label = self._add_row(
            policy_form, "Last Render Color Policy"
        )

        provenance_form = QFormLayout()
        provenance_box = QGroupBox("Provenance")
        provenance_box.setLayout(provenance_form)
        self.prov_backend_label = self._add_row(provenance_form, "Backend source")
        self.prov_config_label = self._add_row(provenance_form, "Config source")
        self.prov_input_label = self._add_row(
            provenance_form, "Input color space source"
        )
        self.prov_display_label = self._add_row(provenance_form, "Display source")
        self.prov_view_label = self._add_row(provenance_form, "View source")
        self.prov_exposure_label = self._add_row(provenance_form, "Exposure source")

        counters_form = QFormLayout()
        counters_box = QGroupBox("Pipeline Counters")
        counters_box.setLayout(counters_form)
        self.raw_decodes_label = self._add_row(counters_form, "Raw Decodes")
        self.preview_gens_label = self._add_row(counters_form, "Preview Generations")
        self.raw_prefetch_label = self._add_row(counters_form, "Raw Prefetch Skips")
        self.preview_prefetch_label = self._add_row(
            counters_form, "Preview Prefetch Skips"
        )

        return self._scroll_form(
            [media_box, transform_box, policy_box, provenance_box, counters_box]
        )

    def _build_caches_tab(self) -> QWidget:
        self.raw_cache_labels = self._build_cache_group("Raw Cache")
        self.preview_cache_labels = self._build_cache_group("Preview Cache")
        self.source_cache_labels = self._build_cache_group("Source Cache")
        # Backward-compatible summary labels used by older tests.
        self.raw_cache_label = self.raw_cache_labels["summary"]
        self.preview_cache_label = self.preview_cache_labels["summary"]
        self.source_cache_label = self.source_cache_labels["summary"]
        return self._scroll_form(
            [
                self.raw_cache_labels["box"],
                self.preview_cache_labels["box"],
                self.source_cache_labels["box"],
            ]
        )

    def _build_cache_group(self, title: str) -> dict[str, object]:
        form = QFormLayout()
        box = QGroupBox(title)
        box.setLayout(form)
        labels = {
            "box": box,
            "entries": self._add_row(form, "Entry Count / Max Entries"),
            "bytes": self._add_row(form, "Current MiB / Max MiB"),
            "hits": self._add_row(form, "Hits"),
            "misses": self._add_row(form, "Misses"),
            "hit_rate": self._add_row(form, "Hit Rate"),
            "evictions": self._add_row(form, "Evictions"),
            "oversized_admissions": self._add_row(form, "Oversized Admissions"),
            "oversized_rejections": self._add_row(form, "Oversized Rejections"),
            "summary": self._add_row(form, "Summary"),
        }
        return labels

    def _build_warnings_tab(self) -> QWidget:
        form = QFormLayout()
        box = QGroupBox("Warnings")
        box.setLayout(form)
        self.resolve_warnings_label = self._add_row(form, "Resolve warnings")
        self.warnings_label = self._add_row(form, "All warnings")
        self.fallback_warnings_label = self._add_row(form, "Fallback Reason")
        return self._scroll_form([box])

    @staticmethod
    def _add_row(form: QFormLayout, title: str) -> QLabel:
        label = _selectable(QLabel("None"))
        safe = "".join(ch for ch in title if ch.isalnum())
        label.setObjectName(f"diag{safe}")
        form.addRow(title, label)
        return label

    def refresh(self) -> None:
        """Reload controller snapshot without decoding or mutating caches."""
        snapshot = self.controller.color_pipeline_diagnostics
        self._last_snapshot = snapshot
        self._apply_snapshot(snapshot)
        self.status_label.setText("")

    def _apply_snapshot(self, snap: ColorPipelineDiagnostics) -> None:
        project_name = None
        try:
            project = self.controller.project
            if project is not None:
                project_name = getattr(project, "name", None)
        except Exception:
            project_name = None

        self.project_label.setText(_text(project_name))
        self.shot_label.setText(_text(snap.shot_name))
        self.media_label.setText(_text(snap.media_path))
        self.frame_label.setText(_text(snap.active_frame))

        self.backend_label.setText(_text(snap.active_backend))
        # Prefer display-safe identity in the UI.
        self.identity_label.setText(_text(snap.transform_identity_display))
        self.input_label.setText(_text(snap.input_color_space))
        self.display_label.setText(_text(snap.display))
        self.view_label.setText(_text(snap.view))
        self.exposure_label.setText(f"{snap.exposure:g}")
        self.fallback_label.setText(_text(snap.fallback_reason))

        self.viewer_policy_label.setText("PREVIEW")
        self.processing_policy_label.setText(
            _text(snap.processing_default_policy).upper()
        )
        self.render_policy_label.setText(_text(snap.render_default_policy).upper())
        self.source_version_label.setText(_text(snap.source_transform_version))
        self.last_render_policy_label.setText(_text(snap.last_render_color_policy))

        provenance = snap.provenance
        self.prov_backend_label.setText(_text(provenance.backend))
        self.prov_config_label.setText(_text(provenance.config))
        self.prov_input_label.setText(_text(provenance.input_color_space))
        self.prov_display_label.setText(_text(provenance.display))
        self.prov_view_label.setText(_text(provenance.view))
        self.prov_exposure_label.setText(_text(provenance.exposure))

        self.raw_decodes_label.setText(str(snap.raw_decode_count))
        self.preview_gens_label.setText(str(snap.preview_generation_count))
        self.raw_prefetch_label.setText(str(snap.pipeline.raw_prefetch_skips))
        self.preview_prefetch_label.setText(str(snap.pipeline.preview_prefetch_skips))

        self._apply_cache(self.raw_cache_labels, snap.raw_cache_diag)
        self._apply_cache(self.preview_cache_labels, snap.preview_cache_diag)
        self._apply_cache(self.source_cache_labels, snap.source_cache_diag)

        resolve = snap.resolve_warnings
        self.resolve_warnings_label.setText(
            "\n".join(resolve) if resolve else "None"
        )
        self.warnings_label.setText(
            "\n".join(snap.warnings) if snap.warnings else "None"
        )
        self.fallback_warnings_label.setText(_text(snap.fallback_reason))

    @staticmethod
    def _apply_cache(labels: dict[str, object], diag: CacheDiagnostics) -> None:
        max_entries = "—" if diag.max_entries is None else str(diag.max_entries)
        labels["entries"].setText(f"{diag.count} / {max_entries}")  # type: ignore[union-attr]
        labels["bytes"].setText(
            f"{format_mib(diag.current_mib)} / {format_mib(diag.max_mib)} MiB"
        )  # type: ignore[union-attr]
        labels["hits"].setText(str(diag.hits))  # type: ignore[union-attr]
        labels["misses"].setText(str(diag.misses))  # type: ignore[union-attr]
        labels["hit_rate"].setText(format_hit_rate(diag.hit_rate))  # type: ignore[union-attr]
        labels["evictions"].setText(str(diag.evictions))  # type: ignore[union-attr]
        labels["oversized_admissions"].setText(str(diag.oversized_admissions))  # type: ignore[union-attr]
        labels["oversized_rejections"].setText(str(diag.oversized_rejections))  # type: ignore[union-attr]
        labels["summary"].setText(
            f"{diag.count} entries · "
            f"{format_mib(diag.current_mib)} / {format_mib(diag.max_mib)} MiB · "
            f"hit {format_hit_rate(diag.hit_rate)} · "
            f"evictions {diag.evictions}"
        )  # type: ignore[union-attr]

    def copy_text(self) -> str:
        snapshot = self._last_snapshot or self.controller.color_pipeline_diagnostics
        return format_color_pipeline_diagnostics(snapshot, display_safe=True)

    def copy_to_clipboard(self) -> None:
        QGuiApplication.clipboard().setText(self.copy_text())
        self.status_label.setText("Report copied to clipboard")
