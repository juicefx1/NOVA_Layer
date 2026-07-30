# Schema Reference

## Status

Approved

## Audience

Developer, Integrator, Plugin Author

## Authority

Authoritative reference for **public data schemas** used by Object Workflow.

Architectural authority:

- `00_Project/01_Implementation/ARCHITECTURE.md` (Schema **2.0** Object Workflow vs Phase 1 Schema **1.0**)

Related API docs (do not duplicate command/event/SDK lifecycle material here):

- `05_Documents/API/00_PUBLIC_API_OVERVIEW.md`
- `05_Documents/API/01_PLUGIN_SDK_REFERENCE.md` (registration, packaging APIs)
- `05_Documents/API/02_AUTOMATION_COMMAND_REFERENCE.md`
- `05_Documents/API/03_EVENT_REFERENCE.md`

Domain model narrative authority (behaviour / invariants beyond JSON fields):

- `00_Project/01_Implementation/02_DOMAIN_MODEL_SPEC.md`

Implementation sources:

| Schema | Primary definitions / validators |
|---|---|
| Project Schema 2.0 | `object_workflow.domain.models.Project`, `adapters.json_project_store.JsonProjectStore`, `domain.validation` |
| Plugin Manifest | `plugin_sdk.manifest.PluginManifest`, `load_manifest` / `parse_manifest` |
| Package Manifest | `plugin_sdk.package.models.PluginPackageManifest`, `parse_package_manifest`, `validate_plugin_package` |

## Scope

Document **implemented** public schemas only: field catalogs, supported versions, and validation rules as coded. Do **not** invent migration paths or compatibility guarantees beyond what the validators enforce.

---

# 1. Introduction

Object Workflow persists and exchanges structured documents through three public schema families:

1. **Project Schema 2.0** — the Object Workflow `Project` aggregate serialized as package `manifest.json` (`.nova` package).  
2. **Plugin Manifest** — plugin directory / package `manifest.json` (`PluginManifest`).  
3. **Package Manifest** — Feature 12 packaging metadata `package.json` (`PluginPackageManifest`).

These version numbers are **independent**:

| Surface | Current supported value |
|---|---|
| Project `schema_version` | `"2.0"` only |
| Plugin SDK `sdk_version` | `"1.0"` only (`SUPPORTED_SDK_VERSIONS`) |
| Package `package_format` | `"1.0"` only (`SUPPORTED_PACKAGE_FORMATS`) |

Phase 1 Smart Layer Schema **1.0** is a **separate** bounded context and is **not** documented here as an Object Workflow public schema.

---

# 2. Audience

| Audience | Primary schemas |
|---|---|
| Developer | Project Schema 2.0 field contracts and store gates |
| Integrator | Project package layout; understanding load rejection codes |
| Plugin Author | Plugin Manifest + Package Manifest field contracts |

---

# 3. Schema Overview

| Schema | On-disk name | Parser / gate | Public types |
|---|---|---|---|
| Project Schema 2.0 | `.nova` package → `manifest.json` + `assets/` | `JsonProjectStore.load` then `Project.model_validate` | `Project` and nested Domain models |
| Plugin Manifest | `manifest.json` | `load_manifest` / `parse_manifest` | `PluginManifest` |
| Package Manifest | `package.json` (inside `.nova-plugin` or unpacked dir) | `parse_package_manifest` + `validate_plugin_package` | `PluginPackageManifest` |

**Field presence legend used below:**

| Mark | Meaning |
|---|---|
| **R** | Required for that document/entity (no usable default; validator rejects absence/empty) |
| **O** | Optional; default applied when absent |
| **C** | Conditional — nullable, omitted in some states, or validated only on specific code paths |

Unknown JSON keys on Project Domain models are **forbidden** (`extra="forbid"`). Plugin/package manifest parsers accept only documented keys they read; they do not formally forbid extras today (unrecognized keys are ignored).

---

# 4. Project Schema

## 4.1 Package layout

`JsonProjectStore` treats a project package as a directory containing:

| Path | Role |
|---|---|
| `manifest.json` | Serialized `Project` (`model_dump(mode="json", by_alias=True)`) |
| `assets/` | Relative asset files referenced by the manifest |
| `assets/source`, `assets/masks`, `assets/intent`, `assets/extractions` | Created on save |

Asset relative paths referenced by entities must satisfy `validate_relative_asset_path`:

- Must be non-empty and **not** absolute (`/` or `\` prefix)  
- No `.` / `..` path segments  
- Must start with `assets/`  

On load, every relative path collected from source/candidates/hypotheses/confirmed/extractions must exist as a file or load fails (`LOAD_FAILED` / missing asset).

## 4.2 Version gate

```text
schema_version must equal "2.0"
```

Any other value (including missing/`null`) → `ProjectStoreError("UNSUPPORTED_SCHEMA", ...)`.

There is **no** multi-version dispatch and **no** Schema 1.0 → 2.0 migrator in Object Workflow.

## 4.3 Top-level `Project`

Source: `domain/models.py` (`Project`).

| Field | Type / values | Presence | Notes |
|---|---|---|---|
| `id` | UUID | **O** (default new UUID) | |
| `schema_version` | `"2.0"` | **R** at load gate; default `"2.0"` on construct | Literal-pinned |
| `name` | string | **R** | |
| `created_at` | datetime | **O** (default UTC now) | |
| `updated_at` | datetime | **O** (default UTC now) | `touch()` updates |
| `workflow_state` | see enum | **O** (default `no_source`) | |
| `source_images` | list | **O** (default `[]`) | |
| `intents` | list | **O** | |
| `candidate_sets` | list | **O** | |
| `generation_records` | list | **O** | May be back-filled in memory on load (§8) |
| `hypotheses` | list | **O** | |
| `confirmations` | list | **O** | |
| `confirmed_objects` | list | **O** | |
| `extraction_results` | list | **O** | |
| `operations` | list | **O** | |
| `active_source_image_id` | UUID \| null | **O** | |
| `active_intent_id` | UUID \| null | **O** | |
| `active_candidate_set_id` | UUID \| null | **O** | |
| `active_generation_id` | UUID \| null | **O** | |
| `active_hypothesis_id` | UUID \| null | **O** | |
| `active_confirmation_id` | UUID \| null | **O** | |
| `active_confirmed_object_id` | UUID \| null | **O** | |
| `active_extraction_result_id` | UUID \| null | **O** | |

### `workflow_state` values

`no_source` · `source_ready` · `intent_provided` · `candidate_set_ready` · `hypothesis_ready` · `object_confirmed` · `extraction_ready`

## 4.4 Nested entities

### `SourceImage`

| Field | Presence | Constraints |
|---|---|---|
| `id`, `created_at` | **O** | defaults |
| `original_filename` | **R** | |
| `relative_asset_path` | **R** | store path rules |
| `media_type` | **R** | `"image/png"` \| `"image/jpeg"` |
| `width`, `height` | **R** | `> 0` |
| `byte_size` | **R** | `≥ 0` |
| `content_fingerprint` | **R** | |

### `ArtistIntent`

| Field | Presence | Constraints |
|---|---|---|
| `id`, `created_at` | **O** | defaults |
| `revision` | **R** | `≥ 1` |
| `source_image_id` | **R** | |
| `instruction` | **R** | `IntentInstruction` |

### `IntentInstruction` / `IntentPayload`

JSON uses alias **`schema`** for `schema_name` (`by_alias=True` on save).

| Field | Presence | Notes |
|---|---|---|
| `schema` / `schema_name` | **R** on the model | Application validator requires exact `"nova.intent.guidance.v1"` (`INTENT_SCHEMA`) |
| `payload.signals` | **R** | Non-empty list of signal objects (Pydantic); deep type/geometry via `validate_intent_instruction` |

### Intent signals (application validation)

Supported `type` values (`SUPPORTED_SIGNAL_TYPES`):

| `type` | Required geometry fields |
|---|---|
| `positive_point` | `x`, `y` in `[0.0, 1.0]` |
| `negative_point` | `x`, `y` in `[0.0, 1.0]` |
| `bounding_box` | `x`, `y`, `width`, `height` in `[0.0, 1.0]`; `width`/`height` `> 0`; `x+width` and `y+height` ≤ `1.0` |

Empty `signals` → `EMPTY_INTENT_PAYLOAD`. Unsupported `type` → `UNSUPPORTED_INTENT_SIGNAL`. Bad geometry → `INVALID_INTENT_GEOMETRY`. Wrong schema name → `UNSUPPORTED_INTENT_SCHEMA`.

**Gap:** `Project.model_validate` stores `payload.signals` as `list[dict]` with only a non-empty check. Full signal geometry / schema-name enforcement runs through `validate_intent_instruction` on Application paths, not as a second pass inside `JsonProjectStore.load`.

### `HypothesisCandidate`

| Field | Presence | Constraints |
|---|---|---|
| `id` | **O** | |
| `confidence` | **R** | `[0.0, 1.0]` |
| `mask_relative_path` | **R** | |
| `preview_relative_path` | **R** | |
| `provider_metadata` | **O** | default `{}` |

### `HypothesisCandidateSet`

| Field | Presence | Constraints |
|---|---|---|
| `id`, `created_at` | **O** | |
| `generation_id` | **O** | nullable |
| `artist_intent_revision` | **R** | `≥ 1` |
| `intent_id`, `source_image_id` | **R** | |
| `provider_id`, `provider_version` | **R** | |
| `candidates` | **R** | `min_length=1` |
| `active_candidate_id` | **O** | if set, must be in `candidates` |
| `operation_id` | **R** | |

### `GenerationRecord`

| Field | Presence | Constraints |
|---|---|---|
| `id`, `generation_id`, `created_at` | **O** | defaults |
| `sequence_number` | **R** | `≥ 1` |
| `artist_intent_id` | **R** | |
| `artist_intent_revision` | **R** | `≥ 1` |
| `provider_id`, `provider_version` | **R** | |
| `candidate_set_id`, `operation_id` | **R** | |
| `status` | **O** | `"available"` \| `"rejected"` \| `"confirmed"` (default `"available"`) |
| `rejected_at` | **O** | nullable |
| `provider_metadata` | **O** | default `{}` |

### `ObjectHypothesis`

| Field | Presence | Constraints |
|---|---|---|
| `id`, `created_at` | **O** | |
| `revision` | **R** | `≥ 1` |
| `source_image_id`, `intent_id` | **R** | |
| `status` | **R** | `"ready"` \| `"rejected"` |
| `mask_relative_path` | **R** | |
| `confidence` | **R** | `[0.0, 1.0]` |
| `provider_id`, `provider_version`, `operation_id` | **R** | |
| `candidate_set_id`, `candidate_id`, `generation_id` | **O** | nullable |

### `ConfirmationRecord`

| Field | Presence | Constraints |
|---|---|---|
| `id`, `created_at` | **O** | |
| `hypothesis_id` | **R** | |
| `confirmed_by` | **O** | default `"artist"` (literal) |
| `note` | **O** | nullable |

### `ConfirmedObject`

| Field | Presence | Constraints |
|---|---|---|
| `id`, `created_at` | **O** | |
| `revision` | **R** | `≥ 1` |
| `source_image_id`, `intent_id`, `hypothesis_id`, `confirmation_id` | **R** | |
| `mask_relative_path` | **R** | |
| `confidence` | **R** | `[0.0, 1.0]` |

### `ExtractionSettings`

All fields have defaults (entire object may be absent on `ExtractionResult`). Cross-field rule: `matting_background_threshold` **must be `<`** `matting_foreground_threshold`.

| Field | Default | Range / enum |
|---|---|---|
| `feather_radius` | `0.0` | `[0, 64]` |
| `edge_blur_radius` | `0.0` | `[0, 64]` |
| `expand_contract_pixels` | `0` | `[-32, 32]` |
| `cleanup_radius` | `0` | `[0, 16]` |
| `remove_small_regions` | `false` | bool |
| `small_region_threshold` | `0` | `≥ 0` |
| `premultiply_alpha` | `false` | bool |
| `crop_mode` | `"full_source"` | only `"full_source"` |
| `crop_padding` | `0` | `≥ 0` |
| `matting_unknown_radius` | `8` | `[0, 64]` |
| `matting_foreground_threshold` | `0.95` | `[0, 1]` |
| `matting_background_threshold` | `0.05` | `[0, 1]` |
| `matting_refinement_strength` | `1.0` | `[0, 1]` |
| `matting_preserve_known_regions` | `true` | bool |
| `matting_backend` | `"color_affinity"` | `"color_affinity"` \| `"neural_onnx"` |

### `ExtractionResult`

| Field | Presence | Constraints |
|---|---|---|
| `id`, `created_at` | **O** | |
| `revision` | **R** | `≥ 1` |
| `confirmed_object_id`, `source_image_id` | **R** | |
| `relative_asset_path` | **R** | |
| `confidence` | **R** | `[0.0, 1.0]` |
| `provider_id`, `provider_version`, `operation_id` | **R** | |
| `width`, `height` | **O** | if set, `≥ 1` |
| `confirmed_generation_id`, `confirmed_candidate_set_id`, `confirmed_candidate_id`, `confirmed_hypothesis_id` | **O** | nullable |
| `artist_intent_revision` | **O** | if set, `≥ 1` |
| `mask_provider_id`, `mask_provider_version` | **O** | nullable |
| `settings` | **O** | `ExtractionSettings` or null |
| `provider_metadata` | **O** | default `{}` |

### `OperationRecord`

| Field | Presence | Constraints |
|---|---|---|
| `id`, `created_at`, `started_at` | **O** | defaults |
| `operation_type` | **R** | string |
| `status` | **R** | `running` \| `succeeded` \| `failed` \| `cancelled` |
| `request_summary` | **O** | default `{}` |
| `error_message` | **O** | nullable |
| `finished_at` | **O** | nullable |

---

# 5. Plugin Manifest

File: **`manifest.json`** in a plugin directory or package root.

Public type: `PluginManifest` (`plugin_sdk.manifest`).  
Public loader: `load_manifest(plugin_dir)`.  
Constants: `SDK_VERSION`, `SUPPORTED_SDK_VERSIONS`, `SUPPORTED_PLUGIN_TYPES` (`plugin_sdk.constants`).

Lifecycle / registration APIs: see `01_PLUGIN_SDK_REFERENCE.md` (not repeated here).

## 5.1 Fields

| JSON field | Presence | Rules |
|---|---|---|
| `plugin_id` | **R** | Non-empty string; must not contain `/`, `\`, or `..` |
| `display_name` | **R** | Non-empty string |
| `description` | **O** | Default `""` |
| `version` | **R** | Non-empty string |
| `author` | **O** | Default `"unknown"` if absent/empty |
| `sdk_version` | **R** | Must be ∈ `SUPPORTED_SDK_VERSIONS` (currently `{"1.0"}`) |
| `plugin_type` | **R** | Must be ∈ `SUPPORTED_PLUGIN_TYPES`: `inference`, `matting`, `host_adapter` |
| `capabilities` | **R** | Non-empty list of non-empty strings; unknown capability strings are **allowed** (forward compatibility) |
| `entry_module` | **R** | Simple module name only — no `.`, `/`, or `\` |
| `optional_dependencies` | **O** | List of non-empty strings; default `[]` |

`source_path` is loader metadata (not a JSON field).

Known capability vocabulary (`KNOWN_CAPABILITIES`) is advisory for Core-recognized tokens; it is **not** an allowlist that rejects unknown values.

## 5.2 Filesystem rule (load time)

When a plugin is activated, the entry file `{entry_module}.py` must exist under the plugin directory (`validate_manifest_filesystem` / package validation). That rule is package/manager validation, not a JSON field.

---

# 6. Package Manifest

File: **`package.json`** beside `manifest.json` inside a `.nova-plugin` archive or unpacked package directory.

Public type: `PluginPackageManifest`.  
Public validators: `validate_plugin_package`, `check_package_compatibility`.  
Constants: `PACKAGE_FORMAT_VERSION`, `SUPPORTED_PACKAGE_FORMATS`, `PACKAGE_EXTENSION` (`.nova-plugin`).

Packaging / install APIs: see Plugin SDK Reference.

## 6.1 Fields

| JSON field | Presence | Rules |
|---|---|---|
| `package_format` | **R** | Must be ∈ `SUPPORTED_PACKAGE_FORMATS` (currently `{"1.0"}`) |
| `plugin_id` | **R** | Non-empty; no `/`, `\`, `..` |
| `version` | **R** | Non-empty string |
| `sdk_version` | **R** | Non-empty string (compatibility checked against `SUPPORTED_SDK_VERSIONS`) |
| `display_name` | **O** | Default `""`; omitted from `to_dict()` when empty |
| `description` | **O** | Default `""`; omitted when empty |
| `author` | **O** | Default `""`; omitted when empty |
| `checksum_sha256` | **O** | If present: lowercased; length must be `64` (`PLUGIN_PACKAGE_CHECKSUM_INVALID`); verified for archive files; **ignored with warning** for unpacked directories |

`source_path` is parser metadata (not JSON).

## 6.2 Cross-manifest compatibility

`check_package_compatibility(package, plugin)` requires:

- Supported `package_format` and both `sdk_version` values ∈ `SUPPORTED_SDK_VERSIONS`  
- Supported `plugin_type`  
- Matching `plugin_id`, `version`, and `sdk_version` between `package.json` and `manifest.json`  

`PackageCompatibilityReport.compatible` is true only when `reasons` is empty.

---

# 7. Validation Rules

## 7.1 Project package (`JsonProjectStore`)

| Stage | Rule | Error code (typical) |
|---|---|---|
| Load | `manifest.json` missing / unreadable | `LOAD_FAILED` |
| Load | `schema_version != "2.0"` | `UNSUPPORTED_SCHEMA` |
| Load | Pydantic validation fails | `LOAD_FAILED` |
| Load | Referenced asset file missing | `LOAD_FAILED` |
| Load / save | Relative asset path invalid | `INVALID_ASSET_PATH` |
| Save | Atomic write failure | `SAVE_FAILED` |

After a successful parse, `migrate_project_generation_history(project)` may **mutate the in-memory project** to back-fill empty `generation_records` from existing `candidate_sets`. It does **not** rewrite the on-disk file by itself.

## 7.2 Intent instruction (`domain.validation`)

| Rule | Code |
|---|---|
| Empty signals | `EMPTY_INTENT_PAYLOAD` |
| Unsupported signal `type` | `UNSUPPORTED_INTENT_SIGNAL` |
| Invalid geometry / object shape | `INVALID_INTENT_GEOMETRY` / `INVALID_INTENT_SIGNAL` |
| `schema_name != "nova.intent.guidance.v1"` | `UNSUPPORTED_INTENT_SCHEMA` |
| Instruction model parse failure | `INVALID_INTENT_INSTRUCTION` |

## 7.3 Plugin `manifest.json`

| Rule | Code / behaviour |
|---|---|
| Missing file / invalid JSON / non-object root | `PluginValidationError` |
| Required string empty/absent | field must be non-empty string |
| Invalid `plugin_id` / `entry_module` | validation error |
| Unsupported `plugin_type` | `PLUGIN_TYPE_UNSUPPORTED` |
| Unsupported `sdk_version` | `PLUGIN_SDK_INCOMPATIBLE` |
| Empty `capabilities` | rejected |
| Unknown capability tokens | **allowed** |

## 7.4 Package validation (`validate_plugin_package`)

| Rule | Code (examples) |
|---|---|
| Missing `package.json` / `manifest.json` | `PLUGIN_PACKAGE_MANIFEST_MISSING` / `PLUGIN_PACKAGE_PLUGIN_MANIFEST_MISSING` |
| Unsupported `package_format` | `PLUGIN_PACKAGE_FORMAT_UNSUPPORTED` |
| Invalid checksum length | `PLUGIN_PACKAGE_CHECKSUM_INVALID` |
| Checksum mismatch (archive) | `PLUGIN_PACKAGE_CHECKSUM_MISMATCH` |
| Unsafe / missing / symlink entry module | `PLUGIN_PACKAGE_ENTRY_UNSAFE` / `ENTRY_MISSING` / `SYMLINK_FORBIDDEN` |
| Zip path traversal / symlink members | unsafe-path / symlink codes from archive open |
| Cross-manifest mismatch / unsupported SDK | collected in `errors` via compatibility reasons |

`PackageValidationResult.ok` requires no errors **and** a compatible report.

---

# 8. Version Compatibility

**What the implementation guarantees:**

| Surface | Rule |
|---|---|
| Project | Load accepts only `schema_version == "2.0"` |
| Plugin SDK | Manifest `sdk_version` must be in `SUPPORTED_SDK_VERSIONS` (`{"1.0"}`) |
| Package format | `package_format` must be in `SUPPORTED_PACKAGE_FORMATS` (`{"1.0"}`) |
| Package ↔ plugin | `plugin_id` / `version` / `sdk_version` must match across the two JSON files |
| Intent schema | Application validation accepts only `nova.intent.guidance.v1` |
| Same-major Project documents | In-memory `migrate_project_generation_history` can synthesize missing `generation_records` for older Schema **2.0** documents that predate that list |

**Distribution version** (`nova-layer` in `pyproject.toml`) is **not** Project schema, SDK, or package-format version.

**Do not assume (not implemented as public guarantees):**

- Schema **1.0 → 2.0** project migration  
- Multi-version Project loaders / converters  
- Cross-major Plugin SDK migration tools  
- Automatic rewrite of on-disk manifests after in-memory generation back-fill  
- Wire-format schema negotiation over a network API  

Always read the `SUPPORTED_*` / Literal constants in source when asserting exact sets.

---

# 9. Unsupported Versions

| Input | Behaviour |
|---|---|
| Project `schema_version` other than `"2.0"` (including Schema `"1.0"`) | Rejected — `UNSUPPORTED_SCHEMA` |
| Plugin `sdk_version` ∉ `SUPPORTED_SDK_VERSIONS` | Rejected — `PLUGIN_SDK_INCOMPATIBLE` |
| Package `package_format` ∉ `SUPPORTED_PACKAGE_FORMATS` | Rejected — `PLUGIN_PACKAGE_FORMAT_UNSUPPORTED` |
| Intent `schema` other than `nova.intent.guidance.v1` | Rejected on Application validation — `UNSUPPORTED_INTENT_SCHEMA` |
| Phase 1 Schema 1.0 packages | Out of Object Workflow public schema scope (separate bounded context) |

---

# 10. Related Documents

| Document | Role |
|---|---|
| `00_Project/01_Implementation/ARCHITECTURE.md` | Architecture authority |
| `00_Project/01_Implementation/02_DOMAIN_MODEL_SPEC.md` | Domain behaviour / invariants |
| `05_Documents/API/00_PUBLIC_API_OVERVIEW.md` | Public API index |
| `05_Documents/API/01_PLUGIN_SDK_REFERENCE.md` | Plugin SDK symbols, packaging APIs |
| `05_Documents/API/02_AUTOMATION_COMMAND_REFERENCE.md` | Commands operating on projects |
| `05_Documents/API/03_EVENT_REFERENCE.md` | Automation events (not schema documents) |

---

## Explicitly Excluded

- Phase 1 / Smart Layer Schema **1.0** field catalogs  
- Private workspace preference documents (not Project schema)  
- Runtime cache / session state (must not be persisted into Project schema — ARCHITECTURE)  
- Invented migration tools or forward/backward compatibility promises  
- Full Plugin SDK registration lifecycle (covered by Plugin SDK Reference)  
- Automation event payloads (covered by Event Reference)  

## Documentation / Implementation Gaps

- Intent signal geometry and `INTENT_SCHEMA` are **not** re-checked inside `JsonProjectStore.load` after Pydantic parse.  
- `checksum_sha256` length is validated as 64 characters; charset is not strictly enforced as hex digits beyond lowercasing.  
- Plugin/package JSON parsers ignore unknown keys (unlike Project Domain `extra="forbid"`).  
- `InstalledPluginRecord` is an install-registry record, not a third on-disk “schema family” for authors; omitted from the three public schemas above.  
