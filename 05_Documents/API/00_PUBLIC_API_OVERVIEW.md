# Public API Overview

## Status

Approved

## Audience

Plugin Author, Integrator, Developer

## Authority

This document indexes **public Object Workflow API surfaces**. It does not redefine behaviour.

Architectural authority:

- `00_Project/01_Implementation/ARCHITECTURE.md`

Implementation authority (exports):

- `nova_layer.object_workflow.plugin_sdk`
- `nova_layer.object_workflow.automation`
- `nova_layer.object_workflow.ports`
- `nova_layer.object_workflow` / `…application` / `…domain` (as listed below)

Detailed references (do not duplicate here):

- `05_Documents/API/01_PLUGIN_SDK_REFERENCE.md`
- `05_Documents/API/02_AUTOMATION_COMMAND_REFERENCE.md`
- `05_Documents/API/03_EVENT_REFERENCE.md`
- `05_Documents/API/04_SCHEMA_REFERENCE.md`

## Scope

Single entry point for public APIs of the Object Workflow bounded context (`nova_layer.object_workflow`). Phase 1 Smart Layer packages are out of scope unless explicitly noted as excluded.

---

# 1. Introduction

NOVA Layer exposes a small set of **in-process** public APIs for extending and driving Object Workflow without forking Domain rules.

There is **no** public HTTP, REST, WebSocket, or RPC surface in Core v1.0 RC (`ARCHITECTURE.md` §10, ADR-006).

Public APIs fall into four documentation categories (this folder):

| Category | Package / concern | Reference doc |
|---|---|---|
| Plugin SDK | `nova_layer.object_workflow.plugin_sdk` | `01_PLUGIN_SDK_REFERENCE.md` |
| Automation | `nova_layer.object_workflow.automation` | `02_AUTOMATION_COMMAND_REFERENCE.md` |
| Events | Automation event bus types | `03_EVENT_REFERENCE.md` |
| Schemas | Project Schema 2.0 + plugin package manifests | `04_SCHEMA_REFERENCE.md` |

Supporting contract surface for provider authors:

| Category | Package | Role |
|---|---|---|
| Ports | `nova_layer.object_workflow.ports` | Protocols providers implement |

Supporting orchestration surface for in-process callers (also used by Automation):

| Category | Package | Role |
|---|---|---|
| Application service | `nova_layer.object_workflow` / `…application` | `ObjectWorkflowService`, `ApplicationError` |

---

# 2. Intended Audience

| Audience | Primary APIs |
|---|---|
| **Plugin Author** | Plugin SDK (`PluginRegistrationContext`, manifests, `.nova-plugin` packaging) |
| **Integrator** | Automation (`AutomationService`, sessions, commands, events) |
| **Provider Author** | Ports (`CoreInferenceEngine`, `PrecisionExtractionEngine`, …) + registration via Plugin SDK / Core registries |
| **Application Developer** | `ObjectWorkflowService` + architecture rules; prefer Automation for scripted action sequences |

Not an audience for these docs: reverse-engineering Qt widgets, private adapter modules, or Phase 1 Smart Layer APIs.

---

# 3. Public API Philosophy

Aligned with `ARCHITECTURE.md`:

1. **Additive extension** — Plugins and automation extend Core; they do not replace Domain.  
2. **Same rules as UI** — Automation maps to existing service/batch actions; confirmation remains explicit.  
3. **Ports over coupling** — Providers integrate through Protocols, not by mutating `Project`.  
4. **Local trust** — Plugin packages are local only (no remote marketplace API).  
5. **Stable exports** — Prefer symbols listed in package `__all__`. Deep private modules are unsupported.  
6. **Document what exists** — Optional GPU/host capabilities are environmental; they are not separate public network APIs.

---

# 4. Public API Categories

```text
                    ┌──────────────────────┐
                    │   Plugin packages    │
                    │   (.nova-plugin)     │
                    └──────────┬───────────┘
                               │ register
                    ┌──────────▼───────────┐
                    │     Plugin SDK       │
                    └──────────┬───────────┘
                               │ into registries / Ports
┌──────────────┐    ┌──────────▼───────────┐    ┌─────────────┐
│  Automation  │───▶│ ObjectWorkflowService │───▶│   Domain    │
│  + Events    │    │  (+ BatchManager)    │    │ Schema 2.0  │
└──────────────┘    └──────────┬───────────┘    └─────────────┘
                               │
                    ┌──────────▼───────────┐
                    │ Ports → Adapters     │
                    └──────────────────────┘
```

