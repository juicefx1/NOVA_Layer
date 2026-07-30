# Automation Guide

## Status

Approved

## Audience

Developer, Integrator, Plugin Author

## Authority

Practical guide for **in-process** Object Workflow Automation.

Architectural authority:

- `00_Project/01_Implementation/ARCHITECTURE.md` (§10 Automation, ADR-006)

API authority (do not duplicate catalogs here):

- `05_Documents/API/02_AUTOMATION_COMMAND_REFERENCE.md` — commands, params, permissions
- `05_Documents/API/03_EVENT_REFERENCE.md` — event types, payloads, delivery semantics
- `05_Documents/API/01_PLUGIN_SDK_REFERENCE.md` — plugin registration APIs
- `05_Documents/Developer/06_PLUGIN_SDK_GUIDE.md` — plugin authoring workflow

Environment setup:

- `05_Documents/Developer/00_DEVELOPER_GUIDE.md`

Public package:

- `nova_layer.object_workflow.automation`

## Scope

Verified workflows: compose `AutomationService`, open sessions, run builtin commands, subscribe to events, extend via plugins, cancel/timeout/error paths. **No** HTTP/REST/WebSocket/RPC. **No** invented remote clients or delivery guarantees.

---

# 1. Introduction

Automation is an application orchestration layer that maps named commands to existing `ObjectWorkflowService` / `BatchManager` actions. It reuses the same confirmation and Domain rules as the UI — it does not bypass Domain (`ARCHITECTURE.md`).

```text
Your script / plugin / integrator code
        │
        ▼
AutomationService  (sessions, submit/execute, events)
        │
        ├── ObjectWorkflowService  (Project use cases + OperationExecutor)
        ├── WorkspaceManager      (shared app workspace)
        ├── BatchManager          (optional; required for batch_execute)
        └── PluginManager         (optional; plugin commands / events)
```

Import root:

```python
from nova_layer.object_workflow.automation import (
    AutomationService,
    AutomationEvent,
    AutomationError,
)
```

---

# 2. Prerequisites

| Requirement | Notes |
|---|---|
| Python **3.12** + editable Core | See Developer Guide |
| Composed `ObjectWorkflowService` | Automation does not create the workflow stack for you |
| `WorkspaceManager` | Passed in or defaults to shared workspace (loaded on construct) |
| `BatchManager` | Only if you need `batch_execute` |
| `PluginManager` | Only if plugins should register Automation commands/events |

Unverified / unsupported as Automation features:

- Networked Automation clients  
- Persistent event logs / replay  
- Guaranteed event emission for every internal cancel/closed-session edge case (see Event Reference)  

---

# 3. Automation Architecture

High-level flow:

```text
create_session(permissions)
        │
submit / execute(command, params)
        │
permission check → queue worker → registry.dispatch
        │
        ├── Builtin handlers → workflow / batch
        └── Plugin handlers  → namespaced commands
        │
AutomationEventBus.publish (in-process, synchronous listeners)
```

| Piece | Role |
|---|---|
| `AutomationSession` | Client handle: permissions, user_context, active ops; uses the **current** Workspace |
| `AutomationService` | Session lifecycle, queue/workers, wait/cancel/query, event subscribe |
| `AutomationCommandRegistry` | Builtin + namespaced plugin commands |
| `AutomationEventBus` | In-process listeners (`subscribe` / `unsubscribe` / `publish`) |
| `AutomationOperation` / `AutomationResult` | Per-command run state and outcome |

Command parameter catalogs and event payloads live in the API references — not repeated here.

---

# 4. Automation Sessions

### Create

```python
session = automation.create_session()
# or restrict permissions:
session = automation.create_session(
    permissions=["read", "write"],  # no "execute"
    user_context={"actor": "ci-script"},
)
```

| Field | Behaviour |
|---|---|
| `session_id` | UUID identifying the session |
| `permissions` | Default: all of `read` / `write` / `execute` |
| `user_context` | Opaque dict stored on the session |
| `workspace` | Same `WorkspaceManager` as the service |
| `closed` | Set by `close_session` |

### Permission model

