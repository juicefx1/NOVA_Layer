# Automation Event Reference

## Status

Approved

## Audience

Integrator, Developer, Plugin Author

## Authority

Authoritative reference for **public Automation events** in Object Workflow.

Architectural authority:

- `00_Project/01_Implementation/ARCHITECTURE.md` (§10 Automation — in-process only)

Related public API docs (do not duplicate command catalogs here):

- `05_Documents/API/00_PUBLIC_API_OVERVIEW.md`
- `05_Documents/API/02_AUTOMATION_COMMAND_REFERENCE.md`
- `05_Documents/API/01_PLUGIN_SDK_REFERENCE.md` (plugin subscription / `PluginChanged`)

Implementation exports:

- `nova_layer.object_workflow.automation`: `AutomationEvent`, `AutomationEventBus`, `AutomationEventType`

## Scope

Document exported event types, verified emit sites, payload keys (required / optional / conditional), and subscription/delivery semantics **as implemented**. No invented ordering, persistence, retry, or remote delivery guarantees.

---

# 1. Introduction

Automation exposes an **in-process** observable event bus. Listeners receive `AutomationEvent` instances when Core publishes them during command execution, workflow progress bridging, batch runs, workspace/project updates, and plugin registration.

There is **no** public remote event stream, durable event log, or replay API.

**Import:**

```python
from nova_layer.object_workflow.automation import (
    AutomationEvent,
    AutomationEventBus,
    AutomationEventType,
)
```

Typical access: `automation_service.events` or `automation_service.subscribe(listener)`.

---

# 2. Audience

| Audience | Use |
|---|---|
| Integrator | Subscribe to command/workflow/batch/project signals |
| Developer | Understand emit sites when composing AutomationService |
| Plugin Author | `subscribe_automation_events` / react to `PluginChanged` |

---

# 3. Event Model Overview

### Envelope (`AutomationEvent`)

| Field | Required on type | Notes |
|---|---|---|
| `event_type` | **required** | One of `AutomationEventType` |
| `session_id` | optional | Present on most session-scoped emits; may be `None` |
| `operation_id` | optional | Automation operation id when applicable |
| `command` | optional | Command name when applicable |
| `payload` | always present (may be empty) | `dict[str, Any]`; keys vary by type/site |
| `timestamp` | **required** (auto) | UTC ISO-8601 `…Z` string |

Method: `to_dict()` stringifies UUIDs and copies `payload`.

### Categories

| Category | Event types |
|---|---|
| Command lifecycle | `OperationStarted`, `OperationCompleted`, `OperationFailed` |
| Workflow / operation progress | `OperationProgress` (bridged from OperationExecutor) |
| Project / workspace | `ProjectChanged`, `WorkspaceChanged` |
| Batch | `BatchChanged` |
| Plugin | `PluginChanged` |

---

# 4. Public Event Types

Complete public set (`AutomationEventType`):

1. `OperationStarted`  
2. `OperationProgress`  
3. `OperationCompleted`  
4. `OperationFailed`  
5. `WorkspaceChanged`  
6. `ProjectChanged`  
7. `BatchChanged`  
8. `PluginChanged`  

No other Automation event type strings are defined on the public Literal.

---

# 5. Command Lifecycle Events

These track an **AutomationOperation** submitted through `AutomationService` (not Domain persistence events).

### `OperationStarted`

| | |
|---|---|
| **When** | Worker begins a queued command after session checks; immediately before registry dispatch |
| **Emit site** | `AutomationService._run_operation` |
| **Envelope** | `session_id` **required**; `operation_id` **required**; `command` **required** |
| **Payload** | `params` **required** — copy of the operation’s param dict |

### `OperationCompleted`

| | |
|---|---|
| **When** | Builtin/plugin handler returns successfully and cancel was not requested |
| **Emit site** | `AutomationService._run_operation` success path |
| **Envelope** | `session_id`, `operation_id`, `command` **required** |
| **Payload** | **required** as the handler’s result `dict` (keys depend on command; see Automation Command Reference) |

### `OperationFailed`

| | |
|---|---|
| **When** | Handler raises `AutomationError` / `ApplicationError` / other Exception; or early cancel path sets cancelled result and publishes |
| **Emit sites** | `_run_operation` exception paths; `cancel()` when it terminalizes a queued/pre-start op |
| **Envelope** | `session_id`, `operation_id`, `command` **required** (on verified sites) |
| **Payload** | See §10 |

**Not emitted:** early returns in `_run_operation` for closed session or `cancel_requested` **before** `OperationStarted` (those set operation status/result but do **not** publish an event in current code).

---

# 6. Workflow and Operation Events

### `OperationProgress`

Bridges **workflow** `OperationExecutor` notifications into the Automation bus. These are **not** AutomationOperation lifecycle events; they carry `workflow_operation_id` inside `payload`.

