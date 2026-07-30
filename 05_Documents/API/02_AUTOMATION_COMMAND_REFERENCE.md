# Automation Command Reference

## Status

Approved

## Audience

Integrator, Developer, Plugin Author

## Authority

Authoritative **public** Automation API reference for Object Workflow.

Architectural authority:

- `00_Project/01_Implementation/ARCHITECTURE.md` (§10 Automation, ADR-006)

Category index (do not duplicate):

- `05_Documents/API/00_PUBLIC_API_OVERVIEW.md`

Plugin registration of commands (SDK side):

- `05_Documents/API/01_PLUGIN_SDK_REFERENCE.md`

Implementation exports:

- `nova_layer.object_workflow.automation` (`__all__`)

## Scope

Document public Automation types, builtin commands (including parameters **as implemented** by builtin handlers), registration, and in-process events. Exclude worker-pool internals, cancel-race implementation details, and non-exported helpers.

---

# 1. Introduction

Automation is an **in-process** command layer over existing Object Workflow services (`ObjectWorkflowService`, optional `BatchManager`, `WorkspaceManager`). It does **not** introduce HTTP/REST/WebSocket/RPC (`ARCHITECTURE.md` §10).

Commands are equivalent to UI actions and must obey the same Domain rules (including explicit confirmation).

**Import root:**

```python
from nova_layer.object_workflow.automation import AutomationService
```

---

# 2. Audience

| Audience | Primary use |
|---|---|
| Integrator | Drive workflow via `AutomationService` sessions/commands/events |
| Developer | Compose Automation with Core services in-process |
| Plugin Author | Register namespaced commands via Plugin SDK / registry |

---

# 3. Automation Overview

```text
AutomationSession (permissions)
        │
        ▼
AutomationService.submit / execute
        │
        ▼
AutomationCommandRegistry.dispatch
        │
        ├── BuiltinCommandHandlers  → ObjectWorkflowService / BatchManager
        └── Plugin command handlers → plugin code
        │
        ▼
AutomationEventBus (in-process)
```

**Permissions** (`AutomationPermission`): `"read"` | `"write"` | `"execute"`.

Default new sessions receive all three permissions unless restricted at `create_session`.

**Statuses** (`AutomationStatus`): `"queued"` | `"running"` | `"completed"` | `"failed"` | `"cancelled"`.

---

# 4. Public Modules

| Public import | Role |
|---|---|
| `nova_layer.object_workflow.automation` | Facade (`__all__` below) |

### Top-level `__all__`

| Symbol | Kind |
|---|---|
| `AutomationService` | Service |
| `AutomationSession` | Type |
| `AutomationCommandRegistry` | Registry |
| `BUILTIN_COMMANDS` | Catalog (`dict[str, CommandSpec]`) |
| `AutomationCommandName` | Type alias (builtin name Literal) |
| `AutomationPermission` | Type alias |
| `AutomationStatus` | Type alias |
| `AutomationOperation` | Type |
| `AutomationResult` | Type |
| `AutomationError` | Exception |
| `AutomationEvent` | Type |
| `AutomationEventBus` | Bus |
| `AutomationEventType` | Type alias |

**Not in `__all__` (internal / non-public):** `BuiltinCommandHandlers`, `CommandSpec` / `CommandHandler` types (exist in `commands.py` / registry but are not facade exports), `bind_workflow_operation`, error factory helpers, retention constants.

`CommandSpec` fields are still described below because they appear on `BUILTIN_COMMANDS` values and `list_commands()` results.

---

# 5. Public Types

## 5.1 `AutomationService`

In-process orchestrator.

**Constructor (keyword args):**

| Parameter | Role |
|---|---|
| `workflow` | Required `ObjectWorkflowService` |
| `workspace` | Optional `WorkspaceManager` (defaults to shared + load) |
| `batch_manager` | Optional; required for `batch_execute` |
| `plugin_manager` | Optional; binds plugin automation registration |
| `max_workers` | Worker pool size (default `4`) |
| `default_timeout_seconds` | Default wait timeout (default `60.0`) |

**Public properties:** `workspace`, `workflow`, `events`, `command_registry`, `plugin_manager`

**Public methods:**