Each command declares a required permission (Command Reference). `submit` / `execute` fail with `PermissionDenied` if the session lacks it.

Examples:

- `load_image`, `confirm_candidate`, `save_project` → typically `write`  
- `generate_candidates`, `generate_extraction`, `batch_execute` → typically `execute`  

### Close

```python
automation.close_session(session.session_id)
```

Closing marks the session closed, cancels queued/running operations tracked by that session, and drops the session from the service. Further submits on that id raise `InvalidState`.

Always call `automation.shutdown()` when tearing down a process-owned service (cancels remaining ops and shuts the worker pool).

---

# 5. Executing Commands

Builtin names and params: **Command Reference §6**. Discover at runtime:

```python
for item in automation.list_commands():
    print(item["name"], item["permission"], item["builtin"], item["plugin_id"])
```

### Blocking: `execute`

Submit + wait for `AutomationResult`:

```python
result = automation.execute(
    session.session_id,
    "load_image",
    {"path": str(image_path)},
    timeout_seconds=60.0,  # optional; default from service construction
)
if not result.ok:
    raise RuntimeError(f"{result.error_code}: {result.error_message}")
source_id = result.payload.get("source_id")
```

### Non-blocking: `submit` + `wait` / `query`

```python
op = automation.submit(session.session_id, "generate_candidates", {})
# poll:
snapshot = automation.query(op.operation_id)
# or block:
result = automation.wait(op.operation_id, timeout_seconds=120.0)
```

| API | Returns | Notes |
|---|---|---|
| `submit` | `AutomationOperation` | Queues on a worker thread; does not block the caller for the handler body |
| `execute` | `AutomationResult` | `submit` + `wait` |
| `wait` | `AutomationResult` | Raises `Timeout` (and requests cancel) on timeout |
| `query` | `AutomationOperation \| None` | Current status/result snapshot |
| `cancel` | `bool` | Cooperative cancel; see §8 |

### Typical interactive sequence (verified in tests)

```text
load_image
 → create_artist_intent
 → generate_candidates
 → select_candidate
 → confirm_candidate
 → generate_extraction
 → export_layer
 → save_project
```

Optional: `close_project` / `open_project` for package round-trips.  
Optional: `batch_execute` when a `BatchManager` is wired.

**Desktop vs Automation batch defaults (do not conflate):**

| Surface | Confirmation posture |
|---|---|
| Desktop Object Workflow / `BatchManager` product default | **Interactive** confirmation; automatic requires explicit UI/API opt-in (`ARCHITECTURE.md` §11) |
| Automation builtin `batch_execute` | Parameter defaults are defined in the **Command Reference** (handler currently defaults `confirmation_mode` toward automatic when omitted) |

Pass explicit `confirmation_mode` / `enable_automatic_confirmation` when you need a specific mode. Do not repeat param tables here — see Command Reference §6.11.

Do **not** invent alternate Domain mutation commands; Automation only exposes registered command names.

---

# 6. Receiving Events

Event types, payloads, and non-guarantees: **Event Reference**.

### Subscribe

```python
from nova_layer.object_workflow.automation import AutomationEvent

seen: list[str] = []

def on_event(event: AutomationEvent) -> None:
    seen.append(event.event_type)
    if event.event_type == "OperationFailed":
        print(event.command, event.payload)

automation.subscribe(on_event)
# later:
automation.unsubscribe(on_event)
# or: automation.events.subscribe(on_event)
```

### Practical notes (implementation)

- Delivery is **synchronous** and **in-process** on the publishing thread.  
- Listener exceptions are isolated (swallowed); they must not assume they can fail the command.  
- Keep listeners cheap; heavy work can stall other listeners and the publisher.  
- Command lifecycle: watch `OperationStarted` / `OperationCompleted` / `OperationFailed`.  
- Domain-ish observations: `ProjectChanged`, `WorkspaceChanged`, `BatchChanged`.  
- Workflow progress bridge: `OperationProgress` (may omit session/operation envelope fields).  

Do not assume persistence, retry, remote fan-out, or that every cancel/closed-session path emits an event.

---

# 7. Extending Automation from Plugins

