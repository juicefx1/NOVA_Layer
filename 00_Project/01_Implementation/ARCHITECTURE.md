# NOVA Layer Architecture

**Status:** Authoritative for NOVA Layer v1.0 RC  
**Audience:** Developer, Maintainer, Architect  
**Scope:** Logical architecture and ownership rules for the Object Workflow product surface.

This is the **only** architecture reference document for NOVA Layer.

- Product behaviour and Domain field contracts are **not** redefined here — see Domain and lifecycle specs.
- Physical repository layout is **not** redefined here — see `05_Documents/Developer/01_PROJECT_STRUCTURE.md`.
- Decision rationale history is recorded in `07_ARCHITECTURE_DECISIONS.md` (ADRs); this document states the resulting architecture.

When implementing new features:

1. Preserve this architecture unless an ADR explicitly supersedes it.
2. Extend existing layers before introducing new ones.
3. Do not invent a second Domain, Schema, Workspace, or workflow stack.

---

## 1. Introduction

NOVA Layer’s v1.0 Object Workflow product is a desktop application that helps artists:

1. Load a source image into a Project  
2. Express ArtistIntent  
3. Generate hypothesis candidates (Core Inference)  
4. Explicitly confirm a ConfirmedObject  
5. Generate a precision extraction  
6. Export or deliver to a host  

Architecture goals (verified intent of the design):

- Replace inference / extraction providers without changing Domain or UI contracts  
- Persist Projects independently of AI model identity  
- Keep artist confirmation explicit (no silent AI auto-confirm as default)  
- Support offline testing with deterministic in-process engines  
- Allow additive plugins and in-process automation without forking Domain rules  

**Out of product-architecture scope (Phase 1):** Smart Layer code under `nova_layer.domain` / related Phase 1 modules uses Schema **1.0** and remains a **separate** bounded context. Do not merge it into Object Workflow Schema **2.0**.

---

## 2. Design Principles

| Principle | Meaning |
|---|---|
| Single responsibility | Each layer owns one class of concerns |
| Explicit boundaries | Engines never mutate Project; UI never talks to providers |
| Dependency direction | Dependencies flow only downward |
| Immutable history | Confirmation and generation history are append-oriented Domain records |
| Explicit confirmation | ConfirmedObject requires an artist ConfirmationRecord |
| Engine independence | Providers are interchangeable behind Protocols |
| Provider independence | Domain does not import provider SDKs |
| Deterministic workflow | Application owns workflow progression and operation lifecycle |
| Additive extension | Plugins and automation extend Core; they do not fork Domain |

---

## 3. High-Level System Overview

```text
┌─────────────────────────────────────────────────────────────┐
│ Presentation (Qt UI + controllers)                          │
└────────────────────────────┬────────────────────────────────┘
                             │
┌────────────────────────────▼────────────────────────────────┐
│ Application                                                 │
│  ObjectWorkflowService · WorkspaceManager · BatchManager    │
│  AutomationService (in-process)                             │
└───────┬───────────────────────────────┬─────────────────────┘
        │                               │
        │                         ┌─────▼──────┐
        │                         │  Runtime   │
        │                         │ caches /   │
        │                         │ executor   │
        │                         └────────────┘
┌───────▼────────┐
│ Domain         │  Schema 2.0 Project aggregate
│ (authoritative │
│  project state)│
└───────┬────────┘
        │ (via Ports only for compute/IO contracts)
┌───────▼────────────────────────────────────────────────────┐
│ Ports (Protocols)                                           │
│  CoreInference · PrecisionExtraction · ProjectStore ·       │
│  OperationExecutor · Host delivery contracts                │
└───────┬────────────────────────────────────────────────────┘
        │
┌───────▼────────────────────────────────────────────────────┐
│ Adapters / Providers                                        │
│  Registries · SAM2/ONNX/matting · JsonProjectStore ·        │
│  Host adapters · Plugin SDK registration targets            │
└────────────────────────────────────────────────────────────┘
```

Canonical Object Workflow package root:

`02_Source/src/nova_layer/object_workflow/`