| Method | Role |
|---|---|
| `bind_plugin_manager(plugin_manager)` | Attach PluginManager to registry/event bus |
| `register_helper(plugin_id, name, payload)` | Store opaque helper metadata; emits `PluginChanged` |
| `list_helpers()` | Copy of registered helpers |
| `create_session(*, permissions=None, user_context=None)` | New `AutomationSession` |
| `get_session(session_id)` | Lookup |
| `close_session(session_id)` | Cancel active ops; drop session |
| `subscribe(listener)` / `unsubscribe(listener)` | Event bus |
| `list_commands()` | List `{name, permission, description, builtin, plugin_id}` |
| `submit(session_id, command, params=None)` | Queue → `AutomationOperation` |
| `execute(session_id, command, params=None, *, timeout_seconds=None)` | Submit + wait → `AutomationResult` |
| `wait(operation_id, *, timeout_seconds=None)` | Wait for result; timeout cancels |
| `cancel(operation_id)` | Request cancel |
| `query(operation_id)` | Current `AutomationOperation` or `None` |
| `shutdown()` | Cancel ops; clear sessions; stop pool |

`submit` enforces session open + `session.has_permission(spec.permission)` before queueing.

---

## 5.2 `AutomationSession`

One automation client bound to the current Workspace (no hidden sessions).

| Field / method | Notes |
|---|---|
| `workspace` | `WorkspaceManager` |
| `session_id` | UUID |
| `user_context` | Opaque dict |
| `permissions` | Default all of `read`/`write`/`execute` |
| `active_operations` | In-flight ops |
| `closed` | Closed flag |
| `has_permission(permission)` | Permission check |
| `track` / `untrack` | Operation tracking |
| `to_dict()` | Snapshot for diagnostics |

---

## 5.3 `AutomationOperation` / `AutomationResult`

**`AutomationResult` (frozen):** `ok`, `command`, `payload`, `error_code`, `error_message`; `to_dict()`.

**`AutomationOperation`:** `operation_id`, `session_id`, `command`, `status`, progress fields, `message`, `params`, `result`, `workflow_operation_id`, timestamps, `cancel_requested`; `to_dict()`.

---

## 5.4 `AutomationCommandRegistry`

Builtin + plugin command registry.

| Method | Role |
|---|---|
| `register_builtin(name, handler)` | Bind handler for a **known** builtin name only |
| `register_plugin_command(plugin_id, name, handler, *, permission="execute", description="")` | Namespaced plugin command |
| `get_spec(name)` / `get_handler(name)` | Lookup |
| `list_commands()` | Specs sorted by name |
| `dispatch(session, name, params=None)` | Invoke handler → `dict` payload |

Plugin command names are qualified as `{plugin_id}.{name}` unless already prefixed. Plugin commands **cannot** override builtins.

---

## 5.5 `BUILTIN_COMMANDS` / `AutomationCommandName`

`BUILTIN_COMMANDS`: mapping of builtin name → spec with `name`, `permission`, `description`, `builtin=True`.

`AutomationCommandName`: Literal of the eleven builtin names listed in §6.

---

## 5.6 `AutomationError`

Extends `ApplicationError` (`.code`, `.message`). Common codes used by the layer include: `InvalidCommand`, `InvalidState`, `PermissionDenied`, `OperationFailed`, `Timeout`, `Cancelled` (plus mapped Application codes from workflow).

---

## 5.7 Events (types)

See §8. Public types: `AutomationEvent`, `AutomationEventBus`, `AutomationEventType`.

---

# 6. Built-in Commands

Permissions and descriptions come from `BUILTIN_COMMANDS`. Parameters and result fields below are taken from **builtin handlers** as implemented. Do not assume additional keys.

Default operation timeout for generate commands: service `default_timeout_seconds` (typically `60`), overridable per call via `timeout_seconds`.

### 6.1 `open_project` — permission `write`

Maps to `ObjectWorkflowService.load_project`.

| Params | Required | Notes |
|---|---|---|
| `package_path` | yes | Project package path |

| Result keys | Notes |
|---|---|
| `project_id`, `name`, `package_path`, `summary` | Sets workspace active project |

Events: `ProjectChanged` (`action=open`), `WorkspaceChanged`.

---

### 6.2 `load_image` — permission `write`

Maps to `load_source` (creates a project named `project_name` or `"Automation"` if none active).

| Params | Required | Notes |
|---|---|---|
| `path` | yes | Aliases: `image_path` |
| `project_name` | no | Used only when creating a new project |

