from __future__ import annotations

import json
import os
import shutil
from collections.abc import Mapping, Sequence
from copy import deepcopy
from pathlib import Path
from threading import Lock
from typing import Any
from uuid import uuid4

ENV_WORKSPACE_PATH = "NOVA_WORKSPACE_PATH"
DEFAULT_WORKSPACE_FILENAME = "workspace.json"
MAX_BATCH_HISTORY = 20
MAX_RECENT_PROJECTS = 20
WORKSPACE_VERSION = 1

_EMPTY_STATE: dict[str, Any] = {
    "version": WORKSPACE_VERSION,
    "recent_projects": [],
    "open_projects": [],
    "active_project": None,
    "selected_tool": None,
    "selected_provider_id": None,
    "selected_extraction_provider_id": None,
    "selected_host_adapter_id": None,
    "selected_plugin_id": None,
    "plugin_configurations": {},
    "plugin_install_root": None,
    "installed_plugins": [],
    "window_geometry": None,
    "dock_layout": None,
    "sidebar_visible": True,
    "recent_export_directory": None,
    "preferences": {},
    "session_metadata": {},
    "recent_batch_history": [],
    "batch_queue_metadata": None,
}


class WorkspaceManager:
    """Application-lifetime Workspace service (Product Feature 10).

    Persists application environment state only — never Project schema payloads,
    runtime caches, ONNX/neural sessions, or OperationExecutor state.

    Feature 11 batch history/queue metadata are stored in the same workspace.json
    document as additive fields (no second workspace architecture).
    """

    _shared: WorkspaceManager | None = None
    _shared_lock = Lock()

    def __init__(self, path: Path | str | None = None) -> None:
        self._path = Path(path) if path is not None else default_workspace_path()
        self._data: dict[str, Any] = deepcopy(_EMPTY_STATE)
        self._loaded = False
        self._load_error: str | None = None

    @classmethod
    def shared(cls, path: Path | str | None = None) -> WorkspaceManager:
        """Return the process-wide WorkspaceManager (created and loaded once)."""
        with cls._shared_lock:
            if cls._shared is None:
                cls._shared = cls(path)
                cls._shared.load()
            return cls._shared

    @classmethod
    def reset_shared_for_tests(cls) -> None:
        """Drop the process singleton (tests only)."""
        with cls._shared_lock:
            cls._shared = None

    @property
    def path(self) -> Path:
        return self._path

    @property
    def load_error(self) -> str | None:
        return self._load_error

    def clear_load_error(self) -> None:
        """Acknowledge a recovered workspace load failure (UI recovery dialog)."""
        self._load_error = None

    def load(self) -> dict[str, Any]:
        self._load_error = None
        if self._path.is_file():
            try:
                raw = json.loads(self._path.read_text(encoding="utf-8"))
                if not isinstance(raw, dict):
                    raise ValueError("workspace root must be a JSON object")
                self._data = deepcopy(_EMPTY_STATE)
                self._data.update(raw)
                self._data["version"] = WORKSPACE_VERSION
            except (OSError, json.JSONDecodeError, ValueError) as exc:
                # Corrupt workspace must never affect Projects: start fresh.
                self._load_error = str(exc)
                self._data = deepcopy(_EMPTY_STATE)
        else:
            self._data = deepcopy(_EMPTY_STATE)
        self._loaded = True
        return dict(self._data)

    def save(self) -> Path:
        """Atomically persist workspace.json (temp + fsync + replace).

        Matches Project persistence guarantees: a crash mid-save must never
        destroy the previous valid workspace document. A `.bak` copy of the
        previous file is refreshed before replace when one already exists.
        """
        if not self._loaded:
            self.load()
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = dict(self._data)
        payload["version"] = WORKSPACE_VERSION
        text = json.dumps(payload, indent=2, sort_keys=True) + "\n"
        temporary = self._path.with_name(f".{self._path.name}.{uuid4().hex}.tmp")
        backup = self._path.with_name(f"{self._path.name}.bak")
        try:
            with temporary.open("w", encoding="utf-8") as handle:
                handle.write(text)
                handle.flush()
                try:
                    os.fsync(handle.fileno())
                except OSError:
                    # Some filesystems (or platforms) may not support fsync.
                    pass
            if self._path.is_file():
                try:
                    shutil.copy2(self._path, backup)
                except OSError:
                    # Backup is best-effort; atomic replace remains the primary guarantee.
                    pass
            os.replace(temporary, self._path)
        except Exception:
            if temporary.exists():
                temporary.unlink(missing_ok=True)
            raise
        return self._path

    def reset_workspace(self) -> None:
        """Clear workspace state and persist an empty document. Projects untouched."""
        self._data = deepcopy(_EMPTY_STATE)
        self._loaded = True
        self._load_error = None
        self.save()

    # --- Feature 11 batch fields (preserved public API) ---

    def record_batch_history(self, entry: Mapping[str, Any]) -> None:
        self._ensure_loaded()
        history = list(self._data.get("recent_batch_history") or [])
        history.insert(0, dict(entry))
        self._data["recent_batch_history"] = history[:MAX_BATCH_HISTORY]
        self.save()

    def recent_batch_history(self) -> list[dict[str, Any]]:
        self._ensure_loaded()
        raw = self._data.get("recent_batch_history") or []
        return [dict(item) for item in raw if isinstance(item, dict)]

    def save_batch_queue_metadata(self, metadata: Mapping[str, Any] | None) -> None:
        self._ensure_loaded()
        self._data["batch_queue_metadata"] = None if metadata is None else dict(metadata)
        self.save()

    def restore_batch_queue_metadata(self) -> dict[str, Any] | None:
        self._ensure_loaded()
        raw = self._data.get("batch_queue_metadata")
        return None if not isinstance(raw, dict) else dict(raw)

    # --- Feature 10 project / session ---

    def record_recent_project(self, package_path: str | Path) -> None:
        self._ensure_loaded()
        path = str(Path(package_path))
        recent = [item for item in self.recent_projects() if item != path]
        recent.insert(0, path)
        self._data["recent_projects"] = recent[:MAX_RECENT_PROJECTS]
        self.save()

    def recent_projects(self) -> list[str]:
        self._ensure_loaded()
        raw = self._data.get("recent_projects") or []
        return [str(item) for item in raw if item]

    def set_open_projects(self, paths: Sequence[str | Path]) -> None:
        self._ensure_loaded()
        self._data["open_projects"] = [str(Path(item)) for item in paths]
        self.save()

    def open_projects(self) -> list[str]:
        self._ensure_loaded()
        raw = self._data.get("open_projects") or []
        return [str(item) for item in raw if item]

    def set_active_project(self, package_path: str | Path | None) -> None:
        self._ensure_loaded()
        self._data["active_project"] = None if package_path is None else str(Path(package_path))
        if package_path is not None:
            self.record_recent_project(package_path)
        else:
            self.save()

    def active_project(self) -> str | None:
        self._ensure_loaded()
        raw = self._data.get("active_project")
        return None if raw is None else str(raw)

    def remove_project_reference(self, package_path: str | Path) -> None:
        """Drop workspace references to a project path. Does not delete the project file."""
        self._ensure_loaded()
        path = str(Path(package_path))
        self._data["recent_projects"] = [item for item in self.recent_projects() if item != path]
        self._data["open_projects"] = [item for item in self.open_projects() if item != path]
        if self.active_project() == path:
            self._data["active_project"] = None
        self.save()

    # --- Provider / plugin / tool selection ---

    def set_selected_tool(self, tool: str | None) -> None:
        self._ensure_loaded()
        self._data["selected_tool"] = tool
        self.save()

    def selected_tool(self) -> str | None:
        self._ensure_loaded()
        raw = self._data.get("selected_tool")
        return None if raw is None else str(raw)

    def set_selected_provider_id(self, provider_id: str | None) -> None:
        self._ensure_loaded()
        self._data["selected_provider_id"] = provider_id
        self.save()

    def selected_provider_id(self) -> str | None:
        self._ensure_loaded()
        raw = self._data.get("selected_provider_id")
        return None if raw is None else str(raw)

    def set_selected_extraction_provider_id(self, provider_id: str | None) -> None:
        self._ensure_loaded()
        self._data["selected_extraction_provider_id"] = provider_id
        self.save()

    def selected_extraction_provider_id(self) -> str | None:
        self._ensure_loaded()
        raw = self._data.get("selected_extraction_provider_id")
        return None if raw is None else str(raw)

    def set_selected_host_adapter_id(self, adapter_id: str | None) -> None:
        self._ensure_loaded()
        self._data["selected_host_adapter_id"] = adapter_id
        self.save()

    def selected_host_adapter_id(self) -> str | None:
        self._ensure_loaded()
        raw = self._data.get("selected_host_adapter_id")
        return None if raw is None else str(raw)

    def set_selected_plugin_id(self, plugin_id: str | None) -> None:
        self._ensure_loaded()
        self._data["selected_plugin_id"] = plugin_id
        self.save()

    def selected_plugin_id(self) -> str | None:
        self._ensure_loaded()
        raw = self._data.get("selected_plugin_id")
        return None if raw is None else str(raw)

    def set_plugin_configuration(self, plugin_id: str, configuration: Mapping[str, Any]) -> None:
        self._ensure_loaded()
        configs = dict(self._data.get("plugin_configurations") or {})
        configs[plugin_id] = dict(configuration)
        self._data["plugin_configurations"] = configs
        self.save()

    def plugin_configurations(self) -> dict[str, dict[str, Any]]:
        self._ensure_loaded()
        raw = self._data.get("plugin_configurations") or {}
        return {
            str(key): dict(value)
            for key, value in raw.items()
            if isinstance(value, dict)
        }

    def get_plugin_configuration(self, plugin_id: str) -> dict[str, Any]:
        return dict(self.plugin_configurations().get(plugin_id, {}))

    def replace_plugin_configurations(
        self,
        configurations: Mapping[str, Mapping[str, Any]],
    ) -> None:
        """Replace the full plugin configuration map (Feature 12 uninstall cleanup)."""
        self._ensure_loaded()
        self._data["plugin_configurations"] = {
            str(key): dict(value) for key, value in configurations.items()
        }
        self.save()

    # --- Feature 12 installed plugin packages ---

    def set_plugin_install_root(self, directory: str | Path | None) -> None:
        self._ensure_loaded()
        self._data["plugin_install_root"] = (
            None if directory is None else str(Path(directory))
        )
        self.save()

    def plugin_install_root(self) -> str | None:
        self._ensure_loaded()
        raw = self._data.get("plugin_install_root")
        return None if raw is None else str(raw)

    def installed_plugins(self) -> list[dict[str, Any]]:
        self._ensure_loaded()
        raw = self._data.get("installed_plugins") or []
        return [dict(item) for item in raw if isinstance(item, dict)]

    def record_installed_plugin(self, entry: Mapping[str, Any]) -> None:
        """Upsert an installed plugin package record by plugin_id."""
        self._ensure_loaded()
        plugin_id = str(entry.get("plugin_id", "")).strip()
        if not plugin_id:
            raise ValueError("installed plugin entry requires plugin_id")
        remaining = [
            item for item in self.installed_plugins() if str(item.get("plugin_id")) != plugin_id
        ]
        remaining.insert(0, dict(entry))
        self._data["installed_plugins"] = remaining
        self.save()

    def remove_installed_plugin(self, plugin_id: str) -> None:
        self._ensure_loaded()
        self._data["installed_plugins"] = [
            item
            for item in self.installed_plugins()
            if str(item.get("plugin_id")) != plugin_id
        ]
        self.save()

    def get_installed_plugin(self, plugin_id: str) -> dict[str, Any] | None:
        for item in self.installed_plugins():
            if str(item.get("plugin_id")) == plugin_id:
                return dict(item)
        return None

    # --- Layout / preferences ---

    def set_window_geometry(self, geometry: Mapping[str, Any] | None) -> None:
        self._ensure_loaded()
        self._data["window_geometry"] = None if geometry is None else dict(geometry)
        self.save()

    def window_geometry(self) -> dict[str, Any] | None:
        self._ensure_loaded()
        raw = self._data.get("window_geometry")
        return None if not isinstance(raw, dict) else dict(raw)

    def set_dock_layout(self, layout: Mapping[str, Any] | None) -> None:
        self._ensure_loaded()
        self._data["dock_layout"] = None if layout is None else dict(layout)
        self.save()

    def dock_layout(self) -> dict[str, Any] | None:
        self._ensure_loaded()
        raw = self._data.get("dock_layout")
        return None if not isinstance(raw, dict) else dict(raw)

    def set_sidebar_visible(self, visible: bool) -> None:
        self._ensure_loaded()
        self._data["sidebar_visible"] = bool(visible)
        self.save()

    def sidebar_visible(self) -> bool:
        self._ensure_loaded()
        return bool(self._data.get("sidebar_visible", True))

    def set_recent_export_directory(self, directory: str | Path | None) -> None:
        self._ensure_loaded()
        self._data["recent_export_directory"] = (
            None if directory is None else str(Path(directory))
        )
        self.save()

    def recent_export_directory(self) -> str | None:
        self._ensure_loaded()
        raw = self._data.get("recent_export_directory")
        return None if raw is None else str(raw)

    def set_preference(self, key: str, value: Any) -> None:
        self._ensure_loaded()
        prefs = dict(self._data.get("preferences") or {})
        prefs[key] = value
        self._data["preferences"] = prefs
        self.save()

    def preferences(self) -> dict[str, Any]:
        self._ensure_loaded()
        raw = self._data.get("preferences") or {}
        return dict(raw) if isinstance(raw, dict) else {}

    def get_preference(self, key: str, default: Any = None) -> Any:
        return self.preferences().get(key, default)

    def set_session_metadata(self, metadata: Mapping[str, Any]) -> None:
        self._ensure_loaded()
        self._data["session_metadata"] = dict(metadata)
        self.save()

    def session_metadata(self) -> dict[str, Any]:
        self._ensure_loaded()
        raw = self._data.get("session_metadata") or {}
        return dict(raw) if isinstance(raw, dict) else {}

    def snapshot(self) -> dict[str, Any]:
        self._ensure_loaded()
        return deepcopy(self._data)

    def _ensure_loaded(self) -> None:
        if not self._loaded:
            self.load()


def default_workspace_path(*, environ: Mapping[str, str] | None = None) -> Path:
    env = environ if environ is not None else os.environ
    configured = str(env.get(ENV_WORKSPACE_PATH, "")).strip()
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".nova_layer" / DEFAULT_WORKSPACE_FILENAME


def queue_metadata_from_paths(
    image_paths: Sequence[str | Path],
    *,
    intent_snapshot: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "items": [{"image_path": str(path), "status": "waiting"} for path in image_paths],
        "intent_snapshot": dict(intent_snapshot or {}),
    }
