# NOVA Layer

# 02_DOMAIN_MODEL_SPEC

Version: 0.3  
Status: Draft  
Document Type: Data and Domain Specification

---

## 1. Purpose

This document defines the core domain model for the NOVA Layer MVP milestone.

It specifies:

- Authoritative domain entities
- Entity identity and revision rules
- Required fields
- Relationships between entities
- Validation constraints
- Persistence boundaries
- Source and result provenance
- Domain invariants
- Serialization names
- Project schema version behaviour

This document is the authority for persistent product data in the MVP domain model.

It coexists with the existing Phase 1 domain (`SmartLayer`, `Shot`, and related types). The two domains must not silently replace each other. Any future integration requires an explicit adapter or migration plan.

Implementation of this domain lives under the bounded context:

```text
nova_layer.object_workflow
```

organized with logical areas equivalent to domain, application, ports, and adapters. A permanent `mvp` package must not be introduced. Phase 1 code must not be moved or renamed.

---

## 2. Domain Model Principle

The domain model represents information that NOVA Layer must remember, validate, save, reopen, and trace.

Temporary AI computation is not automatically part of the domain model.

The following rule applies:

> Domain data represents product truth.  
> Inference data represents temporary computation.

AI-provider-specific intermediate data must not become an authoritative product entity unless a later specification explicitly promotes it.

Operation outcome and workflow state are separate concepts. Operation failure, cancellation, discard, and obsolescence are recorded on `OperationRecord` and must not introduce a persistent workflow state named `Failed` or `Cancelled`.

---

## 3. MVP Domain Scope

The MVP domain model supports:

- One project
- One active source image
- One intended object lineage
- Multiple intent revisions
- Multiple Object Hypotheses
- Explicit artist confirmation
- Multiple confirmed object revisions over time
- Multiple extraction attempts (entity defined; extraction operations deferred)
- One current Extraction Result pointer (null until extraction is implemented)
- Operation and failure history

The MVP does not yet define:

- Multiple simultaneously active objects
- Video clips
- Frame sequences
- Temporal tracking
- Shared object identity across shots
- Collaborative editing
- Cloud synchronisation
- Project merging
- Model training data management
- Automatic migration from Phase 1 schema `1.0`

---

## 4. Authoritative Domain Entities

The MVP defines the following authoritative entities:

1. `Project`
2. `SourceImage`
3. `ArtistIntent`
4. `ObjectHypothesis`
5. `ConfirmationRecord`
6. `ConfirmedObject`
7. `ExtractionResult`
8. `OperationRecord`

Each authoritative entity must have:

- A stable unique identifier
- A creation timestamp
- Validation rules
- Traceable relationships to relevant parent entities

Entities do **not** carry a `schema_version` field.

There is exactly one authoritative project schema version on the persisted `Project` document.

---

## 5. Non-Domain Inference Data

The following concepts are internal inference data and are not authoritative domain entities:

- `InferenceContext`
- `TemporaryEvidence`
- `IntermediateResult`
- Model embeddings
- Internal feature tensors
- Temporary confidence maps
- Provider-specific intermediate masks
- Preprocessing buffers
- Postprocessing buffers

These values may exist in memory, temporary cache, diagnostic output, or provider-specific storage.

They must not be required to reconstruct authoritative project state.

If temporary inference data is persisted for caching or diagnostics, it must be treated as disposable and regenerable.

---

## 6. Shared Types

### 6.1 Entity Identifier

All entity identifiers must be globally unique within the project.

Representation:

```text
UUID string
```

Serialization name: `id`

### 6.2 Timestamps

All timestamps are UTC and serialized as ISO-8601 strings.

Serialization names: `created_at`, `updated_at`, `started_at`, `finished_at`

### 6.3 Normalized Coordinate

Floating-point value in the closed range `[0.0, 1.0]`.

Normalized coordinates are relative to the active source image bounds.

### 6.4 Confidence

Floating-point value in the closed range `[0.0, 1.0]`.

### 6.5 Relative Asset Path

A path relative to the project package root. Absolute filesystem paths must not be stored as authoritative asset locations.

### 6.6 PositivePoint