| Category | Stability expectation | Entry import |
|---|---|---|
| Plugin SDK | Versioned via `SDK_VERSION` / package format | `nova_layer.object_workflow.plugin_sdk` |
| Automation API | Builtin command set + plugin-namespaced commands | `nova_layer.object_workflow.automation` |
| Events | In-process bus on Automation | same package (`AutomationEvent*`) |
| Schemas | Project `schema_version: "2.0"`; plugin manifests | Domain + plugin package types |
| Ports | Protocol contracts for providers | `nova_layer.object_workflow.ports` |
| Application | Service facade for in-process use | `nova_layer.object_workflow` |

---

# 5. Plugin SDK

**Import:** `nova_layer.object_workflow.plugin_sdk`

**Purpose:** Discover, validate, install, and register local plugins into Core registries without modifying Core source (`ARCHITECTURE.md` §9, ADR-005).

**Public themes (see `__all__`; full member list in reference):**

- Lifecycle / discovery: `PluginManager`, `PluginInfo`, `load_manifest`, `PluginManifest`
- Registration: `PluginRegistrationContext`
- Packaging: `PluginPackageManager`, `validate_plugin_package`, `build_nova_plugin_package`, `InstalledPluginRecord`, …
- Compatibility constants: `SDK_VERSION`, `SUPPORTED_SDK_VERSIONS`, `PACKAGE_EXTENSION`, `PACKAGE_FORMAT_VERSION`, `SUPPORTED_PLUGIN_TYPES`
- Errors: `PluginError` hierarchy / package errors

**How it relates to other APIs:**

- Plugins implement or wrap **Ports** (inference / matting / host_adapter capabilities as supported by the SDK).  
- Plugins may register **Automation** commands through the SDK’s automation hooks (namespaced; cannot override builtins).  
- Plugin install metadata may appear in Workspace records; that is Workspace persistence, not a separate public API.

**Reference:** `05_Documents/API/01_PLUGIN_SDK_REFERENCE.md`  
**Guide:** `05_Documents/Developer/06_PLUGIN_SDK_GUIDE.md`

---

# 6. Automation API

**Import:** `nova_layer.object_workflow.automation`

**Purpose:** In-process command orchestration equivalent to UI actions (`ARCHITECTURE.md` §10, ADR-006).

**Public themes:**

- `AutomationService` — create sessions, `submit` / `execute` / `wait` / `cancel`, shutdown  
- `AutomationSession` — permissions and tracking  
- `BUILTIN_COMMANDS` / `AutomationCommandName` — builtin command catalog  
- `AutomationCommandRegistry` — builtin + plugin command registration  
- Results / ops: `AutomationOperation`, `AutomationResult`, `AutomationPermission`, `AutomationStatus`  
- Errors: `AutomationError`

**Builtin commands (names only; parameters in command reference):**

`open_project`, `load_image`, `create_artist_intent`, `generate_candidates`, `select_candidate`, `confirm_candidate`, `generate_extraction`, `export_layer`, `save_project`, `close_project`, `batch_execute`

**How it relates to other APIs:**

- Calls **Application** (`ObjectWorkflowService`, `BatchManager`) — does not reimplement Domain.  
- Emits **Events** on the in-process bus.  
- May be extended by **Plugin SDK** with namespaced commands.

**Not included:** remote clients, auth servers, or HTTP gateways.

**Reference:** `05_Documents/API/02_AUTOMATION_COMMAND_REFERENCE.md`  
**Guide:** `05_Documents/Developer/07_AUTOMATION_GUIDE.md`

---

# 7. Events

**Import:** `nova_layer.object_workflow.automation`  
(`AutomationEvent`, `AutomationEventBus`, `AutomationEventType`)

**Purpose:** Observable notifications for automation and plugin integrators. Transport is **in-process only**.

**Event type names (as defined on `AutomationEventType`):**

`OperationStarted`, `OperationProgress`, `OperationCompleted`, `OperationFailed`, `WorkspaceChanged`, `ProjectChanged`, `BatchChanged`, `PluginChanged`

**How it relates to other APIs:**