| Area | Responsibility |
|---|---|
| `domain/` | Aggregates, confirmation model, workflow-state derivation |
| `ports/` | Engine / store / executor / host Protocols |
| `adapters/` | Concrete providers, store, registries, host delivery |
| `application/` | Use-case orchestration (`ObjectWorkflowService`, `WorkspaceManager`, `BatchManager`) |
| `plugin_sdk/` | Discovery, validation, registration, local `.nova-plugin` packages |
| `automation/` | Transport-independent command orchestration |
| `runtime/` | Ephemeral caches, metrics, decode helpers |

Presentation for Object Workflow lives under `nova_layer.ui` / `nova_layer.app` (controllers), outside the Domain package.

---

## 4. Layered Architecture

### 4.1 Canonical layer names

Authoritative stack (current terminology):

```text
Presentation
        ↓
Application  (+ Automation as application orchestration)
        ↓
Domain
        ↓
Ports
        ↓
Adapters / Providers
```

Runtime caches and the OperationExecutor session are **Application-owned infrastructure concerns**, not Domain state and not a separate product layer.

### 4.2 Terminology mapping (historical → current)

Older drafts (`04_PROJECT_STRUCTURE.md`) used **Engine** and **Infrastructure**. Those names are **retired as layer titles**. Mapping:

| Historical term | Current term | Notes |
|---|---|---|
| Engine Interface | **Ports** | Protocol contracts (`CoreInferenceEngine`, etc.) |
| Engine / Engine Provider | **Adapters / Providers** | Concrete inference, extraction, host adapters |
| Infrastructure (FS, serialization, provider I/O) | **Adapters** (+ Application persistence helpers) | No business rules in adapters |
| Engine Layer (conceptual) | Compute behind Ports | Still must not receive Project or return Domain entities |

Implementation package layout is unchanged; only documentation vocabulary is unified here.

### 4.3 Layer responsibilities

**Presentation**

- Display project/workflow state and progress  
- Capture user input and forward commands to Application  
- Must not contain Domain business rules  
- Must not call Adapters/Providers directly  

**Application**

- Execute use cases and validate requests  
- Own workflow progression and running operations  
- Mutate Domain Project state after validated results  
- Coordinate Ports (inference, extraction, store, executor)  
- Must not implement AI algorithms  

**Domain**

- Own authoritative Project state and business rules  
- Entities include (Object Workflow): Project, SourceImage, ArtistIntent, hypothesis/candidate types, ConfirmationRecord, ConfirmedObject, ExtractionResult, OperationRecord  
- Must not depend on UI, Qt, filesystem I/O, serialization frameworks, OpenCV, or provider SDKs  

**Ports**

- Define request/result Protocols for compute and persistence boundaries  
- Keep Application free of concrete provider types at the contract edge  

**Adapters / Providers**

- Implement Ports (models, store, host delivery, registries)  
- Perform external I/O and provider calls  
- Must never decide Domain business behaviour or mutate Project aggregates directly  

### 4.4 Dependency and communication rules

Allowed:

- Presentation → Application  
- Application → Domain, Ports, Runtime helpers  
- Adapters → Ports (implementations); Application may compose adapters at the composition root  

Prohibited:

- Presentation → Adapters / Providers  
- Presentation → Infrastructure-style direct disk/provider calls bypassing Application  
- Domain → Presentation, Adapters, provider SDKs, Qt, OpenCV, filesystem  
- Adapters → Domain mutation / “owning” Project  
- Reverse dependencies up the stack  

### 4.5 Ownership summary

| Concern | Owner |
|---|---|
| Windows / widgets / user commands | Presentation |
| Use cases, workflow, operation coordination | Application |
| Persistent Project state, confirmation rules | Domain |
| Temporary inference tensors / provider sessions | Adapters (+ Runtime cleanup) |
| Ephemeral decoded frames / cache budgets | Runtime (Application session) |
| External disks, host processes | Adapters |

Only the Application layer may modify Object Workflow Project state.

---

## 5. Domain Layer

Authority for field-level contracts and lifecycle detail:

- `02_DOMAIN_MODEL_SPEC.md`  
- `01_OBJECT_LIFECYCLE_SPEC.md`  