Plugin packaging/load: Plugin SDK Guide. Registration APIs: Plugin SDK Reference.

### Bind plugins to Automation

Construct with a `PluginManager`, or call `bind_plugin_manager` later. Binding attaches:

- Automation command registry → `plugin_manager.set_automation_registry(...)`  
- Event bus → `plugin_manager.set_automation_event_bus(...)`  

Plugins loaded **after** binding can use Automation APIs on `PluginRegistrationContext` during `register()`.

### Register a command (plugin `register`)

```python
def register(context) -> None:
    def ping(session, params):
        # session: AutomationSession; params: mapping
        return {"pong": True, "echo": dict(params)}

    context.register_automation_command(
        "ping",
        ping,
        permission="execute",
        description="health check",
    )
    # Invoked as: "{plugin_id}.ping"
```

Rules:

- Namespaced as `{plugin_id}.{name}` — **cannot** override builtins.  
- Handler signature: `(session, params) -> dict` (result becomes `OperationCompleted.payload`).  
- Default permission is `"execute"` unless you pass another.  

Helpers / events:

```python
context.provide_automation_helper("meta", {"docs": "..."})
context.subscribe_automation_events(on_event)
```

If Automation is not bound, these raise `PluginRuntimeError`.

### Direct registry use (tests / composition roots)

```python
automation.command_registry.register_plugin_command(
    "test.plugin",
    "ping",
    handler,
    permission="execute",
)
# execute: "test.plugin.ping"
```

Prefer Plugin SDK registration for real plugins.

---

# 8. Error Handling

### Raised at submit / wait boundary

`AutomationError` (subclass of `ApplicationError`) with `.code` / `.message`:

| Code | Typical cause |
|---|---|
| `PermissionDenied` | Session lacks command permission |
| `InvalidState` | Closed/unknown session; unknown operation for `wait` |
| `InvalidCommand` | Unknown command / bad params (also from handlers) |
| `Timeout` | `wait`/`execute` exceeded timeout (cancel requested) |
| `Cancelled` | Cooperative cancel surfaced as error in some paths |

### Result object (handler / worker failures)

When the worker finishes with failure, `AutomationResult` usually has `ok=False` plus `error_code` / `error_message` (also mirrored on `OperationFailed` events). Always check `result.ok` after `execute` / `wait`.

### Cancel

```python
automation.cancel(operation_id)
```

- Returns `False` if unknown or already terminal.  
- Sets `cancel_requested`; may cancel underlying workflow op / batch.  
- Pre-start cancel may publish `OperationFailed` with `payload.status == "cancelled"`.  
- Some early closed-session / pre-start paths update operation state **without** an event (Event Reference §5 / §10).  

---

# 9. Testing Automation

Prefer offline tests (Developer Guide gate). Patterns from `tests/test_object_workflow_automation.py`:

1. Temp `WorkspaceManager` + composed `ObjectWorkflowService` (test doubles / mock providers).  
2. `AutomationService(workflow, workspace=..., batch_manager=..., plugin_manager=...)`.  
3. `create_session()` → `execute` a short command chain; assert `result.ok` and payload keys.  
4. `subscribe` and assert observed `event_type` values (not full ordering across all producers unless you filter by `command`).  
5. Restricted `permissions=["read"]` → expect `PermissionDenied` on write commands.  
6. Plugin command: `register_plugin_command` or load a plugin with Automation bound; `execute("plugin_id.name")`.  

```bash
cd 02_Source
source .venv/bin/activate
python -m pytest tests/test_object_workflow_automation.py --tb=short
```

Do not mark GPU/`real_host` coverage unless those lanes are intentionally in scope.

---

# 10. Debugging

| Symptom | Check |
|---|---|
| `PermissionDenied` | Session permissions vs command permission in `list_commands()` |
| `InvalidCommand` | Typo; plugin command not registered / Automation not bound before plugin load |
| `InvalidState` | Session closed; wrong operation id; service already shut down |
| `ok=False` with Application codes | Underlying workflow validation (intent schema, missing active entities, etc.) |
| No events | Subscribe **before** `submit`/`execute`; listener errors are swallowed |
| Missing `OperationProgress` | Only bridged when workflow operation events fire |
| `batch_execute` fails | `BatchManager` not passed into `AutomationService` |
| Plugin command missing | Bind Automation before `load_and_register`; restart may be required to reload plugins |
| Timeout | Increase `timeout_seconds`; inspect `query` / cancel behaviour |