| Field | Type | Required | Serialization |
|---|---|---|---|
| `type` | `"positive_point"` | yes | `type` |
| `x` | NormalizedCoordinate | yes | `x` |
| `y` | NormalizedCoordinate | yes | `y` |

Constraints:

- `0.0 <= x <= 1.0`
- `0.0 <= y <= 1.0`

### 6.7 BoundingBox

| Field | Type | Required | Serialization |
|---|---|---|---|
| `type` | `"bounding_box"` | yes | `type` |
| `x` | NormalizedCoordinate | yes | `x` |
| `y` | NormalizedCoordinate | yes | `y` |
| `width` | NormalizedCoordinate | yes | `width` |
| `height` | NormalizedCoordinate | yes | `height` |

Constraints:

- `width > 0.0`
- `height > 0.0`
- `x + width <= 1.0`
- `y + height <= 1.0`

### 6.8 Intent Signal (extensible)

An intent signal is a typed object in the ArtistIntent payload.

Supported signal types for the first vertical slice:

- `PositivePoint`
- `BoundingBox`

`BoundingBox` is optional. At least one supported intent signal must exist.

The Domain Model remains extensible. Future signal types may include, without limitation:

- negative points
- scribbles
- polygons
- text prompts
- masks
- brush strokes

UI constraints are not Domain constraints. Unsupported signal types presented to Application validation in this milestone must return an explicit validation error and must not create a new intent revision or invalidate existing active state.

### 6.9 Workflow State

Canonical workflow states:

| Value | Serialization | First slice |
|---|---|---|
| NoSource | `no_source` | yes |
| SourceReady | `source_ready` | yes |
| IntentProvided | `intent_provided` | yes |
| HypothesisReady | `hypothesis_ready` | yes |
| ObjectConfirmed | `object_confirmed` | yes |
| ExtractionReady | `extraction_ready` | no (complete spec only) |
| HypothesisRejected | `hypothesis_rejected` | no (later use case) |

Forbidden as workflow states:

- `Empty`
- `Failed`
- `Cancelled`
- `HypothesisGenerating`
- `ExtractionGenerating`

In-flight generation, failure, cancellation, discard, and obsolescence belong to `OperationRecord.status`, not to workflow state.

The initial project workflow state is `NoSource`.

Derived workflow state for the approved first slice is determined from the latest valid committed Domain graph. A failed inference operation must preserve the latest valid workflow state (for example, remain `IntentProvided`).

---

## 7. Project Schema Version

### 7.1 Field

The persisted project document must include:

| Field | Type | Required | Serialization |
|---|---|---|---|
| `schema_version` | string | yes | `schema_version` |

### 7.2 Authoritative Value for This Domain

```text
schema_version = "2.0"
```

This is the only authoritative schema version for the MVP domain persistence format.

### 7.3 Loader Behaviour

1. Read `schema_version` before full deserialization.
2. If `schema_version` is `"2.0"`, deserialize using this specification.
3. If `schema_version` is `"1.0"`, the object-workflow loader must return an explicit error stating that Phase 1 projects are not loaded by this schema.
4. If `schema_version` is missing or unsupported, return an explicit error.
5. Automatic migration from `"1.0"` to `"2.0"` is outside this milestone.

### 7.4 Writer Behaviour

- Writers must emit only `schema_version: "2.0"`.
- Writers must not modify existing Phase 1 `"1.0"` project packages.
- Entity evolution uses `revision` / `version` fields and future migration rules, not per-entity schema versions.

---

## 8. Entity Definitions

Serialization names are snake_case JSON keys.

### 8.1 Project