| Variant | When | Payload keys |
|---|---|---|
| Progress tick | `ObjectWorkflowService` reports `OperationProgress` | `workflow_operation_id` **required**; `current` **required**; `total` **required**; `message` **required** |
| Terminal snapshot | Service reports `OperationSnapshot` | `workflow_operation_id` **required**; `status` **required**; `current` **required**; `total` **required**; `message` **required**; `error_code` **required as key** (value may be `None`) |

| | |
|---|---|
| **Emit site** | `AutomationService._on_workflow_operation_event` |
| **Envelope** | `session_id`, `operation_id`, `command` typically **absent** (`None`) on these emits |

### `ProjectChanged`

Emitted by builtin handlers when project-facing actions succeed.

| | |
|---|---|
| **Emit site** | `BuiltinCommandHandlers._emit_project_changed` |
| **Envelope** | `session_id` **required**; `operation_id`/`command` usually absent |
| **Payload** | `action` **required** (string); plus **conditional** keys per action (see §7) |

### `WorkspaceChanged`

| | |
|---|---|
| **When** | After open/save/close paths that update workspace active project |
| **Emit site** | `BuiltinCommandHandlers._emit_workspace_changed` |
| **Envelope** | `session_id` **required** |
| **Payload** | `active_project` **required** (may be `None`); `workspace_path` **required** (string) |

### `BatchChanged`

| | |
|---|---|
| **Emit site** | `BuiltinCommandHandlers.batch_execute` |
| **Envelope** | `session_id` **required**; `command="batch_execute"` **required** |
| **Payload** | See §7 (`action=started` / `action=finished`) |

### Domain note

These events are **not** Domain schema change records. Domain mutations happen inside Application; events are Automation observations only.

---

# 7. Event Payload Reference

Legend: **R** = required on that emit site · **O** = optional · **C** = conditional (present for some actions/paths).

## 7.1 Envelope fields (all events)

| Key | Presence |
|---|---|
| `event_type` | **R** |
| `timestamp` | **R** |
| `session_id` | **C** — set on most handler/service emits; often unset on `OperationProgress` |
| `operation_id` | **C** — set on automation op lifecycle / some cancel failures |
| `command` | **C** — set on automation op lifecycle and `BatchChanged` |
| `payload` | **R** (dict; may be empty only if a future site omits keys — current sites always pass keys listed below) |

## 7.2 `OperationStarted`

| Payload key | Presence | Notes |
|---|---|---|
| `params` | **R** | `dict` copy of submitted params |

## 7.3 `OperationCompleted`

| Payload key | Presence | Notes |
|---|---|---|
| *(handler-specific)* | **R** as a whole | Entire handler return dict becomes `payload` (e.g. `project_id`, `candidate_ids`, …). No single shared key set. |

## 7.4 `OperationFailed`

| Payload key | Presence | Notes |
|---|---|---|
| `status` | **C** | `"cancelled"` on `cancel()` early terminal publish |
| `error_code` | **C** | Present on AutomationError / ApplicationError / generic failure publishes |
| `error_message` | **C** | Paired with `error_code` on those paths |

Verified combinations:

- Cancel terminalized by `cancel()`: `{ "status": "cancelled" }`  
- `AutomationError`: `{ "error_code", "error_message" }`  
- `ApplicationError` mapped: `{ "error_code", "error_message" }`  
- Generic `Exception`: `{ "error_code": "OperationFailed", "error_message": str(exc) }`  

## 7.5 `OperationProgress`

**Progress tick:**

| Key | Presence |
|---|---|
| `workflow_operation_id` | **R** |
| `current` | **R** |
| `total` | **R** |
| `message` | **R** |

**Terminal snapshot bridge:**

| Key | Presence |
|---|---|
| `workflow_operation_id` | **R** |
| `status` | **R** |
| `current` | **R** (from `progress_current`) |
| `total` | **R** (from `progress_total`) |
| `message` | **R** |
| `error_code` | **R** as a key; value may be `None` | Always included on snapshot bridge emits |

## 7.6 `ProjectChanged`

Always includes:

| Key | Presence |
|---|---|
| `action` | **R** |

Conditional keys by `action` (builtin handlers):

| `action` | Additional keys |
|---|---|
| `open` | `package_path` **R** |
| `load_image` | `source_id` **R** |
| `create_artist_intent` | `intent_id` **R** |
| `select_candidate` | `hypothesis_id` **R** |
| `confirm_candidate` | `confirmed_object_id` **R** |
| `export_layer` | `destination` **R** |
| `save` | `package_path` **R** |
| `close` | `project_id` **R** |

## 7.7 `WorkspaceChanged`

| Key | Presence |
|---|---|
| `active_project` | **R** (nullable path string) |
| `workspace_path` | **R** |

## 7.8 `BatchChanged`

**`action=started`:**

| Key | Presence |
|---|---|
| `action` | **R** (`"started"`) |
| `job_id` | **R** |
| `count` | **R** (queue length) |

**`action=finished`:**

| Key | Presence |
|---|---|
| `action` | **R** (`"finished"`) |
| `job_id` | **R** |
| `status` | **R** |
| `completed` | **R** |
| `failed` | **R** |
| `cancelled` | **R** |

