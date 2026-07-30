# v1.0 Release Notes

## Status

Approved

## Audience

End User, Integrator, Developer, Release Engineer, Maintainer

## Authority

Official release notes for the **NOVA Layer v1.0 Release Candidate** product milestone.

Governing documents:

- `05_Documents/Release/00_VERSIONING_POLICY.md`
- `05_Documents/Release/01_RELEASE_PROCESS.md`
- `00_Project/01_Implementation/ARCHITECTURE.md`

Compatibility and limitations (do not duplicate here):

- `05_Documents/Release/v1.0/02_KNOWN_LIMITATIONS.md`
- `05_Documents/Release/v1.0/03_SUPPORT_MATRIX.md`
- `05_Documents/API/00_PUBLIC_API_OVERVIEW.md`

Artifacts described below are **existing** sealed candidates under `08_Release/` and reports produced by implemented CLI tools. No invented seals or publish events.

---

# 1. Release Overview

| Field | Value |
|---|---|
| Product milestone (docs) | **v1.0 RC** |
| Architecture status | Authoritative for NOVA Layer **v1.0 RC** (`ARCHITECTURE.md`) |
| Latest sealed distribution candidate on disk | **`nova-layer` `0.1.4`** → `08_Release/nova-layer-0.1.4-fc1b1af9ad04/` |
| Seal date (manifest `created_at`) | `2026-07-23T16:16:31Z` |
| Wheel SHA-256 (prefix / full) | `fc1b1af9ad04…` / see `release_manifest.json` |
| Current tree packaging version | See `02_Source/pyproject.toml` (may be a later `.devN` than the sealed wheel) |

**What “v1.0 RC” means here**

- A **product milestone** for Object Workflow (Schema **2.0**) as defined by architecture and Approved API/User docs.  
- A **Release Candidate** stage in Release Process terms: quality gates + optional sealed wheel under `08_Release/`.  

**What it does not mean**

- Distribution version is not necessarily `1.0.0` (Versioning Policy: docs milestone ≠ `pyproject` version until deliberately aligned).  
- This document does not claim PyPI publish, GitHub Release upload, or automated CD (none in-repo).  

**Primary product surface for this milestone:** Object Workflow desktop + in-process Plugin SDK / Automation / Schema 2.0. Phase 1 Smart Layer (Schema **1.0**) remains a **separate** bounded context.

---

# 2. Release Highlights

1. **Object Workflow (Schema 2.0)** — interactive path from source image through explicit confirmation to extraction and export.  
2. **Explicit artist confirmation** — ConfirmedObject requires confirmation; desktop interactive confirmation remains the product default posture.  
3. **Additive Plugin SDK** — local `.nova-plugin` packages; isolated load failures.  
4. **In-process Automation** — command/session/event APIs equivalent to UI actions; no HTTP/RPC Core transport.  
5. **Workspace independent of Projects** — preferences/recent projects vs `.nova` project packages.  
6. **Batch over the same workflow paths** — queue reuse of Application confirmation/extraction; automatic confirmation is opt-in.  
7. **Manual seal toolchain** — `nova-release-verify` / `nova-install-smoke` / `nova-release-candidate` / `nova-release-audit` for content-addressed candidates in `08_Release/`.  

---

# 3. Included Features

Implemented capabilities in scope for the v1.0 RC Object Workflow milestone (summary only; details in User/API docs):

### Desktop Object Workflow

- Create / load / save Object Workflow projects (`.nova` packages)  
- Load PNG/JPEG sources; Artist Intent (points / box) with Apply  
- Generate candidates; select / compare; Confirm; Extract; Export PNG  
- Delivery helpers (reveal / copy path / URI / host send when adapters available)  
- Workspace helpers (recent projects, reopen, restore layout, reset workspace)  
- Batch section (add images, start/cancel/retry; automatic confirmation checkbox is opt-in)  

### Application / Domain

- `ObjectWorkflowService` orchestration with OperationExecutor for generate/extract  
- Schema **2.0** Project persistence (`JsonProjectStore`)  
- Intent schema `nova.intent.guidance.v1`  
- `WorkspaceManager`, `BatchManager`  

### Public extension surfaces

| Surface | Summary |
|---|---|
| Plugin SDK | Manifests, registration context, local package validate/build/install |
| Automation | Sessions, permissions, builtin commands, namespaced plugin commands, in-process events |
| Ports | Inference / extraction / store / executor / host contracts |
| Schemas | Project Schema 2.0; plugin `manifest.json`; package `package.json` format `1.0`; SDK `1.0` |

Full catalogs: Public API Overview and the API references.

### Explicitly not claimed as new remote/platform features

- Remote plugin marketplace  
- Networked Automation  
- Schema **1.0 → 2.0** project migrator  

---

# 4. Verification Summary

### 4.1 Sealed candidate `0.1.4` (artifact evidence)