| Field | Type | Required | Serialization |
|---|---|---|---|
| `id` | UUID string | yes | `id` |
| `schema_version` | `"2.0"` | yes | `schema_version` |
| `name` | string | yes | `name` |
| `created_at` | timestamp | yes | `created_at` |
| `updated_at` | timestamp | yes | `updated_at` |
| `workflow_state` | Workflow State | yes | `workflow_state` |
| `source_images` | SourceImage[] | yes | `source_images` |
| `intents` | ArtistIntent[] | yes | `intents` |
| `hypotheses` | ObjectHypothesis[] | yes | `hypotheses` |
| `confirmations` | ConfirmationRecord[] | yes | `confirmations` |
| `confirmed_objects` | ConfirmedObject[] | yes | `confirmed_objects` |
| `extraction_results` | ExtractionResult[] | yes | `extraction_results` |
| `operations` | OperationRecord[] | yes | `operations` |
| `active_source_image_id` | UUID string \| null | yes | `active_source_image_id` |
| `active_intent_id` | UUID string \| null | yes | `active_intent_id` |
| `active_hypothesis_id` | UUID string \| null | yes | `active_hypothesis_id` |
| `active_confirmation_id` | UUID string \| null | yes | `active_confirmation_id` |
| `active_confirmed_object_id` | UUID string \| null | yes | `active_confirmed_object_id` |
| `active_extraction_result_id` | UUID string \| null | yes | `active_extraction_result_id` |

Initial values after Create Project:

- `workflow_state = no_source`
- all history arrays empty
- all active_* fields `null`

### 8.2 SourceImage

| Field | Type | Required | Serialization |
|---|---|---|---|
| `id` | UUID string | yes | `id` |
| `created_at` | timestamp | yes | `created_at` |
| `original_filename` | string | yes | `original_filename` |
| `relative_asset_path` | relative path | yes | `relative_asset_path` |
| `media_type` | `"image/png"` \| `"image/jpeg"` | yes | `media_type` |
| `width` | integer > 0 | yes | `width` |
| `height` | integer > 0 | yes | `height` |
| `byte_size` | integer >= 0 | yes | `byte_size` |
| `content_fingerprint` | string | yes | `content_fingerprint` |

Official MVP source formats:

- PNG
- JPEG

Unsupported formats must be rejected before a SourceImage is committed.

#### Content fingerprint

- Algorithm: SHA-256
- Input: original source file bytes
- Persist: lowercase hexadecimal digest
- Do not compute the authoritative fingerprint from decoded pixels, thumbnails, paths, timestamps, or metadata

### 8.3 ArtistIntent

ArtistIntent is a semantic artist instruction. Revisions are immutable.

| Field | Type | Required | Serialization |
|---|---|---|---|
| `id` | UUID string | yes | `id` |
| `created_at` | timestamp | yes | `created_at` |
| `revision` | integer >= 1 | yes | `revision` |
| `source_image_id` | UUID string | yes | `source_image_id` |
| `instruction` | IntentInstruction | yes | `instruction` |

#### IntentInstruction

| Field | Type | Required | Serialization |
|---|---|---|---|
| `schema` | string | yes | `schema` |
| `payload` | IntentPayload | yes | `payload` |

For this milestone:

```text
instruction.schema = "nova.intent.guidance.v1"
```

#### IntentPayload (`nova.intent.guidance.v1`)

| Field | Type | Required | Serialization |
|---|---|---|---|
| `signals` | IntentSignal[] | yes | `signals` |

Each signal is a discriminated object by `type`.

First-slice supported `type` values:

- `positive_point`
- `bounding_box`

Validation rules:

1. An empty payload (`signals` missing or empty) is invalid.
2. At least one supported intent signal must exist.
3. Every point must be inside source-image bounds (normalized inclusive range).
4. Every bounding box must have positive width and height.
5. Every bounding box must be inside source-image bounds.
6. Unsupported signal types must return an explicit validation error.
7. Invalid intent input must not create a new revision and must not invalidate existing active state.

`CreateArtistIntent` is used only when no active ArtistIntent exists.  
`UpdateArtistIntent` creates a new immutable revision, preserves previous revisions in history, sets the new revision active, and invalidates active ObjectHypothesis and all downstream active entities. Previous revisions must never be mutated in place.

`UpdateArtistIntent` is specified now; its implementation may be deferred until the next slice after the first vertical slice.

Future instruction schemas and signal types may be added without renaming the ArtistIntent entity.

### 8.4 ObjectHypothesis

