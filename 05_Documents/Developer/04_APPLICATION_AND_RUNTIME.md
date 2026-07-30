# Application and Runtime

## Status

Approved

## Audience

Developer, Maintainer

## Authority

Developer narrative for how Object Workflow **executes work** in the Application layer and what **Runtime** owns.

Architectural authority (do not redefine layers here):

- `00_Project/01_Implementation/ARCHITECTURE.md`

Package map:

- `05_Documents/Developer/01_PROJECT_STRUCTURE.md`

Related guides (do not duplicate):

- `05_Documents/Developer/00_DEVELOPER_GUIDE.md`
- `05_Documents/Developer/06_PLUGIN_SDK_GUIDE.md`
- `05_Documents/Developer/07_AUTOMATION_GUIDE.md`
- `05_Documents/API/00_PUBLIC_API_OVERVIEW.md`

## Scope

Responsibilities and integration of `object_workflow.application` and `object_workflow.runtime` as implemented. Not a substitute for ARCHITECTURE.md. Not a private-API tour of `ObjectWorkflowService` method lists or cache internals.

---

# 1. Introduction

When a user (or Automation command) loads a source, generates candidates, confirms an object, or extracts a layer, the work is orchestrated by the **Application** layer.

**Runtime** is not a fifth product layer in the dependency stack. Per ARCHITECTURE, runtime caches and the OperationExecutor session are **Application-owned infrastructure concerns**: ephemeral, session-scoped, and never written into Project Schema 2.0 or Workspace documents.

```text
Presentation / Automation / Plugin registration
        │
        ▼
Application  (ObjectWorkflowService · WorkspaceManager · BatchManager)
        │         └── Runtime helpers (caches, metrics, decode)
        ▼
Domain Project (authoritative state)
        │
        ▼
Ports → Adapters / Providers
```

Canonical packages:

| Package | Role |
|---|---|
| `nova_layer.object_workflow.application` | Use-case orchestration |
| `nova_layer.object_workflow.runtime` | Disposable caches / metrics / background decode |
| `nova_layer.object_workflow.ports` | Protocols for compute, store, executor |
| `nova_layer.object_workflow.domain` | Schema 2.0 Project aggregate |

Public Application entry commonly used by integrators: `ObjectWorkflowService`, `ApplicationError` (also re-exported from `nova_layer.object_workflow`). Workspace and batch managers live in the same application package and are composed by the desktop controller / Automation.

---

# 2. Runtime Overview

**What Runtime is**

Exported helpers under `nova_layer.object_workflow.runtime`:

| Surface | Purpose |
|---|---|
| `RuntimeCacheBundle` | Session bundle: image / mask / thumbnail / preview caches + shared `PerformanceMonitor` |
| Typed caches (`ImageCache`, `MaskCache`, …) | Budgeted LRU-style memory caches for decoded frames and overlays |
| `PerformanceMonitor`, `InFlightDeduper` | Timing samples and in-flight load deduplication |
| `BackgroundDecodeService` | Background decode helper for presentation/session hygiene |
| Budget constants | Default byte budgets for each cache class |

**What Runtime is not**

- Not Domain state  
- Not Project or Workspace persistence  
- Not a place to put business rules or confirmation logic  
- Not a public extension SDK (prefer Ports + Plugin SDK for providers)

**Ownership**

- Desktop OW composition owns a `RuntimeCacheBundle` for the UI/session and clears it on coordinated shutdown.  
- `BatchManager` may accept an optional `RuntimeCacheBundle` for source caching during a job and must clear/hygiene afterward (ARCHITECTURE §11).  
- `ObjectWorkflowService` owns the **OperationExecutor**, in-memory Project/assets, and an **ephemeral temp workspace** for operation artifacts — these are Application session concerns even though the executor Protocol lives under Ports.

---

# 3. Application Layer Responsibilities

Primary Application types (ARCHITECTURE §6):

| Type | Responsibility |
|---|---|
| `ObjectWorkflowService` | Active Project use cases: load/save, intent, generate/select/confirm, extraction, export/host delivery coordination, operation wait/cancel |
| `WorkspaceManager` | Application-lifetime preferences/session (`workspace.json`) — not Project schema |
| `BatchManager` | Multi-image queue over the **same** service confirmation/extraction paths |
| `ApplicationError` | Structured Application failures (`code` + `message`) |

Rules that must hold when extending Application:

1. Orchestrate through **Ports** — do not embed AI algorithms in Application.  
2. Generate / extract must go through **OperationExecutor** — do not bypass.  
3. Validate provider results before committing Domain entities.  
4. Only Application mutates the Object Workflow `Project` aggregate.  
5. Do not invent a second workflow stack for batch or Automation.

Typical interactive progression (Application-owned):

```text
LoadSource → CreateArtistIntent → GenerateHypothesis → ConfirmHypothesis → GenerateExtraction
```

