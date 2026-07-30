# v1.0 Compatibility

## Status

Approved

## Audience

End User, Integrator, Developer, Plugin Author, Release Engineer, Maintainer

## Authority

**Official compatibility / support matrix** for the NOVA Layer **v1.0 RC** product milestone.

Compatibility **rules and version semantics** are governed by:

- `05_Documents/Release/00_VERSIONING_POLICY.md`

Do **not** restate allowlist algorithms here — link the Versioning Policy. This document states **what is Supported, Unsupported, Not Verified, or Deployment Dependent** for v1.0 RC based on verified implementation and release evidence.

Related:

- `05_Documents/Release/v1.0/01_RELEASE_NOTES.md`
- `05_Documents/Release/v1.0/02_KNOWN_LIMITATIONS.md`
- `05_Documents/Release/01_RELEASE_PROCESS.md`

`03_SUPPORT_MATRIX.md` is a pointer to this file for older listings.

---

# 1. Scope

| In scope | Out of scope |
|---|---|
| Object Workflow Schema **2.0** product surfaces | Invented OS/GPU/host GA claims |
| Public version identifiers (packaging, schema, SDK, package format, intent) | Future compatibility promises |
| What CI and the latest sealed candidate actually exercised | Defect lists (see issue trackers, not this doc) |
| Deployment-dependent adapters/hosts/plugins | Phase 1 Schema **1.0** as an Object Workflow-supported format |

**Label legend**

| Label | Meaning |
|---|---|
| **Supported** | Contractually accepted by Core gates / declared package metadata for this milestone |
| **Unsupported** | Rejected or not provided by Core |
| **Not Verified** | Outside CI and/or sealed-candidate claim for this RC |
| **Deployment Dependent** | Works only when local adapters, models, hosts, or plugins are present and correctly configured |

---

# 2. Product Compatibility

### 2.1 Version surfaces (Supported values)

Exact membership / literals — see Versioning Policy for rules:

| Surface | Supported for Object Workflow v1.0 RC |
|---|---|
| Docs milestone | **v1.0 RC** |
| Project `schema_version` | `"2.0"` |
| Intent schema | `nova.intent.guidance.v1` |
| Plugin SDK `sdk_version` | `"1.0"` (∈ `SUPPORTED_SDK_VERSIONS`) |
| Plugin `package_format` | `"1.0"` (∈ `SUPPORTED_PACKAGE_FORMATS`) |
| Automation transport | **In-process only** |
| Distribution package name | `nova-layer` |
| Python (package metadata) | `>=3.12,<3.14` (`pyproject.toml`) |

### 2.2 Distribution candidates

| Item | Status |
|---|---|
| Latest sealed candidate on disk | **Supported as sealed artifact**: `nova-layer` **`0.1.4`** → `08_Release/nova-layer-0.1.4-fc1b1af9ad04/` (Release Notes) |
| Live tree `pyproject.toml` version | May be a later `.devN` — **Supported for development**; not automatically the same as the sealed wheel |
| Packaging version `1.0.0` | **Not** required for docs milestone v1.0 RC (Versioning Policy) |

### 2.3 Product surfaces

| Surface | Compatibility posture |
|---|---|
| Desktop Object Workflow (Schema 2.0 UI) | **Supported** as the v1.0 RC product path |
| Plugin SDK + local `.nova-plugin` | **Supported** (local trust model) |
| Automation API + events | **Supported** in-process |
| Batch via Application / desktop Batch section | **Supported**; confirmation mode rules per Known Limitations / Command Reference |
| Phase 1 Smart Layer Schema 1.0 | **Separate** bounded context — **not** Object Workflow Schema 2.0 compatible |

---

# 3. Unsupported Versions

| Input / expectation | Status |
|---|---|
| Object Workflow Project `schema_version` ≠ `"2.0"` (including Schema `"1.0"`) | **Unsupported** (hard reject) |
| Schema **1.0 → 2.0** automatic migration | **Unsupported** |
| Plugin `sdk_version` ∉ `SUPPORTED_SDK_VERSIONS` | **Unsupported** |
| `package_format` ∉ `SUPPORTED_PACKAGE_FORMATS` | **Unsupported** |
| Intent schema ≠ `nova.intent.guidance.v1` (Application validation) | **Unsupported** |
| Remote plugin marketplace / download pipeline | **Unsupported** |
| HTTP/REST/WebSocket/RPC Automation | **Unsupported** |
| Soft-load / deprecation grace for wrong version strings | **Unsupported** |
| Cross-major Plugin SDK migration tools | **Unsupported** |
| Overriding builtin Automation commands | **Unsupported** |
| Guaranteed forward-compat for unknown Project Schema keys | **Unsupported** (`extra="forbid"`) |

---

# 4. Platform Compatibility

Only rows with verification evidence are marked Supported. Everything else is Not Verified unless Deployment Dependent.

