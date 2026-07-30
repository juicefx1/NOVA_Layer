# NOVA Layer Project Structure

## Status

Approved

## Audience

Developer, Maintainer

## Authority

This document describes repository and package layout as implemented.

Authoritative architecture:

- `00_Project/01_Implementation/ARCHITECTURE.md` (sole architecture reference)
- `00_Project/01_Implementation/07_ARCHITECTURE_DECISIONS.md` (ADR rationale)

Physical layout (this document):

- `02_Source/src/nova_layer/`

## Scope

Physical layout of the monorepo, Object Workflow package map, public import surfaces, and where tests, docs, and release artifacts live.

---

# 1. Repository Top Level

```text
NOVA_Layer/
├── 00_Project/          # Product philosophy + implementation specifications
├── 01_Design/           # Design assets and development planning notes
├── 02_Source/           # Installable Python package + tests
├── 03_AI/               # Model contracts / model assets (not docs)
├── 04_Assets/           # Non-code assets
├── 05_Documents/        # Human documentation (this tree)
├── 06_Test/             # Datasets and acceptance/benchmark reports
├── 07_Build/            # Build outputs / reports
├── 08_Release/          # Build artifacts ONLY (wheels, manifests, smoke JSON)
├── plugins/             # Local plugin discovery root (runtime)
└── .github/workflows/   # CI (ruff + offline pytest)
```

Notes:

- `00_Project/01_Implementation/` holds approved specs (`ARCHITECTURE.md`, Domain, lifecycle, ADRs, RC docs).
- `01_Design/06_Development/` holds roadmap / Phase 1 planning; it is not the Object Workflow architecture source of truth.
- `08_Release/` must remain artifact storage. Release *documentation* lives under `05_Documents/Release/`.

---

# 2. Source Package Layout (`02_Source/`)

```text
02_Source/
├── pyproject.toml
├── README.md                 # Phase 1–oriented source README (historical breadth)
├── src/nova_layer/
│   ├── __main__.py           # Desktop entry: python -m nova_layer
│   ├── object_workflow/      # Object Workflow bounded context (Schema 2.0)
│   ├── domain/               # Phase 1 Domain (Schema 1.0) — separate
│   ├── app/                  # Qt controllers / app services (Phase 1 + OW controller)
│   ├── ui/                   # PySide6 presentation
│   ├── adapters/             # Phase 1 capability adapters (outside OW package)
│   ├── ports/                # Phase 1 ports (outside OW package)
│   ├── host/                 # Host session helpers (Phase 1)
│   └── …                     # acceptance, benchmarks, release helpers, depth/pose tools
└── tests/                    # pytest suite
    └── ui/                   # Qt UI tests (excluded from default CI)
```

Install and test from `02_Source/` with the package editable install (see Developer Guide).

---

# 3. Object Workflow Bounded Context

Canonical root (from `ARCHITECTURE.md`):

`02_Source/src/nova_layer/object_workflow/`

| Directory | Responsibility |
|---|---|
| `domain/` | Aggregates, confirmation model, workflow state derivation (Schema 2.0) |
| `ports/` | Engine / store / executor Protocols |
| `adapters/` | JsonProjectStore, registries, SAM2/ONNX/matting, host delivery adapters |
| `application/` | `ObjectWorkflowService`, `WorkspaceManager`, `BatchManager`, host delivery helpers |
| `plugin_sdk/` | Discovery, validation, registration, local `.nova-plugin` packages |
| `automation/` | Transport-independent command orchestration |
| `runtime/` | Caches, metrics, background decode helpers |

Dependency direction (must hold) — see `ARCHITECTURE.md`:

```text
Presentation (ui/, app Qt controllers)
        ↓
Application (object_workflow/application, automation)
        ↓
Domain (object_workflow/domain) — Schema 2.0
        ↓
Ports (object_workflow/ports)
        ↓
Adapters / Providers (object_workflow/adapters, plugin_sdk)
```

Domain must remain free of Qt, filesystem I/O, and AI framework imports.

---

# 4. Application Entry Points (Implemented)

| Entry | Module | Role |
|---|---|---|
| Desktop app | `python -m nova_layer` → `nova_layer.__main__` | Shows `MainWindow` |
| Object Workflow UI | `nova_layer.ui.object_workflow_window` | OW window |
| Object Workflow controller | `nova_layer.app.object_workflow_controller` | Coordinates service, workspace, plugins, batch, shutdown |
| OW application service | `nova_layer.object_workflow.application.service.ObjectWorkflowService` | Project use cases |
| Workspace | `nova_layer.object_workflow.application.workspace_manager.WorkspaceManager` | Application-lifetime workspace.json |
| Batch | `nova_layer.object_workflow.application.batch_manager.BatchManager` | Multi-image queue |
| Automation | `nova_layer.object_workflow.automation.service.AutomationService` | In-process commands |
| Plugins | `nova_layer.object_workflow.plugin_sdk.manager.PluginManager` | Discovery / registration |

---

# 5. Public Import Surfaces (Package `__all__`)

These are the documented public re-export roots for Object Workflow. Prefer these imports over deep private modules when writing plugins or automation clients.