Confirmation remains explicit; automatic batch confirmation is opt-in only (ARCHITECTURE §11).

---

# 4. Runtime Lifecycle

### Session start

Composition roots (tests, scripts, or `ObjectWorkflowController`) construct:

1. Workspace (load `workspace.json` if used)  
2. Provider registries / selected adapters  
3. `ObjectWorkflowService` with `ProjectStore`, inference (and optional extraction) engines, optional host registry  
4. Optional `RuntimeCacheBundle`, `BatchManager`, `PluginManager`, `AutomationService`

### During the session

- Domain `Project` and asset bytes live on the service.  
- Long-running generate/extract work is submitted to the bound `OperationExecutor`; progress/snapshots notify Application listeners.  
- Runtime caches hold **decoded** frames/overlays for UI or batch — discardable under memory pressure.  
- Provider sessions (GPU/ONNX predictors, etc.) remain in **adapters**, not in Domain or Workspace.

### Shutdown (coordinated)

ARCHITECTURE / controller order (conceptual):

```text
Cancel active service operation / batch
 → save Workspace
 → PluginManager.shutdown()
 → RuntimeCacheBundle.clear()
 → ObjectWorkflowService.shutdown()
```

`ObjectWorkflowService.shutdown()` (verified behaviour):

- Idempotent  
- Best-effort cancel of a running operation  
- Shuts down the executor if it exposes `shutdown`  
- Calls provider `shutdown`/`close` hooks when present  
- Removes the ephemeral temp workspace directory  

UI close paths must invoke the composition-root shutdown — do not leak executor threads, caches, or temp dirs.

---

# 5. Service Coordination

### Single-image path

```text
Caller (UI / Automation / test)
        │
        ▼
ObjectWorkflowService use-case method
        │
        ├── validate request / active entities
        ├── submit OperationWork via OperationExecutor   (generate / extract)
        ├── wait / observe OperationProgress|Snapshot
        ├── validate adapter results
        └── commit Domain entities + assets; derive workflow state
```

Host delivery and export are Application-coordinated against host adapters registered for the session — still without moving Domain rules into adapters.

### Batch path

```text
BatchManager
        │
        └── for each queue item → ObjectWorkflowService paths
              (interactive confirmation default; automatic only when opted in)
```

Batch does not implement a second Domain or confirmation model.

### Operation observation

Callers may register operation event handlers on the service (`add_operation_event_handler`). Automation bridges those progress/snapshot notifications onto its in-process event bus (see Automation / Event guides).

### Default executor note

If no executor is injected, the service uses the in-process threaded executor adapter historically named `MockOperationExecutor`. Architecturally it is the Core OperationExecutor adapter for deterministic offline behaviour — not a “discard work” stub (ARCHITECTURE §7 / ADR-002).

---

# 6. Domain Interaction

| Direction | Allowed |
|---|---|
| Application → Domain | Create/update Project entities after validation; derive workflow state |
| Domain → Application | Never |
| Adapters → Domain mutation | Never — adapters return Port results only |
| Presentation → Domain | Never — go through Application |

Domain remains Schema **2.0** only for Object Workflow. Field contracts: Domain model spec + Schema Reference. Lifecycle/confirmation rules: lifecycle / Domain specs — not redefined here.

Application errors such as `NO_PROJECT`, `NO_ACTIVE_INTENT`, validation failures, or `CANCELLED` surface as `ApplicationError` (or mapped Automation errors when called via Automation).

---

# 7. Ports and Adapters

```text
Application
    uses Protocols in object_workflow.ports
        │
        ▼
Adapters implement those Protocols
(registries, JsonProjectStore, inference/matting/host adapters, executor adapter)
```

Important Ports (public package `nova_layer.object_workflow.ports`):

| Port theme | Examples |
|---|---|
| Inference | `CoreInferenceEngine`, request/success types, provider descriptors |
| Extraction | `PrecisionExtractionEngine`, extraction provider descriptors |
| Persistence | `ProjectStore` |
| Execution | `OperationExecutor`, `OperationProgress`, `OperationSnapshot` |

Rules:

- Ports define request/result shapes — they must not receive Domain `Project` aggregates as engine inputs or return Domain entities as provider output.  
- Application validates and maps Port results into Domain commits.  
- Plugins register **into** adapter registries via Plugin SDK; they do not become a second Application layer.

Engine/port field detail: `00_Project/01_Implementation/03_ENGINE_INTERFACE_SPEC.md` and Ports package docs — not duplicated here.

---

# 8. Plugin Integration

Plugins are additive registration into Core registries (`ARCHITECTURE.md` §9).

Integration with Application/Runtime:

| Step | What happens |
|---|---|
| Discover / load | `PluginManager` validates manifests and imports entry modules |
| Register | `PluginRegistrationContext` registers inference / matting / host factories into registries used when composing `ObjectWorkflowService` |
| Failures | Isolated per plugin — must not abort Application startup |
| Packages | Local `.nova-plugin` only; install root is Workspace/env metadata, not Project schema |
| Shutdown | Composition root calls `PluginManager.shutdown()` before/around service teardown |

Runtime caches are **not** a plugin extension point. Provider authors implement Ports; see Plugin SDK Guide / Reference.

Reloading an already-registered plugin id may require application restart (implementation constraint).

---

# 9. Automation Integration

Automation is Application orchestration, not a transport layer (`ARCHITECTURE.md` §10).

```text
AutomationService
        │
        ├── ObjectWorkflowService   (builtin command handlers)
        ├── BatchManager           (batch_execute)
        ├── WorkspaceManager       (shared session workspace)
        └── PluginManager          (optional; namespaced commands / event subscribe)
```

Verified integration facts:

- Commands map to existing service/batch actions — same confirmation path as UI.  
- Automation may attach listeners to workflow operation events and republish on its in-process bus.  
- Permissions are session-scoped (`read` / `write` / `execute`).  
- No HTTP/REST/WebSocket/RPC in Core.

Usage detail: Automation Guide + Command/Event references.

---

# 10. Error Propagation

| Layer | Typical surface |
|---|---|
| Domain validation | Intent/schema helpers raise validation errors consumed by Application |
| Ports / Adapters | Provider/store errors with codes; Application maps or wraps |
| Application | `ApplicationError(code, message)` for use-case failures |
| Automation | `AutomationError` (extends Application error shape) + `AutomationResult.ok == False` |
| Plugins | SDK errors (`PluginValidationError`, `PluginRuntimeError`, …) isolated at load/register |

Callers should branch on **codes**, not string matching of messages. Do not assume every failure emits an Automation event (Event Reference documents non-emission cases).

Cancel paths: Application `cancel_operation` / batch cancel / Automation `cancel` are cooperative with the executor and providers; always shut down composition roots to release resources.

---

# 11. Best Practices

1. Put new use cases on `ObjectWorkflowService` (or Batch wrapping it) — not in UI widgets or adapters.  
2. Keep generate/extract behind `OperationExecutor`.  
3. Treat Runtime caches as disposable; never persist them into Project or Workspace.  
4. Clear or drop cache bundles on session/batch end and on shutdown.  
5. Compose Plugins → registries → service; do not let plugins mutate Domain directly.  
6. Prefer Automation for scripted sequences that must match UI semantics.  
7. Propagate `ApplicationError` codes upward; map at API boundaries only.  
8. Invoke coordinated shutdown from the composition root (controller or test teardown).  
9. Keep Workspace free of Project payloads and live GPU sessions.  
10. Extend Ports/Adapters for new providers; do not invent a parallel Application stack.  

---

# 12. Related Documents

| Document | Role |
|---|---|
| `00_Project/01_Implementation/ARCHITECTURE.md` | Sole architecture authority |
| `00_Project/01_Implementation/07_ARCHITECTURE_DECISIONS.md` | ADR rationale (executor, shutdown, workspace, …) |
| `00_Project/01_Implementation/03_ENGINE_INTERFACE_SPEC.md` | Port/engine contracts |
| `00_Project/01_Implementation/02_DOMAIN_MODEL_SPEC.md` | Domain field authority |
| `05_Documents/Developer/01_PROJECT_STRUCTURE.md` | Package layout |
| `05_Documents/Developer/05_WORKSPACE_AND_PERSISTENCE.md` | Workspace/persistence narrative (when written) |
| `05_Documents/Developer/06_PLUGIN_SDK_GUIDE.md` | Plugin workflow |
| `05_Documents/Developer/07_AUTOMATION_GUIDE.md` | Automation workflow |
| `05_Documents/API/00_PUBLIC_API_OVERVIEW.md` | Public API index |
| `05_Documents/API/03_EVENT_REFERENCE.md` | Operation progress bridging into Automation events |

---

## Explicitly Out of Scope

- Method-by-method `ObjectWorkflowService` API catalog  
- Internal work-class / thread-pool / ContextVar details  
- Qt signal graphs inside `ObjectWorkflowController`  
- Phase 1 Smart Layer Application/Runtime (separate bounded context)  
- Invented distributed runtime, remote executors, or durable job queues  

## Documentation Gaps

- `05_Documents/Developer/05_WORKSPACE_AND_PERSISTENCE.md` may still be a stub — Workspace rules live primarily in ARCHITECTURE §8 until that guide is filled.  
- No separate public “Application API reference” beyond Overview + this narrative; service method lists are intentionally not mirrored here.  
- Batch product/UX guide may still be incomplete relative to Feature 11 philosophy docs.  
- GPU/provider session teardown beyond best-effort `shutdown`/`close` hooks depends on each adapter and is not uniformly documented per provider.  