| Field | Type | Required | Serialization |
|---|---|---|---|
| `id` | UUID string | yes | `id` |
| `created_at` | timestamp | yes | `created_at` |
| `revision` | integer >= 1 | yes | `revision` |
| `source_image_id` | UUID string | yes | `source_image_id` |
| `intent_id` | UUID string | yes | `intent_id` |
| `status` | `"ready"` \| `"rejected"` | yes | `status` |
| `mask_relative_path` | relative path | yes | `mask_relative_path` |
| `confidence` | Confidence | yes | `confidence` |
| `provider_id` | string | yes | `provider_id` |
| `provider_version` | string | yes | `provider_version` |
| `operation_id` | UUID string | yes | `operation_id` |

A hypothesis with `status = "ready"` may be confirmed.  
A hypothesis with `status = "rejected"` must not become a ConfirmedObject.

`RejectHypothesis` may remain as a later MVP use case. It is excluded from the first vertical slice implementation and acceptance gate.

### 8.5 ConfirmationRecord

| Field | Type | Required | Serialization |
|---|---|---|---|
| `id` | UUID string | yes | `id` |
| `created_at` | timestamp | yes | `created_at` |
| `hypothesis_id` | UUID string | yes | `hypothesis_id` |
| `confirmed_by` | `"artist"` | yes | `confirmed_by` |
| `note` | string \| null | no | `note` |

Confirmation is an explicit artist action. Implicit confirmation is forbidden.

### 8.6 ConfirmedObject

| Field | Type | Required | Serialization |
|---|---|---|---|
| `id` | UUID string | yes | `id` |
| `created_at` | timestamp | yes | `created_at` |
| `revision` | integer >= 1 | yes | `revision` |
| `source_image_id` | UUID string | yes | `source_image_id` |
| `intent_id` | UUID string | yes | `intent_id` |
| `hypothesis_id` | UUID string | yes | `hypothesis_id` |
| `confirmation_id` | UUID string | yes | `confirmation_id` |
| `mask_relative_path` | relative path | yes | `mask_relative_path` |
| `confidence` | Confidence | yes | `confidence` |

### 8.7 ExtractionResult

Defined for completeness. Extraction operations are outside the first vertical slice.

| Field | Type | Required | Serialization |
|---|---|---|---|
| `id` | UUID string | yes | `id` |
| `created_at` | timestamp | yes | `created_at` |
| `revision` | integer >= 1 | yes | `revision` |
| `confirmed_object_id` | UUID string | yes | `confirmed_object_id` |
| `mask_relative_path` | relative path | yes | `mask_relative_path` |
| `confidence` | Confidence | yes | `confidence` |
| `provider_id` | string | yes | `provider_id` |
| `provider_version` | string | yes | `provider_version` |
| `operation_id` | UUID string | yes | `operation_id` |

### 8.8 OperationRecord

| Field | Type | Required | Serialization |
|---|---|---|---|
| `id` | UUID string | yes | `id` |
| `created_at` | timestamp | yes | `created_at` |
| `operation_type` | string | yes | `operation_type` |
| `status` | `"succeeded"` \| `"failed"` \| `"cancelled"` | yes | `status` |
| `request_summary` | object | yes | `request_summary` |
| `error_message` | string \| null | no | `error_message` |
| `started_at` | timestamp | yes | `started_at` |
| `finished_at` | timestamp \| null | no | `finished_at` |

Known `operation_type` values:

- `create_project`
- `load_source`
- `create_intent`
- `update_intent`
- `generate_hypothesis`
- `reject_hypothesis`
- `confirm_hypothesis`
- `save_project`
- `load_project`

A failed, cancelled, discarded, or obsolete operation must not activate partial output and must not change workflow state away from the latest valid committed state.

---

## 9. Active Reference Rules

1. At most one active entity of each kind may exist.
2. If an `active_*_id` is non-null, it must reference an entity present in the corresponding history array.
3. Historical entities remain accessible after they are no longer active.
4. Replacing the active source invalidates active intent, hypothesis, confirmation, confirmed object, and extraction pointers.
5. Creating or updating intent invalidates active hypothesis, confirmation, confirmed object, and extraction pointers.
6. Rejecting a hypothesis (later use case) clears `active_hypothesis_id` but retains the hypothesis in history with `status = "rejected"`.
7. Confirming a hypothesis creates a ConfirmationRecord and ConfirmedObject, sets their active pointers, and sets workflow state to `object_confirmed`.