| Result keys | Notes |
|---|---|
| `source_image_id`, `original_filename`, `width`, `height` | |

Events: `ProjectChanged` (`action=load_image`).

---

### 6.3 `create_artist_intent` — permission `write`

Maps to `create_artist_intent`.

| Params | Required | Notes |
|---|---|---|
| `intent` or `instruction` | yes* | Mapping; if omitted, `params` itself may be the mapping |
| | | Accepts full intent document **or** payload-only; if neither `schema` nor `payload` present, wraps as `schema=nova.intent.guidance.v1` with `signals` from the mapping |

| Result keys | Notes |
|---|---|
| `intent_id`, `revision` | |

Events: `ProjectChanged` (`action=create_artist_intent`).

---

### 6.4 `generate_candidates` — permission `execute`

Starts hypothesis generation via OperationExecutor and waits.

| Params | Required | Notes |
|---|---|---|
| `timeout_seconds` | no | Float; default service timeout |

| Result keys | Notes |
|---|---|
| `workflow_operation_id`, `candidate_set_id`, `candidate_ids`, `operation_status` | |

Also emits operation lifecycle events (§8).

---

### 6.5 `select_candidate` — permission `write`

| Params | Required | Notes |
|---|---|---|
| `candidate_id` | yes | |

| Result keys | Notes |
|---|---|
| `hypothesis_id`, `candidate_id` | |

Events: `ProjectChanged` (`action=select_candidate`).

---

### 6.6 `confirm_candidate` — permission `write`

Maps to `confirm_hypothesis` (explicit artist confirmation path).

| Params | Required | Notes |
|---|---|---|
| `hypothesis_id` | no | If omitted, confirms active hypothesis |

| Result keys | Notes |
|---|---|
| `confirmed_object_id`, `revision` | |

If a batch job is awaiting confirmation, notifies `BatchManager`.  
Events: `ProjectChanged` (`action=confirm_candidate`).

---

### 6.7 `generate_extraction` — permission `execute`

| Params | Required | Notes |
|---|---|---|
| `timeout_seconds` | no | |
| `settings` | no | Mapping passed to `start_generate_extraction` when provided |

| Result keys | Notes |
|---|---|
| `workflow_operation_id`, `extraction_id`, `confidence`, `operation_status` | |

---

### 6.8 `export_layer` — permission `write`

Maps to `export_active_extraction`.

| Params | Required | Notes |
|---|---|---|
| `destination` | yes | Aliases: `path`, `export_path` |
| `allow_overwrite` | no | Default `false` |

| Result keys | Notes |
|---|---|
| `destination`, `adapter_id`, `action` | Updates workspace recent export directory |

Events: `ProjectChanged` (`action=export_layer`).

---

### 6.9 `save_project` — permission `write`

| Params | Required | Notes |
|---|---|---|
| `package_path` | yes | |

| Result keys | Notes |
|---|---|
| `package_path` | Sets workspace active project |

Events: `ProjectChanged` (`action=save`), `WorkspaceChanged`.

---

### 6.10 `close_project` — permission `write`

Creates a fresh empty project (UI “new/empty” equivalent) and clears workspace active project.

| Params | Required | Notes |
|---|---|---|
| `project_name` | no | Default `"Untitled"` |

| Result keys | Notes |
|---|---|
| `project_id`, `name`, `closed` | `closed=true` |

Events: `ProjectChanged` (`action=close`), `WorkspaceChanged`.

---

### 6.11 `batch_execute` — permission `execute`

Requires `BatchManager` configured on `AutomationService`.

| Params | Required | Notes |
|---|---|---|
| `image_paths` | yes | Non-empty list/tuple; alias `images` |
| `intent` or `intent_snapshot` | yes | Mapping (shared ArtistIntent snapshot) |
| `confirmation_mode` | no | Default **`"automatic"`** in this handler; allowed Batch values: `"interactive"` \| `"automatic"` |
| `enable_automatic_confirmation` | no | Default `true` when mode is `"automatic"`, else as provided |
| `export_directory` | no | |
| `host_adapter_id` / `host_action` | no | |
| `selection_policy` | no | Default `"highest_confidence"`; also `"first_candidate"` |

| Result keys | Notes |
|---|---|
| `job_id`, `status`, `statistics` | `statistics`: `completed`, `failed`, `cancelled`, `total` |

