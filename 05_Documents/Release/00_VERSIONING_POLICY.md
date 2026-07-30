# Versioning Policy

## Status

Approved

## Audience

Release Engineer, Maintainer, Developer, Plugin Author, Integrator

## Authority

**Official versioning and compatibility policy** for NOVA Layer Release documentation.

Architectural authority:

- `00_Project/01_Implementation/ARCHITECTURE.md`

Public version surfaces (field catalogs and validators — do not duplicate here):

- `05_Documents/API/00_PUBLIC_API_OVERVIEW.md` (§ Version Compatibility)
- `05_Documents/API/01_PLUGIN_SDK_REFERENCE.md`
- `05_Documents/API/04_SCHEMA_REFERENCE.md`
- `05_Documents/API/02_AUTOMATION_COMMAND_REFERENCE.md`
- `05_Documents/API/03_EVENT_REFERENCE.md`

Implementation constants (source of current values):

- `02_Source/pyproject.toml` — distribution package version
- `nova_layer.object_workflow.plugin_sdk` — `SDK_VERSION`, `SUPPORTED_SDK_VERSIONS`
- `nova_layer.object_workflow.plugin_sdk.package` — `PACKAGE_FORMAT_VERSION`, `SUPPORTED_PACKAGE_FORMATS`
- `nova_layer.object_workflow.domain` — Project `schema_version`
- `nova_layer.object_workflow.domain.validation` — `INTENT_SCHEMA`

This document does **not** invent SemVer ranges for Schema/SDK/package-format strings, migration tools, or remote compatibility negotiation. Those are not implemented.

---

# 1. Purpose

Define every **public version identifier**, how they relate, what Core guarantees today, what counts as a breaking change, and how Release docs should talk about stages — so Release Notes, Support Matrix, Migration Guide, and checklists stay consistent.

---

# 2. Scope

**In scope**

- Distribution package version (`nova-layer`)  
- Object Workflow Project Schema version  
- Intent instruction schema id  
- Plugin SDK version  
- Plugin package format version  
- Compatibility allowlists as implemented  
- Product release documentation stages under `05_Documents/Release/`  

**Out of scope**

- Phase 1 Smart Layer Schema **1.0** versioning (separate bounded context)  
- Third-party model artifact versioning  
- Host application (Photoshop, etc.) version matrices (optional / unverified lanes)  
- Invented multi-version loaders or Schema 1.0 → 2.0 migrators  

---

# 3. Version Types

Public identifiers are **independent**. Bumping one does not automatically bump another.

| Identifier | Where declared | Current implemented value | Role |
|---|---|---|---|
| Distribution package | `pyproject.toml` → `[project].version` | `0.1.5.dev0` (as of this policy write; always re-read source) | Installable `nova-layer` wheel/sdist identity |
| Product milestone (docs) | Release folder / ARCHITECTURE status | **v1.0 RC** (documentation / architecture status) | Human release train label — **not** the same string as `pyproject` version |
| Project Schema | `Project.schema_version` | `"2.0"` only | Object Workflow project package document version |
| Intent schema | `INTENT_SCHEMA` | `"nova.intent.guidance.v1"` | ArtistIntent instruction schema name |
| Plugin SDK | `SDK_VERSION` / `SUPPORTED_SDK_VERSIONS` | `"1.0"` / `{"1.0"}` | Plugin `manifest.json` `sdk_version` contract |
| Plugin package format | `PACKAGE_FORMAT_VERSION` / `SUPPORTED_PACKAGE_FORMATS` | `"1.0"` / `{"1.0"}` | `package.json` `package_format` |
| Plugin / package content versions | Manifest `version` fields | Author-defined strings | Plugin identity/version; **not** Core SDK version |
| Provider versions | Provider descriptors | Author-defined strings | Runtime provider metadata; not a Core schema version |

**Rules of interpretation**

1. Schema / SDK / package-format values are **exact string membership** checks against allowlists or literals — not SemVer range negotiation.  
2. Distribution version **may** use SemVer-like forms (including `.dev0` pre-releases) for packaging; that does **not** imply Schema or SDK SemVer compatibility algorithms.  
3. Documentation milestone **v1.0** / **v1.0 RC** labels the Release doc set and architecture status; integrators must still read `pyproject.toml` for the installed package version.