---

## 10. Revision and Version Rules

1. `revision` is a monotonic integer per entity lineage within the project for that entity type.
2. The first entity of a type uses `revision = 1`.
3. Each newly committed intent, hypothesis, confirmed object, or extraction result receives the next revision number for its type.
4. ArtistIntent revisions are immutable; updates always append a new entity.
5. Entity evolution across product releases uses revision/version fields and project-level migration rules.
6. Per-entity `schema_version` fields are forbidden.

---

## 11. Entity Relationships

```text
Project
 ├── SourceImage[]
 ├── ArtistIntent[]          → source_image_id
 ├── ObjectHypothesis[]      → source_image_id, intent_id, operation_id
 ├── ConfirmationRecord[]    → hypothesis_id
 ├── ConfirmedObject[]       → source_image_id, intent_id, hypothesis_id, confirmation_id
 ├── ExtractionResult[]      → confirmed_object_id, operation_id
 └── OperationRecord[]
```

Active pointers on Project select the current entity of each kind.

---

## 12. Validation Invariants

1. `schema_version` must equal `"2.0"` for this domain format.
2. Initial projects satisfy the `NoSource` conditions in §8.1.
3. A SourceImage may be created only for PNG or JPEG inputs that pass validation.
4. `content_fingerprint` must be the lowercase hex SHA-256 of original source file bytes.
5. An ArtistIntent must reference an existing SourceImage and pass intent-signal validation.
6. An ObjectHypothesis must reference existing SourceImage and ArtistIntent.
7. A ConfirmationRecord must reference an existing ObjectHypothesis with `status = "ready"`.
8. A ConfirmedObject must reference matching SourceImage, Intent, Hypothesis, and ConfirmationRecord.
9. No ConfirmedObject may be created without an explicit ConfirmationRecord.
10. Engine providers must not create or mutate Project entities directly.
11. Failed, cancelled, discarded, or obsolete operations must not leave partially committed domain graphs or activate partial output.
12. Workflow state must never be set to `Empty`, `Failed`, or `Cancelled`.

---

## 13. Persistence Requirements

### 13.1 Package Layout

```text
{project_name}.nova/
  manifest.json
  assets/
    source/
    masks/
    intent/
```

### 13.2 Manifest

`manifest.json` contains the serialized Project document defined in this specification.

### 13.3 Assets

- Source pixels are stored under `assets/source/`.
- Hypothesis and confirmed masks are stored under `assets/masks/`.
- Optional intent-associated masks may be stored under `assets/intent/`.
- Domain fields store relative paths only.
- Persisted hypothesis masks for this milestone are binary single-channel unsigned 8-bit images with background `0` and foreground `255`, matching source width and height.

### 13.4 Atomicity

Save must be atomic with respect to the package directory. A failed save must leave the previously valid package unchanged.

### 13.5 Phase 1 Isolation

Phase 1 `"1.0"` packages remain owned by the existing Phase 1 persistence path.  
This schema `"2.0"` writer and loader must not silently rewrite `"1.0"` packages.

---

## 14. Coexistence with Phase 1 Domain

1. Phase 1 types such as `SmartLayer` and `Shot` remain unchanged by this milestone.
2. MVP entities defined here must not silently replace Phase 1 entities of similar names.
3. Implementations must use `nova_layer.object_workflow` with logical domain / application / ports / adapters areas.
4. A product namespace named `mvp` must not be introduced.
5. Future integration between Phase 1 and this domain requires an explicit adapter or migration plan.

---

## 15. Summary

The MVP domain is a schema `"2.0"` project graph centered on SourceImage, ArtistIntent, ObjectHypothesis, ConfirmationRecord, and ConfirmedObject.

Artist confirmation is explicit.  
Inference output is temporary until validated and committed by Application.  
Operation failure does not become a workflow state.  
Extraction entities exist for forward compatibility but are not exercised by the first vertical slice.