| Environment | Status | Evidence |
|---|---|---|
| Python **3.12** | **Supported** (CI + packaging range) | `.github/workflows/ci.yml` uses 3.12; `requires-python = ">=3.12,<3.14"` |
| Python 3.13 | **Supported** by package metadata only | In `requires-python` range; **Not Verified** as a dedicated CI job in-repo |
| Python &lt; 3.12 or ≥ 3.14 | **Unsupported** by package metadata | `pyproject.toml` |
| Linux (`ubuntu-latest` CI runner) | **Supported** for offline gate | CI `runs-on: ubuntu-latest` |
| macOS / Windows desktop | **Not Verified** as CI platforms | No matrix jobs in `ci.yml` |
| PySide6 desktop extra (`>=6.8,<7`) | **Supported** as declared dependency for desktop installs | `pyproject.toml` `[project.optional-dependencies] desktop` |
| Offscreen Qt GUI smoke in seal | **Supported** for sealed `0.1.4` install-smoke | `gui_startup_passed: true` in sealed report |
| Full `tests/ui/` suite | **Not Verified** as CI | Ignored in CI |
| CUDA / MPS / GPU production inference | **Not Verified** | Optional `real_model` excluded from CI/seal claim |
| Commercial host applications | **Not Verified** / often **Deployment Dependent** | Optional `real_host`; host adapters vary |

Do **not** invent a multi-OS support claim beyond the above.

---

# 5. Runtime Compatibility

| Concern | Status | Notes |
|---|---|---|
| Offline unit/integration tests (default markers) | **Supported** verification lane | CI: `pytest -m "not real_model and not real_host" --ignore=tests/ui` |
| `real_model` marker | **Not Verified** in default CI/seal | Opt-in local |
| `real_host` marker | **Not Verified** in default CI/seal | Opt-in local |
| OperationExecutor generate/extract path | **Supported** contract | Must not bypass (ARCHITECTURE) |
| Runtime caches persisted into Project/Workspace | **Unsupported** | Session-scoped only |
| Core Inference / Precision Extraction provider choice | **Deployment Dependent** | Built-ins + discovered plugins; quality/device vary |
| Host **Send to Host** | **Deployment Dependent** | Requires available adapter/action |
| Local plugin load | **Deployment Dependent** | Manifest/SDK/format must match; trusted code |
| Automation without `BatchManager` for `batch_execute` | **Unsupported** for that command | Known Limitations |
| Event bus durability / remote delivery | **Unsupported** | Event Reference |

---

# 6. Documentation Compatibility

| Docs artifact | Status |
|---|---|
| Approved API / User / key Developer / Release policy+process+notes+limitations | **Supported** as documentation authority for this milestone |
| Docs milestone label **v1.0 RC** with packaging ≠ `1.0.0` | **Supported** reading (Versioning Policy) |
| Sealed acceptance titled Phase 1 (`P1-AT-*`) | **Supported** as seal input; **Not** an Object Workflow–branded suite name (Release Notes) |
| Claiming GA / PyPI publish from this folder alone | **Unsupported** | Release Process: publish out-of-band; GA only when checklist complete |
| Treating `03_SUPPORT_MATRIX.md` as a second matrix body | **Unsupported** | Pointer only — this file is authoritative |

---

# 7. Related Documents

| Document | Role |
|---|---|
| `05_Documents/Release/00_VERSIONING_POLICY.md` | Compatibility **rules** authority |
| `05_Documents/Release/01_RELEASE_PROCESS.md` | What CI/seal verify |
| `05_Documents/Release/v1.0/01_RELEASE_NOTES.md` | Sealed `0.1.4` evidence |
| `05_Documents/Release/v1.0/02_KNOWN_LIMITATIONS.md` | Intentional limits / Not Verified detail |
| `05_Documents/Release/v1.0/06_MIGRATION_GUIDE.md` | Migration non-support (when written) |
| `05_Documents/API/00_PUBLIC_API_OVERVIEW.md` | Public API surfaces |
| `05_Documents/API/04_SCHEMA_REFERENCE.md` | Schema field gates |
| `02_Source/pyproject.toml` | Packaging Python range / extras |
| `.github/workflows/ci.yml` | Automated platform evidence |

---

## Deployment-Dependent Checklist (operators)

Confirm locally before relying on these in production:

- [ ] Selected Core Inference provider/device available  
- [ ] Precision Extraction / matting backend available  
- [ ] Host adapter present if using **Send to Host**  
- [ ] Plugins’ `sdk_version` / `package_format` match allowlists  
- [ ] Sealed wheel SHA matches Release Notes if distributing from `08_Release/`  

## Documentation Gaps

- No dedicated CI matrix for macOS/Windows or Python 3.13.  
- Support claims for GPU/hosts remain **Not Verified**.  
- Migration Guide still placeholder for narrative restatement of Schema 1.0→2.0 non-support.  