- Produced primarily by **Automation** (and bridged workflow progress).  
- **Plugin** registration/lifecycle may publish `PluginChanged`.  
- Events are not a persistence schema and are not written into Project Schema 2.0 documents.

**Reference:** `05_Documents/API/03_EVENT_REFERENCE.md`

---

# 8. Schemas

Two schema families matter to public API consumers:

### 8.1 Object Workflow Project Schema 2.0

- Domain aggregate: `Project` with `schema_version: "2.0"`.  
- Persistence rejects non-`2.0` Object Workflow packages.  
- Public Domain exports (subset): `nova_layer.object_workflow.domain` / root re-exports such as `Project`, `WorkflowState`, `BinaryMask`.  
- Field-level contracts: `00_Project/01_Implementation/02_DOMAIN_MODEL_SPEC.md` and `04_SCHEMA_REFERENCE.md` (when written).

Phase 1 Schema **1.0** is a **different** public/data surface and is not part of this Object Workflow API overview.

### 8.2 Plugin package / manifest schemas

- Plugin SDK package format version: `PACKAGE_FORMAT_VERSION` (currently `"1.0"`).  
- Plugin SDK version: `SDK_VERSION` (currently `"1.0"`; see `SUPPORTED_SDK_VERSIONS`).  
- Manifest / package JSON shapes are owned by the Plugin SDK — document in Schema + Plugin references, not here.

**Reference:** `05_Documents/API/04_SCHEMA_REFERENCE.md`

---

# 9. Version Compatibility

| Version surface | Current value (implementation constants) | Compatibility rule |
|---|---|---|
| Plugin SDK | `SDK_VERSION = "1.0"` | Manifest `sdk_version` must be in `SUPPORTED_SDK_VERSIONS` |
| Plugin package format | `PACKAGE_FORMAT_VERSION = "1.0"` | Must be in `SUPPORTED_PACKAGE_FORMATS` |
| Object Workflow Project | Schema `"2.0"` | Non-`2.0` load → unsupported schema error |
| Automation commands | Builtin set above | Additive plugin commands only; no builtin override |
| Application package | `nova-layer` version in `02_Source/pyproject.toml` | Distribution version; not the same as Schema/SDK numbers |

**Unverified / unsupported as public API guarantees:**

- Cross-major SDK migration tools  
- Schema 1.0 → 2.0 project migrator for Object Workflow  
- Wire-compatible remote event streams  

Check constants in source when documenting exact supported sets; do not hard-code stale copies in call sites.

---

# 10. Related Documents

| Document | Use |
|---|---|
| `00_Project/01_Implementation/ARCHITECTURE.md` | Architecture authority |
| `05_Documents/Developer/00_DEVELOPER_GUIDE.md` | Contributor orientation |
| `05_Documents/Developer/01_PROJECT_STRUCTURE.md` | Package map |
| `05_Documents/API/01_PLUGIN_SDK_REFERENCE.md` | Plugin SDK symbol reference |
| `05_Documents/API/02_AUTOMATION_COMMAND_REFERENCE.md` | Command catalog |
| `05_Documents/API/03_EVENT_REFERENCE.md` | Event payloads |
| `05_Documents/API/04_SCHEMA_REFERENCE.md` | Schema field index |
| `00_Project/01_Implementation/03_ENGINE_INTERFACE_SPEC.md` | Port/request contracts (engine interfaces) |
| `00_Project/01_Implementation/02_DOMAIN_MODEL_SPEC.md` | Domain model authority |

---

## Explicitly Out of Scope (Internal / Non-Public)

Do not treat as supported public extension APIs:

- `nova_layer.ui.*`, `nova_layer.app.*` controllers and widgets  
- Phase 1 `nova_layer.domain` / Phase 1 ports & adapters  
- Private modules under `object_workflow` not listed in package `__all__`  
- Runtime cache helpers (`object_workflow.runtime`) — session infrastructure, not an extension SDK  
- Concrete adapter modules beyond Ports + documented registry/factory exports used at composition roots  
- `08_Release/` artifacts, CI scripts, benchmark CLIs  

Composition helpers under `nova_layer.object_workflow.adapters` (`create_core_inference_engine`, registries, store types, …) exist for Core wiring and tests; prefer **Ports** + **Plugin SDK** for third-party extension.