Events: `BatchChanged` with `action=started` / `action=finished`.

**Important:** BatchManager still requires explicit automatic opt-in for automatic mode. This handler sets `enable_automatic_confirmation` by default when `confirmation_mode` is `"automatic"`. Interactive batch still requires confirmation via the normal confirmation path (e.g. `confirm_candidate` while awaiting confirmation). Unsupported mode/policy values fail through Application/Batch errors.

---

# 7. Command Registration

### Builtins

`AutomationService` constructs `BuiltinCommandHandlers` and calls `AutomationCommandRegistry.register_builtin` for each builtin name. Callers do not normally re-register builtins.

### Plugins

Preferred path: Plugin SDK `PluginRegistrationContext.register_automation_command(...)` (see Plugin SDK Reference), which ultimately calls:

`AutomationCommandRegistry.register_plugin_command(plugin_id, name, handler, ...)`.

Rules:

- Namespaced as `{plugin_id}.{name}`  
- Cannot override builtin names  
- Invalid names (empty / path separators) rejected  
- Emits `PluginChanged` (`action=register_command`) when the registry has an event bus  

`AutomationService.bind_plugin_manager` attaches the registry and event bus to `PluginManager`.

`register_helper` / `list_helpers` store opaque helper payloads for scripts/plugins (not builtin workflow commands).

---

# 8. Event Interaction

**Bus:** `AutomationService.events` → `AutomationEventBus`  
**API:** `subscribe` / `unsubscribe` / `publish` (publish used by Core/handlers; listeners should subscribe)

**`AutomationEvent` fields:** `event_type`, optional `session_id` / `operation_id` / `command`, `payload` dict, `timestamp`. Method: `to_dict()`.

### `AutomationEventType` values

| Type | Typical producers / payload notes |
|---|---|
| `OperationStarted` | Service when an automation op begins; payload may include `params` |
| `OperationProgress` | Bridged from workflow OperationExecutor progress/terminal snapshots (`workflow_operation_id`, progress fields, optional `status` / `error_code`) |
| `OperationCompleted` | Successful automation op; payload = handler result dict |
| `OperationFailed` | Failed/cancelled automation op; payload includes error fields or `{status: cancelled}` |
| `ProjectChanged` | Builtin handlers; payload includes `action` and related ids/paths |
| `WorkspaceChanged` | Open/save/close paths; `active_project`, `workspace_path` |
| `BatchChanged` | `batch_execute` start/finish statistics |
| `PluginChanged` | Plugin command registration / helper registration / automation bind |

Listener exceptions are isolated (do not fail the publisher).

**Transport:** in-process only. No remote event stream API.

Detailed payload catalog expansion: `05_Documents/API/03_EVENT_REFERENCE.md`.

---

# 9. Version Compatibility

| Surface | Notes |
|---|---|
| Builtin command set | The eleven names in `AutomationCommandName` / `BUILTIN_COMMANDS` |
| Permissions | `read` / `write` / `execute` only |
| Plugin commands | Additive, namespaced; must not collide with builtins |
| Plugin SDK | Command registration requires compatible SDK (`SDK_VERSION`); see Plugin SDK Reference |
| Project Schema | Automation mutates Schema **2.0** Projects via Application — not a separate automation schema |
| Distribution version | `nova-layer` package version ≠ automation command set version |

No public guarantee of wire-stable remote clients or cross-major command renames without documentation updates.

---

# 10. Related Documents

| Document | Role |
|---|---|
| `05_Documents/API/00_PUBLIC_API_OVERVIEW.md` | API category index |
| `05_Documents/API/01_PLUGIN_SDK_REFERENCE.md` | Plugin command registration |
| `05_Documents/API/03_EVENT_REFERENCE.md` | Event reference (payload depth) |
| `05_Documents/Developer/07_AUTOMATION_GUIDE.md` | Narrative guide |
| `00_Project/01_Implementation/ARCHITECTURE.md` | Architecture authority |
| `nova_layer.object_workflow` / Application | Underlying service APIs |

---

## Explicitly Excluded (Internal)

- `BuiltinCommandHandlers` class and cancel-flag maps  
- Thread pool / operation retention implementation  
- `bind_workflow_operation` / ContextVar wiring  
- Error factory helpers not exported on the facade  
- Qt UI automation hooks  
- Invented commands or parameters not present in builtin handlers  
