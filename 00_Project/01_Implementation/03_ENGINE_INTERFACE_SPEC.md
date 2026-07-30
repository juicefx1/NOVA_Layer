# NOVA Layer

# 03_ENGINE_INTERFACE_SPEC

Version: 0.3  
Status: Draft  
Document Type: Application and Engine Contract Specification

---

## 1. Purpose

This document defines the interfaces between the NOVA Layer application layer and its processing engines for the object-workflow bounded context.

It specifies:

- Application commands
- Application queries
- Request and response structures
- Core Inference Engine interfaces
- Precision Extraction Engine interfaces (deferred for the first vertical slice)
- Operation handling
- Validation boundaries
- Error and cancellation behaviour
- Provider abstraction rules
- Mock Core Inference behaviour for the first vertical slice

This document defines what may be requested from the system.

The internal execution sequence of each use case is defined in `03A_USE_CASE_SPEC.md`.

Domain field definitions are authoritative in `02_DOMAIN_MODEL_SPEC.md`.

---

## 2. Core Interface Principle

All application operations must follow the pattern:

```text
Request
    ↓
Application Service
    ↓
Domain and Engine Operations
    ↓
Response
```

Rules:

1. Engines never own Project state.
2. Engines never mutate Project entities.
3. Application validates inputs, invokes engines, validates results, then commits Domain entities.
4. Temporary inference data is not Domain truth until Application commits it.
5. Provider-specific details remain behind engine ports.
6. Operation status and workflow state are separate. Failure and cancellation belong to `OperationRecord`, not workflow state.

---

## 3. Architectural Ownership

| Concern | Owner |
|---|---|
| Workflow state transitions | Application |
| Domain entity creation and revision | Application + Domain |
| Persistence | Application via persistence port |
| Inference computation | Core Inference Engine |
| Extraction computation | Precision Extraction Engine (deferred) |
| Artist confirmation decision | Application / artist action only |
| Obsolete result discard | Application |

Engines receive only the data required for computation. They must not receive a mutable Project aggregate.

Bounded context root:

```text
02_Source/src/nova_layer/object_workflow/
```

Logical areas: domain, application, ports, adapters.

Do not introduce an `mvp` namespace. Do not move or rename Phase 1 code.

---

## 4. Execution Model for the First Vertical Slice

For the first vertical slice:

- Core Inference is **synchronous and in-process**.
- Application waits for the engine result before continuing the use case.
- Asynchronous job queues, background workers, and cancellation tokens are out of scope for this slice.
- Cancellation semantics are defined for forward compatibility on `OperationRecord` but need not be exercised by the Mock provider in this slice.

Precision Extraction remains defined at interface level but is **not required** to be implemented or invoked in this slice.

---

## 5. Application Commands

Commands mutate project state or trigger processing that may lead to mutation after validation.

| Command | Purpose | First Slice |
|---|---|---|
| `CreateProject` | Create a new schema `"2.0"` project in `NoSource` | Required |
| `LoadSource` | Validate and commit one PNG/JPEG SourceImage | Required |
| `CreateArtistIntent` | Commit the first ArtistIntent when none is active | Required |
| `UpdateArtistIntent` | Append a new immutable ArtistIntent revision | Specified now; implementation deferred |
| `GenerateObjectHypothesis` | Invoke Core Inference and commit ObjectHypothesis | Required |
| `RejectHypothesis` | Mark active hypothesis rejected | Later use case; excluded from first-slice gate |
| `ConfirmObjectHypothesis` | Create ConfirmationRecord + ConfirmedObject | Required |
| `SaveProject` | Persist schema `"2.0"` package atomically | Required |
| `LoadProject` | Load schema `"2.0"` package and restore actives | Required |
| `GenerateExtraction` | Invoke Precision Extraction | Deferred |

### 5.1 CreateArtistIntent vs UpdateArtistIntent

`CreateArtistIntent`:

- Allowed only when no active ArtistIntent exists.
- Creates revision `1` for the lineage (or the first intent for the active source).
- Sets the new intent active.
- Transitions workflow state to `IntentProvided`.

`UpdateArtistIntent`:

- Creates a new immutable ArtistIntent revision.
- Preserves the previous revision in history.
- Sets the new revision as active.
- Invalidates the active ObjectHypothesis and all downstream active entities.
- Never mutates a previous ArtistIntent revision in place.
- Must not recreate an updated intent through `CreateArtistIntent`.

Invalid intent input for either command:

- Returns an explicit validation error.
- Must not create a new revision.
- Must not invalidate existing active state.

### 5.2 Inference Failure Behaviour

If `GenerateObjectHypothesis` fails:

- Record `OperationRecord` with `status = "failed"`.
- Preserve the latest valid workflow state (example: remain `IntentProvided`).
- Do not create or activate a partial ObjectHypothesis.
- Do not set workflow state to `Failed`.

Obsolete, cancelled, or discarded results must not activate partial output.

Command responses return either:

- Success payload with relevant entity ids / workflow state, or
- Structured failure with error code and message.

---

## 6. Application Queries

Queries must not mutate Domain state.

| Query | Purpose | First Slice |
|---|---|---|
| `GetProjectSummary` | Return ids, workflow state, active pointers | Required |
| `GetActiveSource` | Return active SourceImage or null | Required |
| `GetActiveIntent` | Return active ArtistIntent or null | Required |
| `GetActiveHypothesis` | Return active ObjectHypothesis or null | Required |
| `GetActiveConfirmedObject` | Return active ConfirmedObject or null | Required |
| `ListOperations` | Return OperationRecord history | Required |
| `GetActiveExtraction` | Return active ExtractionResult or null | Deferred |

---

## 7. Core Inference Engine Interface

### 7.1 Port

```text
CoreInferenceEngine.generate_hypothesis(request) -> result | error
```

The port is provider-agnostic. The first vertical slice uses a Mock provider.

### 7.2 Request

| Field | Type | Required | Notes |
|---|---|---|---|
| `request_id` | UUID string | yes | Correlation id owned by Application |
| `source_image_path` | path | yes | Readable source asset path for this call |
| `source_width` | integer | yes | Must match SourceImage |
| `source_height` | integer | yes | Must match SourceImage |
| `media_type` | `"image/png"` \| `"image/jpeg"` | yes | Official MVP formats |
| `content_fingerprint` | string | yes | Lowercase hex SHA-256 of original source bytes |
| `intent_instruction` | IntentInstruction | yes | As defined in Domain Model |
| `provider_options` | object | no | Provider-specific, optional |

The engine must not receive:

- Project aggregate
- Confirmation records
- Confirmed objects
- Persistence handles that can mutate Domain truth

### 7.3 Success Result

The result must remain engine-neutral. Provider-specific image library types must not appear on the public interface. If an internal image library is used, convert at the engine boundary.

| Field | Type | Required | Notes |
|---|---|---|---|
| `request_id` | UUID string | yes | Must match the request |
| `mask` | BinaryMask | yes | Canonical representation below |
| `confidence` | Confidence | yes | `[0.0, 1.0]` |
| `provider_id` | string | yes | e.g. `mock.core_inference` |
| `provider_version` | string | yes | Provider version string |
| `diagnostics` | object | no | Disposable; not Domain |

#### BinaryMask (canonical)

| Property | Requirement |
|---|---|
| Width | Equal to source image width |
| Height | Equal to source image height |
| Channels | One |
| Pixel type | Unsigned 8-bit |
| Background | `0` |
| Foreground | `255` |

Public transport representation may be raw bytes plus width/height/channel metadata, or an equivalent engine-neutral structure. It must not expose provider-specific types.

### 7.4 Error Result

| Field | Type | Required |
|---|---|---|
| `request_id` | UUID string | yes |
| `error_code` | string | yes |
| `message` | string | yes |
| `retryable` | boolean | yes |

Known error codes for this milestone:

- `INVALID_REQUEST`
- `UNSUPPORTED_MEDIA_TYPE`
- `UNSUPPORTED_INTENT_SCHEMA`
- `UNSUPPORTED_INTENT_SIGNAL`
- `INFERENCE_FAILED`
- `CANCELLED` (forward compatibility; operation status only)

### 7.5 Application Commit Rules After Inference

On success:

1. Verify `request_id` is still the current outstanding request.
2. Validate mask dimensions, channel count, pixel type, and value domain.
3. Persist mask asset under the project package.
4. Create `ObjectHypothesis` with next revision and `status = "ready"`.
5. Set `active_hypothesis_id`.
6. Record succeeded `OperationRecord`.
7. Transition workflow state to `HypothesisReady`.

On obsolete result:

1. If `request_id` is no longer current, discard the result.
2. Do not create Domain entities from obsolete results.
3. Do not change workflow state.
4. Optionally record a cancelled/ignored operation note; do not corrupt actives.

On failure:

1. Record failed `OperationRecord`.
2. Preserve the latest valid workflow state.
3. Do not create a partial ObjectHypothesis.
4. Do not set workflow state to `Failed`.

---

## 8. Mock Core Inference Contract

Provider id:

```text
mock.core_inference
```

Behaviour for the first vertical slice:

1. Accepts PNG and JPEG sources.
2. Accepts `nova.intent.guidance.v1` instructions with supported signals.
3. Returns a deterministic BinaryMask for identical request inputs.
4. Mask matches the canonical representation in §7.3.
5. Returns confidence in `[0.0, 1.0]`.
6. Does not call external network services.
7. Does not require GPU.
8. Does not invent ConfirmedObject or ConfirmationRecord.
9. Converts any internal image library types to the engine-neutral BinaryMask at the boundary.

---

## 9. Precision Extraction Engine Interface

Defined for completeness. Not required in the first vertical slice.

### 9.1 Port

```text
PrecisionExtractionEngine.extract(request) -> result | error
```

### 9.2 Request (summary)

- `request_id`
- Confirmed object mask reference
- Source image reference
- Optional provider options

### 9.3 Result (summary)

- Refined BinaryMask
- Confidence
- Provider identity/version

Application commit rules mirror Core Inference: validate, persist asset, create ExtractionResult, update actives. Engines still do not mutate Project. Extraction success may set workflow state to `ExtractionReady` in a later slice.

---

## 10. Confirmation Interface

Confirmation is not an engine operation.

```text
ConfirmObjectHypothesis(hypothesis_id) -> ConfirmationRecord + ConfirmedObject
```

Rules:

1. Hypothesis must exist and have `status = "ready"`.
2. Application creates ConfirmationRecord with `confirmed_by = "artist"`.
3. Application creates ConfirmedObject copying the validated hypothesis mask reference and provenance links.
4. Workflow state becomes `ObjectConfirmed`.
5. Engines are not invoked.

---

## 11. Persistence Interface

### 11.1 Port

```text
ProjectStore.save(project, package_path) -> ok | error
ProjectStore.load(package_path) -> project | error
```

### 11.2 Schema Gating

1. Save writes `schema_version = "2.0"` only.
2. Load reads `schema_version` first.
3. `"2.0"` loads with this Domain Model.
4. `"1.0"` and unknown versions return explicit errors.
5. No automatic migration in this milestone.

### 11.3 Isolation

This store is separate from the Phase 1 schema `"1.0"` store. It must not silently extend or rewrite Phase 1 packages.

---

## 12. Source Loading Interface

```text
LoadSource(path) -> SourceImage
```

Rules:

1. Official formats: PNG, JPEG only.
2. Reject unsupported formats before Domain commit.
3. Compute width, height, byte size.
4. Compute `content_fingerprint` as lowercase hex SHA-256 of original source file bytes.
5. Copy or materialize asset into `assets/source/` with a relative path.
6. Set `active_source_image_id` and clear dependent actives.
7. Workflow state becomes `SourceReady`.

---

## 13. Error and Cancellation Behaviour

1. All mutating commands that attempt processing which can fail produce an OperationRecord.
2. Structured errors include machine-readable `error_code` and human-readable `message`.
3. Cancellation is reserved for future async execution and appears only as OperationRecord status, never as workflow state.
4. Obsolete results are discarded by Application using `request_id`.
5. Failed operations preserve the latest valid workflow state.

---

## 14. Prohibited Behaviours

1. Engines must not create ConfirmationRecord.
2. Engines must not create ConfirmedObject.
3. Engines must not write `manifest.json`.
4. Engines must not change workflow state.
5. UI must not bypass Application validation.
6. Implementations must not introduce a permanent `mvp` architectural namespace.
7. Domain must not treat first-slice signal support as the only possible future ArtistIntent signals.
8. Workflow state must never be `Empty`, `Failed`, or `Cancelled`.
9. `CreateArtistIntent` must not be used to apply an intent update when an active intent already exists.

---

## 15. First Vertical Slice Coverage

Required:

- CreateProject
- LoadSource (PNG/JPEG, SHA-256 fingerprint)
- CreateArtistIntent (`positive_point` and optional `bounding_box`)
- GenerateObjectHypothesis via deterministic Mock Core Inference (sync, BinaryMask)
- ConfirmObjectHypothesis → ConfirmationRecord + ConfirmedObject
- SaveProject / LoadProject with schema `"2.0"` gating
- Restore ConfirmedObject after reload
- Validation tests for empty and invalid intent payloads

Specified now, implementation deferred:

- UpdateArtistIntent

Excluded from first-slice implementation and acceptance gate:

- RejectHypothesis
- Extraction
- Real AI providers
- Depth / Pose
- Host plugins
- Phase 1 migration
- New production UI
- Repository reorganization

---

## 16. Summary

Application owns validation, confirmation, persistence, and Domain commits.  
Core Inference computes temporary hypotheses behind a provider port.  
Mock Core Inference enables a deterministic headless slice without real AI.  
Operation failure preserves the latest valid workflow state.  
Precision Extraction and RejectHypothesis remain specified for later slices.