---

# 4. Compatibility Rules

### 4.1 What Core guarantees (implemented)

| Surface | Compatibility rule |
|---|---|
| Project Schema | Load accepts only `schema_version == "2.0"`. Other values → unsupported schema error. |
| Intent schema | Application validation accepts only `nova.intent.guidance.v1`. |
| Plugin SDK | Manifest `sdk_version` must be ∈ `SUPPORTED_SDK_VERSIONS`. |
| Package format | `package_format` must be ∈ `SUPPORTED_PACKAGE_FORMATS`. |
| Package ↔ plugin alignment | `plugin_id`, `version`, and `sdk_version` must match across `package.json` and `manifest.json` (see Schema / Plugin SDK references). |
| Automation builtins | Builtin command names must not be overridden by plugins; plugin commands are namespaced. |
| Transports | Automation and events remain **in-process** for Core — no wire-protocol version. |

### 4.2 Additive vs replaceable

| Change | Compatibility impact (policy) |
|---|---|
| Add a new value to `SUPPORTED_SDK_VERSIONS` / `SUPPORTED_PACKAGE_FORMATS` while keeping old values | **Additive** for newly supported plugins/packages |
| Keep Project Schema `"2.0"` field additions that older 2.0 docs omit, if loaders still accept prior 2.0 documents | **Compatible within Schema 2.0** only when loaders remain backward-tolerant (e.g. in-memory generation history back-fill — see Schema Reference) |
| Remove a value from an allowlist, or change the Project Schema literal | **Breaking** (see §5) |

### 4.3 Explicit non-guarantees

Core does **not** currently provide:

- Schema **1.0 → 2.0** project migration  
- Cross-major Plugin SDK migration tools  
- Soft compatibility with unknown `sdk_version` / `package_format` / `schema_version` strings  
- Networked API version headers  
- Guaranteed forward compatibility for unknown Project Schema keys (`extra="forbid"` on Domain models)  

Always re-read `SUPPORTED_*` and Literals in source when asserting exact sets.

---

# 5. Breaking Changes

A change is **breaking** for a given public surface if existing conforming artifacts or callers fail under the new Core without modification.

### 5.1 Breaking (by surface)

| Surface | Breaking examples |
|---|---|
| Project Schema | Change required `schema_version`; remove/rename required fields; reject documents previously loadable as 2.0 |
| Intent schema | Change `INTENT_SCHEMA` id without accepting the prior id |
| Plugin SDK | Remove `"1.0"` from `SUPPORTED_SDK_VERSIONS` without a documented replacement path; change entrypoint/`register` contract incompatibly |
| Package format | Remove `"1.0"` from `SUPPORTED_PACKAGE_FORMATS`; change required `package.json` fields incompatibly |
| Automation | Rename/remove builtin commands; change required permissions so previous sessions fail; change public result/event contracts incompatibly |
| Distribution | Remove public package exports that Release/API docs list as public |

### 5.2 Non-breaking (typical)

- New optional Project fields that remain absent-tolerant on load  
- New plugin capability strings (unknown capabilities already allowed)  
- New namespaced plugin Automation commands  
- New optional Automation params with defaults  
- Distribution patch/minor bumps that do not change the above contracts  

### 5.3 Documentation requirement

Breaking changes **must** be called out in the versioned Release Notes and, when applicable, Migration Guide for that product milestone. Do not silently narrow allowlists.

---

# 6. Deprecation Policy

**Current implementation reality:** unsupported versions are **hard-rejected**. There is **no** implemented deprecation window, warning-only compatibility mode, or dual-schema loader for Object Workflow.

Therefore this policy defines:

| Term | Meaning in NOVA Layer today |
|---|---|
| Unsupported | Rejected at validation/load (e.g. wrong `schema_version`, SDK, or package format) |
| Deprecated (docs-only) | May be announced in Release Notes **before** a future Core removes or replaces a surface — announcement alone does not keep old versions loading |
| Removed | No longer in allowlists / no longer exported |

**Rules for future Core changes**

1. Prefer **additive** allowlist growth over silent removal.  
2. If a public string version must be retired, Release docs for that milestone must state: last supporting distribution version, rejection behaviour, and whether any migrator exists (**none** for Schema 1.0 → 2.0 today).  
3. Do not document a deprecation grace period unless and until Core implements one.