Architectural rules:

- Object Workflow Projects use Schema **2.0** exclusively.  
- Phase 1 Schema **1.0** Projects are a separate type/loader path (ADR-001).  
- Engine/provider output is temporary until Application validates and commits Domain entities.  
- ConfirmedObject requires an explicit ConfirmationRecord with artist confirmation (ADR-003).  
- Workflow state is derived/controlled through Application; UI and providers must not set it ad hoc.  

Typical interactive progression (Application-owned):

```text
LoadSource → CreateArtistIntent → GenerateHypothesis → ConfirmHypothesis → GenerateExtraction
```

`UpdateArtistIntent` is a separate revision command, not a silent side effect of generation.

---

## 6. Application Layer

Primary types (package `object_workflow.application`):

| Type | Role |
|---|---|
| `ObjectWorkflowService` | Active Project use cases, assets, operation submission, host delivery coordination |
| `WorkspaceManager` | Application-lifetime workspace preferences/session (not Project schema) |
| `BatchManager` | Multi-image queue over the same service confirmation/extraction paths |

Rules:

- Application orchestrates Ports; it does not embed provider algorithms.  
- Generate / extract run through `OperationExecutor` — **do not bypass** the executor for those paths.  
- Application validates provider results before committing Domain entities.  

Composition root for the desktop OW UI is `ObjectWorkflowController` (`nova_layer.app`), which wires service, workspace, plugins, batch, and shutdown.

---

## 7. Runtime

Runtime concerns are **session-scoped** and must not be persisted into Project or Workspace schema documents.

Ownership (ADR-002, ADR-007):

- `ObjectWorkflowService` owns the active Project handle, in-memory assets, OperationExecutor, and ephemeral temp workspace used for operation artifacts.  
- `object_workflow.runtime` provides disposable caches/metrics (image/mask/thumbnail/preview budgets).  
- Long-running provider sessions (e.g. inference predictors) are held by adapters and released on coordinated shutdown.  

**Shutdown (coordinated):** `ObjectWorkflowController.shutdown()` cancels active operations/batch → saves workspace → shuts down plugins → clears runtime caches → shuts down service (executor + temp workspace + provider shutdown hooks). UI close paths must invoke this.

The in-process threaded executor used by default is historically named `MockOperationExecutor` for deterministic offline behaviour; architecturally it is the Core OperationExecutor adapter, not a “no-op” discard path (ADR-002).

---

## 8. Workspace

ADR-004:

- Exactly **one** application-lifetime Workspace abstraction: `WorkspaceManager`.  
- Persists environment/session state only (`workspace.json`): recent projects, layout, preferences, plugin install metadata, batch queue metadata as applicable.  
- **Must not** store Project schema payloads, runtime caches, or live GPU/ONNX sessions.  
- Corrupt workspace recovery resets workspace defaults; Projects on disk remain untouched.  
- Saves are atomic (temporary file + fsync when available + replace; backup best-effort).  

Physical paths and UI restore behaviour: Feature 10 philosophy + `05_Documents/Developer/05_WORKSPACE_AND_PERSISTENCE.md` (when written).

---

## 9. Plugin System

ADR-005:

- Plugins register through `PluginRegistrationContext` into Core registries (additive).  
- Plugin load/runtime failures are isolated; they must not abort application startup.  
- Supported extension styles include inference, matting, and host_adapter capabilities as implemented by the SDK.  
- Packages use local `.nova-plugin` archives/directories only — **no** remote marketplace or download pipeline in Core.  
- Reloading an already-registered plugin may require application restart (implementation constraint; not a second plugin architecture).  

Public surface: `nova_layer.object_workflow.plugin_sdk`.  
Authoring detail: Developer / API plugin docs (link, do not duplicate SDK reference here).

---

## 10. Automation

ADR-006:

- `AutomationService` maps commands to existing `ObjectWorkflowService` / `BatchManager` actions **in-process**.  
- No HTTP / REST / WebSocket / RPC transport in v1.0 Core.  
- Permissions are session-scoped (`read` / `write` / `execute`).  
- Automation must use the same confirmation path as UI (no Domain bypass).  
- Plugin commands are namespaced and must not override builtins.  

