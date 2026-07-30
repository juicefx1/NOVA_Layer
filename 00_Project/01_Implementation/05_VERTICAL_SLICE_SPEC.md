# NOVA Layer

# 05_VERTICAL_SLICE_SPEC

Version: 0.3  
Status: Draft  
Document Type: Implementation Roadmap

---

# 1. Purpose

This document defines the implementation order of the object-workflow bounded context.

Development shall proceed in small, testable vertical slices.

Each slice must produce a working application increment.

No slice may depend on unfinished future features.

---

# 2. Vertical Slice Principles

Each slice should include the layers required for that increment:

- Application
- Domain
- Engine (or Mock Engine)
- Infrastructure
- Tests

Presentation / production UI is not required for the first approved slice.

Every slice must be executable.

Every slice must leave the application in a valid state.

---

# 3. Approved First Vertical Slice

The approved first slice is:

```text
Create Project
        ↓
Load Source
        ↓
Create ArtistIntent
        ↓
Generate ObjectHypothesis
  (deterministic Mock Core Inference)
        ↓
Explicitly Confirm Hypothesis
        ↓
Create ConfirmationRecord
        ↓
Create ConfirmedObject
        ↓
Save Project (schema_version "2.0")
        ↓
Load Project
        ↓
Restore ConfirmedObject state
```

Canonical workflow states exercised by this slice:

- `NoSource`
- `SourceReady`
- `IntentProvided`
- `HypothesisReady`
- `ObjectConfirmed`

Do not use `Empty`, `Failed`, or `Cancelled` as workflow states.

---

# 4. First-Slice Exclusions

Excluded from first-slice implementation and acceptance gate:

- `RejectHypothesis` implementation
- `UpdateArtistIntent` implementation
- Extraction
- Real AI providers
- Depth
- Pose
- Host plugins
- Phase 1 migration
- New production UI
- Repository reorganization

`UpdateArtistIntent` must remain specified in `03_ENGINE_INTERFACE_SPEC.md` and `03A_USE_CASE_SPEC.md`, but its implementation may be deferred until the next slice.

`RejectHypothesis` may remain documented as a later MVP use case.

---

# 5. Slice 1 — Project Creation

## Goal

Create a schema `"2.0"` project in `NoSource`.

## Features

- Create Project
- Project initialization
- NoSource workflow state

## Completion Criteria

- Project can be created.
- Project has valid initial state (`NoSource`, empty histories, null actives).

---

# 6. Slice 2 — Source Management

## Goal

Support loading a PNG or JPEG source image.

## Features

- Load Source
- Source validation
- SHA-256 `content_fingerprint` from original file bytes

## Completion Criteria

- SourceImage is created.
- Active SourceImage exists.
- Invalid or unsupported images are rejected.
- Workflow state becomes `SourceReady`.

Source replacement may be specified for later slices; it is not required to pass the first-slice acceptance gate.

---

# 7. Slice 3 — Artist Intent (Create only)

## Goal

Capture the first artist intent.

## Features

- CreateArtistIntent
- Intent validation for `positive_point` and optional `bounding_box`
- Empty and invalid payload rejection without state mutation

## Completion Criteria

- ArtistIntent can be created when none is active.
- Workflow state becomes `IntentProvided`.
- Empty or invalid payloads create no revision and do not invalidate actives.

`UpdateArtistIntent` is deferred to the next slice after this first gate.

---

# 8. Slice 4 — Mock Hypothesis Generation

## Goal

Validate the workflow without real AI.

## Features

- Deterministic Mock Core Inference Engine
- Generate ObjectHypothesis
- Operation tracking
- Inference failure preserves latest valid workflow state

## Completion Criteria

- Hypothesis is generated with canonical BinaryMask (W×H, 1ch, uint8, 0/255).
- Active hypothesis is set.
- Workflow state becomes `HypothesisReady`.
- Failed generation records `OperationRecord.status = failed` and preserves e.g. `IntentProvided`.
- No real AI provider is required.

---

# 9. Slice 5 — Confirmation

## Goal

Support explicit confirmation.

## Features

- Confirm Hypothesis
- ConfirmationRecord
- ConfirmedObject

## Completion Criteria

- Explicit confirmation is required.
- ConfirmedObject is created.
- Workflow reaches `ObjectConfirmed`.

---

# 10. Slice 6 — Persistence Round-Trip

## Goal

Persist and restore confirmed object state.

## Features

- Save Project (`schema_version "2.0"`)
- Load Project
- Reject schema `"1.0"` / unknown versions
- State reconstruction including ConfirmedObject

## Completion Criteria

- Project can be saved.
- Project can be reopened.
- Active ConfirmedObject state is restored.

---

# 11. Later Slices (not first-slice gate)

Later slices may include, in an order to be scheduled after the first gate:

- UpdateArtistIntent
- RejectHypothesis
- Source replacement
- Mock Extraction / ExtractionReady
- Real AI Integration
- Production UI

---

# 12. Definition of Done (First Slice)

The first slice is complete only if:

- Code compiles.
- First-slice acceptance tests in `06_ACCEPTANCE_TESTS.md` pass.
- Headless Application workflow functions correctly.
- No placeholder logic remains, except the approved Mock Core Inference Engine.
- Documentation is updated if behaviour changes.

---

# 13. Mock Engine Policy

Mock Engines are implementation tools.

They must:

- Produce deterministic output.
- Be independent of external AI providers.
- Support automated testing.
- Implement the same Engine Interface as real providers.
- Return engine-neutral BinaryMask results.

Application code must not distinguish between Mock and Real engines.

---

# 14. Package Location

Implement under:

```text
02_Source/src/nova_layer/object_workflow/
```

with logical areas equivalent to domain, application, ports, and adapters.

Do not introduce an `mvp` namespace.

Do not move or rename Phase 1 code.

---

# 15. Success Criteria (First Slice)

The first vertical slice is successful when the approved workflow in §3 executes end-to-end with schema `"2.0"` persistence and ConfirmedObject restoration.