### `nova_layer.object_workflow`

- `ObjectWorkflowService`
- `Project`
- `WorkflowState`
- `BinaryMask`

### `nova_layer.object_workflow.application`

- `ObjectWorkflowService`
- `ApplicationError`

### `nova_layer.object_workflow.ports`

Protocols and request/result types for:

- Core inference (`CoreInferenceEngine`, `CoreInferenceRequest`, `CandidateResult`, …)
- Precision extraction (`PrecisionExtractionEngine`, …)
- Operation executor (`OperationExecutor`, `OperationSnapshot`, …)
- Project store (`ProjectStore`, …)
- Provider descriptors / runtime config

### `nova_layer.object_workflow.plugin_sdk`

Includes (non-exhaustive relative to `__all__`):

- `PluginManager`, `PluginManifest`, `PluginRegistrationContext`, `PluginInfo`
- Package types: `PluginPackageManager`, `validate_plugin_package`, `build_nova_plugin_package`, …
- Constants: `SDK_VERSION`, `SUPPORTED_SDK_VERSIONS`, `PACKAGE_EXTENSION`, …

### `nova_layer.object_workflow.automation`

- `AutomationService`, `AutomationSession`
- `AutomationCommandRegistry`, `BUILTIN_COMMANDS`
- `AutomationEvent`, `AutomationEventBus`
- `AutomationOperation`, `AutomationResult`, permissions / status types

Builtin command names currently registered in Core:

`open_project`, `load_image`, `create_artist_intent`, `generate_candidates`, `select_candidate`, `confirm_candidate`, `generate_extraction`, `export_layer`, `save_project`, `close_project`, `batch_execute`

Full public API documentation (Approved):

- `05_Documents/API/00_PUBLIC_API_OVERVIEW.md`
- `05_Documents/API/01_PLUGIN_SDK_REFERENCE.md`
- `05_Documents/API/02_AUTOMATION_COMMAND_REFERENCE.md`
- `05_Documents/API/03_EVENT_REFERENCE.md`
- `05_Documents/API/04_SCHEMA_REFERENCE.md`

### `nova_layer.object_workflow.runtime`

Runtime cache types (`RuntimeCacheBundle`, typed caches, `PerformanceMonitor`, …) — application/runtime ownership, not Domain persistence.

### `nova_layer.object_workflow.adapters`

Factory/registry helpers exported for Core wiring (e.g. inference engine creation). Prefer ports for extension contracts; use adapters when Core composition requires them.

---

# 6. Persistence Locations (Conceptual)

| Data | Owner | On-disk form (implemented) |
|---|---|---|
| Object Workflow Project | Domain + `JsonProjectStore` | Project package; Schema **2.0**; atomic replace |
| Workspace | `WorkspaceManager` | `workspace.json` (temp + fsync + `os.replace`; `.bak` best-effort) |
| Installed plugins | Plugin package manager + workspace records | Local install root (see env constants in plugin SDK) |
| Temp operation artifacts | `ObjectWorkflowService` temp workspace | Ephemeral directory removed on `shutdown()` |

Workspace must not store Project schema payloads, runtime caches, or live GPU sessions.

---

# 7. Tests Layout

```text
02_Source/tests/
├── test_object_workflow_*.py   # OW feature / regression suites
├── test_rc_sprint_01.py        # RC Sprint 1 quality gates
├── test_rc_sprint_02.py        # RC Sprint 2 quality gates
├── test_*                      # Phase 1 and shared suites
└── ui/                         # Qt UI tests (CI-ignored)
```

CI offline filter:

```text
-m "not real_model and not real_host" --ignore=tests/ui
```

---

# 8. Documentation Layout (`05_Documents/`)

Defined by `05_Documents/00_DOCUMENTATION_ARCHITECTURE.md`:

```text
05_Documents/
├── 00_DOCUMENTATION_ARCHITECTURE.md
├── User/
├── Developer/          # this guide lives here
├── API/
├── Architecture/
└── Release/
    ├── VERSIONING_POLICY.md
    ├── RELEASE_PROCESS.md
    └── v1.0/             # versioned release docs
```

---

# 9. Related Specs (Do Not Copy)

| Topic | Spec path |
|---|---|
| Architecture (sole reference) | `00_Project/01_Implementation/ARCHITECTURE.md` |
| Architecture decisions (ADRs) | `00_Project/01_Implementation/07_ARCHITECTURE_DECISIONS.md` |
| Domain model | `00_Project/01_Implementation/02_DOMAIN_MODEL_SPEC.md` |
| Object lifecycle | `00_Project/01_Implementation/01_OBJECT_LIFECYCLE_SPEC.md` |
| Engine/port contracts | `00_Project/01_Implementation/03_ENGINE_INTERFACE_SPEC.md` |
| Product features | `00_Project/00_Philosophy/` |

---

# 10. Explicit Non-Goals for This Document

- Does not redefine Domain rules or Schema fields
- Does not claim GPU/host/UI verification
- Does not invent public HTTP/RPC surfaces (Automation is in-process)
- Does not treat `08_Release/` as a documentation tree