---

# 7. Release Stages

Release documentation uses product milestones; packaging uses `pyproject` versions.

| Stage (docs) | Meaning |
|---|---|
| **Development / `.devN`** | Distribution version may carry a local/dev suffix (e.g. `.dev0`). Not a shipped GA claim. |
| **RC (Release Candidate)** | Architecture/docs status such as **v1.0 RC**: feature-complete intent for the milestone with accepted risks / unverified lanes labelled in Known Limitations / Support Matrix. |
| **vX.Y Release docs** | Versioned folder `05_Documents/Release/vX.Y/` — notes, matrix, checklists for that milestone. |
| **GA / final** | Only claim when Release checklist / go-live docs for that milestone are completed and distribution version is cut accordingly. |

**Mapping rule:** A docs folder named `v1.0/` describes the **v1.0 product milestone**. The installed `nova-layer` version string may still be a pre-1.0 packaging version until maintainers intentionally align them. Never assume `pyproject` `1.0.0` exists solely because Release docs say v1.0 RC.

Optional verification lanes (`real_model`, `real_host`, desktop UI smoke) are **not** version identifiers; they are test/support labels (see Developer Guide / Support Matrix when filled).

---

# 8. Version Matrix

Re-verify against source at release time. Snapshot at policy approval:

| Surface | Value | Gate |
|---|---|---|
| Distribution (`nova-layer`) | See `02_Source/pyproject.toml` | Packaging / install identity |
| Docs milestone | v1.0 RC (ARCHITECTURE / Release tree) | Release documentation set |
| Project `schema_version` | `"2.0"` | `JsonProjectStore` / Domain Literal |
| Intent schema | `nova.intent.guidance.v1` | `validate_intent_instruction` |
| `SDK_VERSION` | `"1.0"` | Plugin manifest |
| `SUPPORTED_SDK_VERSIONS` | `{"1.0"}` | Plugin load / package compatibility |
| `PACKAGE_FORMAT_VERSION` | `"1.0"` | `package.json` |
| `SUPPORTED_PACKAGE_FORMATS` | `{"1.0"}` | Package validation |
| Automation transport | In-process only | ARCHITECTURE §10 |
| Schema 1.0 → 2.0 migrator | **Not provided** | Unsupported |

Detail for fields and validation errors: Schema Reference and Plugin SDK Reference.

---

# 9. Related Documents

| Document | Role |
|---|---|
| `05_Documents/Release/RELEASE_PROCESS.md` | How releases are cut (process) |
| `05_Documents/Release/v1.0/*` | Milestone-specific release artifacts in docs form |
| `05_Documents/API/00_PUBLIC_API_OVERVIEW.md` | Public API + compatibility summary |
| `05_Documents/API/04_SCHEMA_REFERENCE.md` | Schema/SDK/package field authority |
| `05_Documents/API/01_PLUGIN_SDK_REFERENCE.md` | SDK/package contracts |
| `05_Documents/API/02_AUTOMATION_COMMAND_REFERENCE.md` | Command surface stability notes |
| `05_Documents/API/03_EVENT_REFERENCE.md` | Event surface (no separate event schema version) |
| `00_Project/01_Implementation/ARCHITECTURE.md` | Product architecture authority |
| `05_Documents/00_DOCUMENTATION_ARCHITECTURE.md` | Docs ownership rules |

Canonical path for this policy in the Release tree: **`05_Documents/Release/00_VERSIONING_POLICY.md`**.  
`VERSIONING_POLICY.md` is a pointer for older links.

---

## Explicit Non-Claims

- No SemVer compatibility algorithm for Schema/SDK/package-format strings  
- No promise that distribution major version equals Schema or SDK major  
- No implemented deprecation soft-load period  
- No Schema 1.0 Object Workflow support under this policy  

## Documentation Gaps

- Distribution version and docs milestone **v1.0** are intentionally distinct today (`0.1.5.dev0` vs v1.0 RC docs); align them deliberately at GA.  
- No machine-readable “compatibility manifest” beyond source constants.  
- Event and Automation surfaces have no separate numeric schema version field on the wire (in-process only).  
