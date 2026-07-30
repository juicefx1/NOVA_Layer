from __future__ import annotations

from collections.abc import Callable, Mapping
from threading import RLock
from typing import Any

from nova_layer.object_workflow.automation.commands import (
    BUILTIN_COMMANDS,
    CommandHandler,
    CommandSpec,
)
from nova_layer.object_workflow.automation.errors import invalid_command
from nova_layer.object_workflow.automation.events import AutomationEvent, AutomationEventBus
from nova_layer.object_workflow.automation.models import AutomationPermission
from nova_layer.object_workflow.automation.session import AutomationSession


class AutomationCommandRegistry:
    """Builtin + plugin command registry. Plugin commands inherit plugin permissions."""

    def __init__(self, events: AutomationEventBus | None = None) -> None:
        self._lock = RLock()
        self._specs: dict[str, CommandSpec] = dict(BUILTIN_COMMANDS)
        self._handlers: dict[str, CommandHandler] = {}
        self._events = events

    def register_builtin(self, name: str, handler: CommandHandler) -> None:
        with self._lock:
            if name not in BUILTIN_COMMANDS:
                raise invalid_command(f"unknown builtin command: {name!r}")
            self._handlers[name] = handler

    def register_plugin_command(
        self,
        plugin_id: str,
        name: str,
        handler: CommandHandler,
        *,
        permission: AutomationPermission = "execute",
        description: str = "",
    ) -> None:
        """Register a plugin-provided automation command (validated plugin path only)."""
        key = name.strip()
        if not key or "/" in key or "\\" in key:
            raise invalid_command(f"invalid plugin command name: {name!r}")
        # Namespace plugin commands to avoid colliding with builtins.
        qualified = key if key.startswith(f"{plugin_id}.") else f"{plugin_id}.{key}"
        with self._lock:
            if qualified in BUILTIN_COMMANDS:
                raise invalid_command(
                    f"plugin command cannot override builtin: {qualified!r}"
                )
            self._specs[qualified] = CommandSpec(
                name=qualified,
                permission=permission,
                description=description or f"Plugin command from {plugin_id}",
                builtin=False,
                plugin_id=plugin_id,
            )
            self._handlers[qualified] = handler
        if self._events is not None:
            self._events.publish(
                AutomationEvent(
                    event_type="PluginChanged",
                    payload={
                        "action": "register_command",
                        "plugin_id": plugin_id,
                        "command": qualified,
                    },
                )
            )

    def get_spec(self, name: str) -> CommandSpec:
        with self._lock:
            spec = self._specs.get(name)
            if spec is None:
                raise invalid_command(f"unknown automation command: {name!r}")
            return spec

    def get_handler(self, name: str) -> CommandHandler:
        with self._lock:
            handler = self._handlers.get(name)
            if handler is None:
                raise invalid_command(f"automation command not registered: {name!r}")
            return handler

    def list_commands(self) -> list[CommandSpec]:
        with self._lock:
            return [self._specs[key] for key in sorted(self._specs)]

    def dispatch(
        self,
        session: AutomationSession,
        name: str,
        params: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        self.get_spec(name)
        handler = self.get_handler(name)
        return handler(session, dict(params or {}))


AutomationHelperFactory = Callable[[], Mapping[str, Any]]