Useful dumps:

```python
print(session.to_dict())
print(automation.query(op.operation_id).to_dict())
print(result.to_dict())
```

---

# 11. Best Practices

1. Drive workflows through Automation commands — do not fork Domain rules in scripts.  
2. Use the Command / Event references for params and payloads; keep this guide for workflow.  
3. Prefer least privilege sessions in untrusted automation contexts.  
4. Check `result.ok` every time; do not ignore `error_code`.  
5. Subscribe early; keep listeners fast and exception-safe.  
6. Wire `BatchManager` only when batch is required. Treat **desktop** interactive-as-default separately from **Automation** `batch_execute` parameter defaults (Command Reference).  
7. Bind `PluginManager` before loading plugins that need Automation APIs.  
8. Namespace plugin commands; never attempt builtin overrides.  
9. Call `close_session` / `shutdown` for cleanup in long-running hosts.  
10. Treat Automation as **in-process only** — no remote transport assumptions.  

---

# 12. Common Pitfalls

| Pitfall | Reality |
|---|---|
| Expecting HTTP/RPC Automation | Unsupported in Core (ADR-006) |
| Skipping `confirm_candidate` | Confirmation remains required before extraction |
| Assuming desktop and Automation share the same batch default | Desktop is interactive-by-default; Automation `batch_execute` defaults are in the Command Reference — pass modes explicitly |
| Calling `batch_execute` without `BatchManager` | Handler raises invalid state |
| Restricted session + `execute` commands | `PermissionDenied` |
| Subscribing after work finishes | You miss lifecycle events |
| Assuming every cancel emits an event | Not true for all pre-start/closed-session paths |
| Assuming durable event history | Bus is in-process only |
| Plugin register before Automation bind | Automation context APIs unavailable |
| Overriding `open_project` via plugin name | Builtin override rejected |
| Holding UI thread on long `execute` | Prefer `submit` + progress events when UI responsiveness matters |
| Treating Phase 1 Schema 1.0 APIs as OW Automation | Separate bounded context |

---

# 13. Related Documents

| Document | Role |
|---|---|
| `05_Documents/API/02_AUTOMATION_COMMAND_REFERENCE.md` | Builtin commands + registration |
| `05_Documents/API/03_EVENT_REFERENCE.md` | Event types + payloads + non-guarantees |
| `05_Documents/API/01_PLUGIN_SDK_REFERENCE.md` | `register_automation_command` / events |
| `05_Documents/Developer/06_PLUGIN_SDK_GUIDE.md` | Plugin workflow |
| `05_Documents/API/04_SCHEMA_REFERENCE.md` | Project / intent schemas used by commands |
| `05_Documents/API/00_PUBLIC_API_OVERVIEW.md` | Public API index |
| `05_Documents/Developer/00_DEVELOPER_GUIDE.md` | Environment + offline tests |
| `00_Project/01_Implementation/ARCHITECTURE.md` | Architecture authority |
| `02_Source/tests/test_object_workflow_automation.py` | Verified usage examples |

---

## Explicitly Out of Scope

- Worker-pool / ContextVar / cancel-race internals  
- Qt / `ObjectWorkflowController` as the Automation authoring API  
- Remote transports, auth gateways, or multi-tenant Automation servers  
- Full command parameter tables and event payload matrices (API references)  
- Invented ordering/persistence/retry guarantees  

## Documentation Gaps

- No first-party CLI that wraps `AutomationService` for shell users.  
- No User-facing “macro recorder” / visual Automation builder.  
- Desktop composition wiring (when the app constructs Automation) is application-specific and not fully documented as a separate guide.  
- Silent non-emission on some cancel/closed-session paths is implemented behaviour — integrators must not treat the event bus as a complete state machine log.  
