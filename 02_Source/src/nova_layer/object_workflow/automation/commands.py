from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Literal

from nova_layer.object_workflow.automation.models import AutomationPermission
from nova_layer.object_workflow.automation.session import AutomationSession

AutomationCommandName = Literal[
    "open_project",
    "load_image",
    "create_artist_intent",
    "generate_candidates",
    "select_candidate",
    "confirm_candidate",
    "generate_extraction",
    "export_layer",
    "save_project",
    "close_project",
    "batch_execute",
]

CommandHandler = Callable[[AutomationSession, Mapping[str, Any]], dict[str, Any]]


@dataclass(frozen=True, slots=True)
class CommandSpec:
    name: str
    permission: AutomationPermission
    description: str
    builtin: bool = True
    plugin_id: str | None = None


BUILTIN_COMMANDS: dict[str, CommandSpec] = {
    "open_project": CommandSpec(
        "open_project",
        "write",
        "Open an existing project package (maps to load_project).",
    ),
    "load_image": CommandSpec(
        "load_image",
        "write",
        "Load a source image into the active project (maps to load_source).",
    ),
    "create_artist_intent": CommandSpec(
        "create_artist_intent",
        "write",
        "Create ArtistIntent (maps to create_artist_intent).",
    ),
    "generate_candidates": CommandSpec(
        "generate_candidates",
        "execute",
        "Generate hypothesis candidates via OperationExecutor.",
    ),
    "select_candidate": CommandSpec(
        "select_candidate",
        "write",
        "Select a hypothesis candidate (maps to select_candidate).",
    ),
    "confirm_candidate": CommandSpec(
        "confirm_candidate",
        "write",
        "Confirm the active hypothesis (maps to confirm_hypothesis).",
    ),
    "generate_extraction": CommandSpec(
        "generate_extraction",
        "execute",
        "Generate extraction via OperationExecutor.",
    ),
    "export_layer": CommandSpec(
        "export_layer",
        "write",
        "Export the active extraction layer (maps to export_active_extraction).",
    ),
    "save_project": CommandSpec(
        "save_project",
        "write",
        "Save the active project (maps to save_project).",
    ),
    "close_project": CommandSpec(
        "close_project",
        "write",
        "Close the active project by starting a fresh empty project.",
    ),
    "batch_execute": CommandSpec(
        "batch_execute",
        "execute",
        "Execute BatchManager over multiple images.",
    ),
}