Public surface: `nova_layer.object_workflow.automation`.  
Command/event catalogs: `05_Documents/API/` references (when written).

---

## 11. Batch Processing

Architectural constraints (aligned with ADR-003):

- Batch reuses `ObjectWorkflowService` paths; it does not implement a second workflow.  
- **Interactive confirmation is the default** mode.  
- Automatic confirmation requires explicit opt-in (`enable_automatic_confirmation` with automatic mode).  
- Confirmed-object binding remains required before extraction.  
- Engine identity is stable for a batch run (replacement mid-batch is an error).  
- Runtime source caches may be used during a job and must be cleared afterward as part of session hygiene.  

Product/UX detail: Feature 11 philosophy + Batch developer/user docs.

---

## 12. Persistence

| Data | Store | Architectural rule |
|---|---|---|
| Object Workflow Project | `JsonProjectStore` (Project package) | Schema **2.0**; atomic package replace (temp + backup). Non-`2.0` rejected. |
| Workspace | `WorkspaceManager` → `workspace.json` | Atomic replace; must not corrupt Projects. |
| Temp operation artifacts | Service temp workspace | Ephemeral; removed on shutdown. |
| Installed plugins | Local install root + workspace records | Local-only trust model. |

Domain serialization rules and asset path safety belong to Domain/store specs and adapters — not duplicated here.

---

## 13. Extension Points

Approved extension surfaces:

1. **Ports + registries** — new Core Inference / Precision Extraction / Host adapters  
2. **Plugin SDK** — additive registration and local packages  
3. **Automation commands** — in-process commands equivalent to existing user actions  

Non-goals (architecture):

- Cloud sync / multi-user workspace  
- Remote plugin marketplace  
- Second Domain or second Schema inside Object Workflow  
- Bypassing OperationExecutor for generate/extract  
- Remote automation transport  

---

## 14. Architecture Decision References

Living ADR log: `07_ARCHITECTURE_DECISIONS.md`.

| ADR | Decision (summary) |
|---|---|
| ADR-001 | Object Workflow Schema 2.0 is a separate bounded context from Phase 1 Schema 1.0 |
| ADR-002 | Ports over direct engine coupling; in-process OperationExecutor |
| ADR-003 | Explicit artist confirmation; batch automatic mode is opt-in |
| ADR-004 | Workspace independent of Projects |
| ADR-005 | Plugin SDK additive registration; isolated failure |
| ADR-006 | Automation is transport-independent (in-process) |
| ADR-007 | Coordinated shutdown across controller/service/plugins/runtime |

New architecture-changing work requires a new ADR **and** an update to this document.

---

## 15. Related Documents

| Document | Role relative to this file |
|---|---|
| `07_ARCHITECTURE_DECISIONS.md` | Decision records (why); this file is the resulting architecture (what) |
| `02_DOMAIN_MODEL_SPEC.md` | Domain field/aggregate contracts |
| `01_OBJECT_LIFECYCLE_SPEC.md` | Lifecycle rules |
| `03_ENGINE_INTERFACE_SPEC.md` | Port/request-level engine contracts |
| `04_PROJECT_STRUCTURE.md` | **Historical** logical-structure draft — superseded by this document for architecture |
| `05_Documents/Developer/01_PROJECT_STRUCTURE.md` | Physical repository / package map |
| `05_Documents/Developer/00_DEVELOPER_GUIDE.md` | Contributor orientation |
| `05_Documents/00_DOCUMENTATION_ARCHITECTURE.md` | Documentation ownership rules |
| `00_Project/00_Philosophy/` | Product feature intent (not architecture authority) |
| `02_Source/src/nova_layer/object_workflow/` | Implementation |

---

## Document History

- Consolidated Object Workflow architecture into this single authoritative document.  
- Resolved historical **Engine / Infrastructure** naming to **Ports / Adapters**.  
- Preserved ADR-001–007 decisions without introducing new architecture.  
- Removed outdated vertical-slice claims that conflict with the implemented extraction path.  