## 7.9 `PluginChanged`

| Emit site | Payload |
|---|---|
| `AutomationService.bind_plugin_manager` | `action` **R** (`"automation_bound"`); `plugin_count` **R** |
| `AutomationService.register_helper` | `action` **R** (`"register_helper"`); `helper` **R** (`"{plugin_id}.{name}"`) |
| `AutomationCommandRegistry.register_plugin_command` | `action` **R** (`"register_command"`); `plugin_id` **R**; `command` **R** (qualified name) |

Envelope: typically no `session_id` / `operation_id` / `command` on these emits.

---

# 8. Subscription Model

### `AutomationEventBus` (public)

| Method | Behavior |
|---|---|
| `subscribe(listener)` | Append listener if not already present |
| `unsubscribe(listener)` | Remove matching listener identity |
| `publish(event)` | Snapshot listener list under lock, then invoke each listener |

Listener type: `Callable[[AutomationEvent], None]` (not separately exported; used by subscribe APIs).

### How to subscribe

1. `automation_service.subscribe(listener)` / `unsubscribe(listener)`  
2. `automation_service.events.subscribe(listener)`  
3. Plugins: `PluginRegistrationContext.subscribe_automation_events(listener)` when the bus is attached (`ARCHITECTURE` / Plugin SDK Reference)

---

# 9. Delivery and Ordering Semantics

**Confirmed by implementation:**

- Delivery is **synchronous** and **in-process** on the publishing thread.  
- Listeners run **sequentially** in subscription order (list iteration after snapshot).  
- Listener exceptions are **swallowed** (isolated); they do not fail `publish` or abort remaining listeners.  
- Duplicate `subscribe` of the same callable is ignored (identity check).  

**Not provided (do not assume):**

- Asynchronous/queued delivery  
- Cross-process or networked delivery  
- Persistence, replay, acknowledgements, or at-least-once / exactly-once guarantees  
- Global ordering across different publishers/threads beyond “happens-before” of the calling code  
- Delivery after `AutomationService.shutdown()`  
- That every state transition emits an event (see silent cancel/closed-session paths in §5 / §10)  
- Filtering, topics, or schema versioning of payloads beyond the envelope fields  

---

# 10. Error and Cancellation Events

| Situation | Public event? | Notes |
|---|---|---|
| Handler failure | **Yes** — `OperationFailed` with `error_code` / `error_message` | |
| Generic exception | **Yes** — `OperationFailed` with `error_code="OperationFailed"` | |
| `cancel()` terminalizes queued/pre-start op | **Yes** — `OperationFailed` with `payload.status="cancelled"` | |
| Cancel requested after start; handler raises `Cancelled` | **Yes** — `OperationFailed` with error fields | |
| `cancel_requested` before `OperationStarted` (early return) | **No event** in current code | Operation record still marked cancelled |
| Session closed before start | **No event** in current code | Operation marked failed locally |
| Workflow cancel/progress | May appear as `OperationProgress` snapshots and/or later `OperationFailed` | Depends on timing |

Cancellation of underlying workflow ops is requested via service/batch cancel paths; observers should watch both Automation lifecycle events and `OperationProgress` bridges.

---

# 11. Version Compatibility

| Surface | Notes |
|---|---|
| `AutomationEventType` | Fixed public Literal of eight strings |
| Envelope fields | Stable on `AutomationEvent` / `to_dict()` |
| Payload keys | Command- and site-specific; additive changes possible without a separate event-schema version |
| Plugin SDK | Event subscription requires automation bus binding; SDK version rules apply to plugins, not to event payloads |
| Transport | In-process only for v1.0 RC |

There is no separate “events schema version” constant distinct from the Automation/Plugin SDK surfaces.

---

# 12. Related Documents

| Document | Role |
|---|---|
| `05_Documents/API/02_AUTOMATION_COMMAND_REFERENCE.md` | Commands that trigger many of these events |
| `05_Documents/API/01_PLUGIN_SDK_REFERENCE.md` | `subscribe_automation_events`, plugin command registration |
| `05_Documents/API/00_PUBLIC_API_OVERVIEW.md` | API category index |
| `00_Project/01_Implementation/ARCHITECTURE.md` | Architecture authority |

---

## Explicitly Excluded (Internal)

- Non-exported listener type alias module details beyond subscribe signatures  
- Thread-pool / ContextVar / cancel-flag internals  
- Domain change feeds, Qt signals, Phase 1 events  
- Invented guarantees (retry, persistence, remote fan-out)  

## Implementation Notes / Gaps

- Builtin handlers skip `ProjectChanged` / `WorkspaceChanged` / `BatchChanged` when constructed with `events=None` (no publish).  
- Closed-session and pre-start cancel returns update operation state without publishing lifecycle events.  
- No dedicated `OperationCancelled` type; cancellation uses `OperationFailed` (and sometimes silent status-only updates).  
- `OperationCompleted.payload` has no shared schema beyond “handler return dict”.  
- No event schema version field on the envelope.  