Directory: `08_Release/nova-layer-0.1.4-fc1b1af9ad04/`

| Check | Tool / artifact | Result (as recorded) |
|---|---|---|
| Wheel structure / console scripts / no embedded weights | `nova_layer-0.1.4-wheel.json` (`nova-release-verify`) | `valid: true` |
| Temp install + module `--help` + offscreen GUI probe | `nova_layer-0.1.4-install-smoke.json` (`nova-install-smoke`) | `valid: true`, `gui_startup_passed: true` |
| Acceptance suite embedded in seal | `phase1_acceptance_latest.json` | **9 / 9** passed |
| Seal manifest | `release_manifest.json` | `format_version: 3`, version `0.1.4`, acceptance 9/9 |

**Acceptance suite identity (important):** the sealed report is titled **“NOVA Layer Phase 1 Acceptance”** (`P1-AT-001` … `P1-AT-009`). It is the report format required by the current seal tool. It must **not** be read as a dedicated Object Workflow Schema 2.0 acceptance suite name.

### 4.2 Ongoing offline quality gate (CI / local)

As defined in Release Process / Developer Guide / `.github/workflows/ci.yml`:

- `ruff check src tests`  
- `pytest -m "not real_model and not real_host" --ignore=tests/ui`  

CI does **not** build or seal wheels.

### 4.3 Not part of the sealed `0.1.4` claim

Label these in Known Limitations / Support Matrix rather than implying seal coverage:

- Optional `real_model` / `real_host` pytest markers  
- Full `tests/ui/` suite as a CI gate  
- GPU / commercial host production verification  
- A separately sealed Object Workflow–named acceptance report  

Re-audit any copied seal directory with `nova-release-audit` before redistribution (Release Process).

---

# 5. Compatibility Summary

| Identifier | v1.0 RC expectation (see Versioning Policy) |
|---|---|
| Docs milestone | v1.0 RC |
| Project Schema | `"2.0"` only |
| Intent schema | `nova.intent.guidance.v1` |
| Plugin SDK | `"1.0"` ∈ `SUPPORTED_SDK_VERSIONS` |
| Package format | `"1.0"` ∈ `SUPPORTED_PACKAGE_FORMATS` |
| Automation transport | In-process only |
| Distribution package | Sealed example `0.1.4`; tree may differ — read `pyproject.toml` |

Unsupported / non-guarantees (including Schema 1.0 → 2.0 migration): **Versioning Policy** and **Known Limitations**.

Platform and optional-lane detail: **Support Matrix** (when completed; until then treat GPU/host/UI-beyond-smoke as unverified unless labelled otherwise).

---

# 6. Upgrade Notes

1. **Object Workflow vs Phase 1** — Schema **2.0** Projects are not Schema **1.0** Smart Layer projects. There is **no** Schema 1.0 → 2.0 migrator in Core.  
2. **Install from a sealed wheel** — Use the wheel inside the sealed `08_Release/…` directory after audit; do not assume the live tree’s `.devN` version matches that seal.  
3. **Plugins** — Must declare supported `sdk_version` / package format; local install only.  
4. **Automation callers** — Builtin command and event contracts: Command / Event references. Desktop batch interactive default vs Automation `batch_execute` parameter defaults: Automation Guide + Command Reference.  
5. **Breaking-change policy** — Versioning Policy §5; this RC notes do not introduce a Schema/SDK allowlist removal.  

---

# 7. Related Documents

| Document | Role |
|---|---|
| `05_Documents/Release/00_VERSIONING_POLICY.md` | Version identifiers |
| `05_Documents/Release/01_RELEASE_PROCESS.md` | Seal / audit workflow |
| `05_Documents/Release/v1.0/02_KNOWN_LIMITATIONS.md` | Accepted risks / unverified lanes |
| `05_Documents/Release/v1.0/03_SUPPORT_MATRIX.md` | Environments |
| `05_Documents/Release/v1.0/04_TEST_REPORT.md` | Deeper test citation (when filled) |
| `05_Documents/User/00_GETTING_STARTED.md` | First-run OW path |
| `05_Documents/User/01_USER_GUIDE.md` | Everyday OW usage |
| `05_Documents/API/00_PUBLIC_API_OVERVIEW.md` | Public API index |
| `00_Project/01_Implementation/ARCHITECTURE.md` | Architecture authority |
| `08_Release/nova-layer-0.1.4-fc1b1af9ad04/` | Latest sealed candidate artifacts on disk |

---

## Documentation Gaps

- Known Limitations and Support Matrix for v1.0 are still placeholders — readers must not invent GPU/host GA claims.  
- No sealed distribution yet whose `pyproject` version equals `1.0.0`.  
- Seal acceptance input still uses Phase 1 suite naming while the product milestone is Object Workflow v1.0 RC.  
- Post-`0.1.4` tree changes (e.g. current `.devN`) are not automatically a new sealed candidate until Release Process is re-run.  
