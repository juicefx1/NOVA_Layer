# NOVA Layer Developer Guide

## Status

Approved

## Audience

Developer, Maintainer

## Authority

This document orients contributors. It does not redefine product behaviour.

Authoritative sources:

- `00_Project/01_Implementation/ARCHITECTURE.md` (sole architecture reference)
- `00_Project/01_Implementation/07_ARCHITECTURE_DECISIONS.md` (decision rationale)
- `05_Documents/00_DOCUMENTATION_ARCHITECTURE.md`
- Implementation under `02_Source/src/nova_layer/`

## Scope

How to set up a development environment, navigate the repository, run the offline test lane, and find the correct deeper guide for Object Workflow work.

---

# 1. What You Are Working On

NOVA Layer contains two related code areas in one package tree:

| Area | Package root | Schema | Role |
|---|---|---|---|
| Object Workflow (v1.0 RC focus) | `nova_layer.object_workflow` | **2.0** | Artist intent → candidates → confirmation → extraction → host/export |
| Phase 1 Smart Layer | `nova_layer.domain`, `nova_layer.app`, `nova_layer.ui` (non-OW modules) | **1.0** | Earlier vertical slice; keep separate unless a task explicitly targets it |

Do not merge schemas. Do not introduce a second Object Workflow Domain or a second Workspace architecture.

Canonical Object Workflow architecture: `00_Project/01_Implementation/ARCHITECTURE.md`.

Repository layout details: `05_Documents/Developer/01_PROJECT_STRUCTURE.md`.

---

# 2. Prerequisites

Verified for the offline development lane:

- Python **3.12** (see `02_Source/pyproject.toml`)
- Working directory for package install and tests: `02_Source/`
- Optional desktop extras for the Qt app (`PySide6`) via the `desktop` extra

Unverified in documentation (do not assume):

- GPU / MPS / CUDA availability
- Commercial host applications for `real_host` tests
- That every machine can run `tests/ui/` headlessly

---

# 3. Environment Setup

From the repository root:

```bash
cd 02_Source
python3.12 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
python -m pip install --upgrade pip
python -m pip install -e ".[desktop,dev]"
```

Package name: `nova-layer` (import name: `nova_layer`).

Current package version in tree: see `[project].version` in `02_Source/pyproject.toml` (development versions may use a `.dev0` suffix).

---

# 4. Running the Application

Desktop entrypoint:

```bash
cd 02_Source
source .venv/bin/activate
python -m nova_layer
```

This launches `MainWindow` (`nova_layer.ui.main_window`). Object Workflow is available from the welcome flow via `ObjectWorkflowWindow` / `ObjectWorkflowController`.

Do not treat Phase 1 Smart Layer UI flows as the Object Workflow product guide; use User docs under `05_Documents/User/` once written.

---

# 5. Offline Checks (Required Local Gate)

Mirror CI (`.github/workflows/ci.yml`):

```bash
cd 02_Source
source .venv/bin/activate
python -m ruff check src tests
python -m pytest -m "not real_model and not real_host" --ignore=tests/ui --tb=short
```

Notes:

- Default `pytest` `addopts` already exclude `real_model` and `real_host`.
- UI tests under `tests/ui/` require Qt/`pytest-qt` and are **excluded from CI**.
- Optional markers (not part of the default gate):
  - `real_model` — local SAM / model smoke (needs artefacts)
  - `real_host` — commercial host bridge smoke (needs local host)

---

# 6. Where Code Lives (Quick Map)

| Concern | Location |
|---|---|
| Object Workflow Domain | `02_Source/src/nova_layer/object_workflow/domain/` |
| Ports (Protocols) | `.../object_workflow/ports/` |
| Adapters / providers | `.../object_workflow/adapters/` |
| Application services | `.../object_workflow/application/` (`ObjectWorkflowService`, `WorkspaceManager`, `BatchManager`) |
| Plugin SDK + `.nova-plugin` | `.../object_workflow/plugin_sdk/` |
| Automation API | `.../object_workflow/automation/` |
| Runtime caches / metrics | `.../object_workflow/runtime/` |
| Qt presentation (OW + Phase 1) | `02_Source/src/nova_layer/ui/`, `.../app/` |
| Offline tests | `02_Source/tests/` |
| Authoritative architecture | `00_Project/01_Implementation/ARCHITECTURE.md` |
| Human docs (this tree) | `05_Documents/` |
| Build artifacts only | `08_Release/` |

Public package entry surfaces (indexes, not full references):

- `nova_layer.object_workflow` — `ObjectWorkflowService`, `Project`, `WorkflowState`, `BinaryMask`
- `nova_layer.object_workflow.plugin_sdk` — `PluginManager`, package manager, manifests, errors
- `nova_layer.object_workflow.automation` — `AutomationService`, commands, events, session
- `nova_layer.object_workflow.ports` — engine / store / executor Protocols

Public API references (Approved):

- `05_Documents/API/00_PUBLIC_API_OVERVIEW.md`
- `05_Documents/API/01_PLUGIN_SDK_REFERENCE.md`
- `05_Documents/API/02_AUTOMATION_COMMAND_REFERENCE.md`
- `05_Documents/API/03_EVENT_REFERENCE.md`
- `05_Documents/API/04_SCHEMA_REFERENCE.md`

---

# 7. Architectural Rules (Non-Negotiable)

| Principle | Summary |
|---|---|
| Dependency direction | Presentation → Application → Domain → Ports → Adapters |
| Domain purity | No Qt, filesystem I/O, or AI frameworks in Domain |
| Single Workspace | One `WorkspaceManager` (workspace ≠ Project schema) |
| Executor required | Generate / extract go through `OperationExecutor` |
| Schema split | Object Workflow **2.0**; Phase 1 **1.0** remains separate |
| Local plugins only | `.nova-plugin` packages; no remote marketplace |
| In-process automation | No HTTP/RPC transport in Core |

Full rules: `00_Project/01_Implementation/ARCHITECTURE.md`.  
Decision index: `00_Project/01_Implementation/07_ARCHITECTURE_DECISIONS.md`.  
Application/Runtime narrative: `05_Documents/Developer/04_APPLICATION_AND_RUNTIME.md`.  
Architecture Guide placeholder: `05_Documents/Developer/02_ARCHITECTURE_GUIDE.md`.

---

# 8. Typical Object Workflow Change Paths

| If you change… | Start here | Also update / read |
|---|---|---|
| Domain entities / confirmation rules | `object_workflow/domain/` | `02_DOMAIN_MODEL_SPEC.md`, `01_OBJECT_LIFECYCLE_SPEC.md` |
| Use-case orchestration | `object_workflow/application/service.py` | ports + offline tests |
| Provider behaviour | `object_workflow/adapters/` | port Protocols; keep Domain clean |
| Workspace persistence | `application/workspace_manager.py` | never store Project schema payloads in workspace |
| Batch defaults / confirmation | `application/batch_manager.py` | interactive remains default; automatic needs explicit opt-in |
| Plugins | `plugin_sdk/` | Feature 12 philosophy + package validation tests |
| Automation commands | `automation/` | must map to existing service actions |

Shutdown ownership (controller coordinates cancel → workspace save → plugins → caches → service/temp/GPU cleanup) is defined in `ARCHITECTURE.md`.

---

# 9. Documentation Tree

Documentation rules and folder ownership: `05_Documents/00_DOCUMENTATION_ARCHITECTURE.md`.

| Folder | Use for |
|---|---|
| `User/` | End-user guides |
| `Developer/` | Contributor guides (this file) |
| `API/` | Public surface indexes |
| `Architecture/` | Architecture book / lifecycle narrative (links to specs) |
| `Release/` | Versioned release docs and process |

Do not put prose documentation into `08_Release/`.

---

# 10. Related Developer Documents

| Document | Status | Topic |
|---|---|---|
| `01_PROJECT_STRUCTURE.md` | Approved | Repository and package layout |
| `02_ARCHITECTURE_GUIDE.md` | Stub (placeholder) | Layer guide linking to `ARCHITECTURE.md` |
| `03_DOMAIN_MODEL.md` | Stub (placeholder) | Index to Domain specs |
| `04_APPLICATION_AND_RUNTIME.md` | Approved | Service, executor, caches |
| `05_WORKSPACE_AND_PERSISTENCE.md` | Stub (placeholder) | Workspace vs Project persistence |
| `06_PLUGIN_SDK_GUIDE.md` | Approved | Plugin authoring overview |
| `07_AUTOMATION_GUIDE.md` | Approved | In-process automation |
| `08_BATCH_ARCHITECTURE.md` | Stub (placeholder) | Batch manager behaviour |
| `09_TESTING_GUIDE.md` | Stub (placeholder) | Markers, CI lanes, stress gaps |
| `10_BUILD_GUIDE.md` | Stub (placeholder) | Wheels / packaging |
| `11_CONTRIBUTING.md` | Stub (placeholder) | Contribution process |

Also see Approved User guides: `05_Documents/User/00_GETTING_STARTED.md`, `05_Documents/User/01_USER_GUIDE.md`.

---

# 11. Known Documentation Gaps

Labelled so contributors do not invent behaviour:

- GPU / real-model verification — optional test lane; not default CI
- Commercial host verification — optional `real_host` lane
- Desktop UI automated smoke — present under `tests/ui/`, not run in CI
- Large-batch / large-image stress limits — not documented as hard product limits
- Object Workflow Schema migration from non-`2.0` — hard reject in store; no supported migration path documented as implemented
