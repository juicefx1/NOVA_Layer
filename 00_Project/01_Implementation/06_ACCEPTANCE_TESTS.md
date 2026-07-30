# NOVA Layer

# 06_ACCEPTANCE_TESTS

Version: 0.3  
Status: Draft  
Document Type: Acceptance Specification

---

# 1. Purpose

This document defines the acceptance criteria for the NOVA Layer object-workflow MVP milestone.

An implementation is considered complete for a given gate only when the tests for that gate pass.

These tests validate observable application behaviour rather than implementation details.

---

# 2. Acceptance Principles

Acceptance tests shall verify:

- Application workflow
- Domain consistency
- Workflow progression
- Data persistence
- Error handling
- Engine abstraction

Implementation details are not part of acceptance.

Operation failure and workflow state are separate. Do not expect workflow states named `Empty`, `Failed`, or `Cancelled`.

---

# 3. First-Slice Acceptance Gate

The following sections marked **First Slice** must pass for the first vertical slice.

Sections marked **Later** are retained for the broader MVP and are not required to pass the first-slice gate.

---

# 4. Project Creation — First Slice

## Test

Create a new project.

## Expected Result

- Project is created with `schema_version = "2.0"`.
- Project state matches NoSource initial conditions.
- No active entities exist.
- Workflow state is `NoSource`.

---

# 5. Source Loading — First Slice

## Test

Load a valid PNG or JPEG source image.

## Expected Result

- SourceImage is created.
- SourceImage becomes active.
- `content_fingerprint` is the lowercase hex SHA-256 of the original file bytes.
- Workflow state becomes `SourceReady`.

---

## Test

Load an unsupported image.

## Expected Result

- Operation fails.
- No SourceImage is created.
- Previous state is preserved.
- Workflow state is unchanged.

---

# 6. Source Replacement — Later

## Test

Replace the active source.

## Expected Result

- New SourceImage becomes active.
- Previous SourceImage remains in history.
- Active Intent is cleared.
- Active Hypothesis is cleared.
- Active ConfirmedObject is cleared.
- Active ExtractionResult is cleared.

---

# 7. Artist Intent — First Slice

## Test

Create a valid ArtistIntent with at least one `positive_point` and optional `bounding_box`.

## Expected Result

- ArtistIntent is created.
- ArtistIntent becomes active.
- Workflow state becomes `IntentProvided`.

---

## Test

Create ArtistIntent with an empty payload.

## Expected Result

- Validation fails.
- No new ArtistIntent revision is created.
- Existing active state is not invalidated.
- Workflow state is unchanged.

---

## Test

Create ArtistIntent with invalid geometry (point or box outside bounds, or non-positive box size).

## Expected Result

- Validation fails.
- No new ArtistIntent revision is created.
- Existing active state is not invalidated.

---

## Test

Create ArtistIntent with an unsupported signal type.

## Expected Result

- Explicit validation error is returned.
- No new ArtistIntent revision is created.
- Existing active state is not invalidated.

---

# 8. Update ArtistIntent — Later

## Test

Update ArtistIntent.

## Expected Result

- New immutable revision is created via `UpdateArtistIntent`.
- Previous revision remains in history.
- Downstream active entities are invalidated.
- Previous revisions are not mutated in place.

---

# 9. Hypothesis Generation — First Slice

## Test

Generate an ObjectHypothesis with the Mock Core Inference Engine.

## Expected Result

- ObjectHypothesis is created.
- ObjectHypothesis becomes active.
- Mask is BinaryMask: source W×H, 1 channel, uint8, background 0, foreground 255.
- Identical inputs produce a deterministic mask.
- Workflow state becomes `HypothesisReady`.

---

## Test

Generate with engine/inference failure.

## Expected Result

- `OperationRecord.status` is `failed`.
- No ObjectHypothesis is created or activated.
- Latest valid workflow state is preserved (example: remains `IntentProvided`).
- Workflow state is not set to `Failed`.

---

# 10. Hypothesis Rejection — Later

## Test

Reject the active hypothesis.

## Expected Result

- Hypothesis remains in history with rejected status.
- Active hypothesis is cleared.
- New hypothesis may be generated.

Excluded from the first-slice acceptance gate.

---

# 11. Explicit Confirmation — First Slice

## Test

Confirm an ObjectHypothesis.

## Expected Result

- ConfirmationRecord is created.
- ConfirmedObject is created.
- ConfirmedObject becomes active.
- Workflow state becomes `ObjectConfirmed`.

---

# 12. Extraction — Later

## Test

Generate ExtractionResult.

## Expected Result

- ExtractionResult is created.
- ExtractionResult becomes active.
- Workflow state becomes `ExtractionReady`.

---

## Test

Attempt extraction without confirmation.

## Expected Result

- Extraction is rejected.
- No ExtractionResult is created.

---

# 13. Save Project — First Slice

## Test

Save project after ObjectConfirmed.

## Expected Result

- Project is written successfully with `schema_version = "2.0"`.
- Saved project can be reopened.

---

## Test

Save failure.

## Expected Result

- Existing project remains valid.
- No corrupted project is produced.

---

# 14. Load Project — First Slice

## Test

Load a valid schema `"2.0"` project.

## Expected Result

- Project is reconstructed.
- Active SourceImage is restored.
- Active ArtistIntent is restored.
- Active ConfirmedObject is restored.
- Workflow state is restored (`ObjectConfirmed` for the approved happy path).

---

## Test

Load a schema `"1.0"` or unknown project.

## Expected Result

- Load fails with an explicit error.
- Current project remains unchanged.
- No automatic migration occurs.

---

# 15. Workflow Validation — First Slice

The following workflow must execute successfully.

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
Confirm Hypothesis
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

Expected Result

- Every step succeeds.
- Workflow state progresses:

```text
NoSource → SourceReady → IntentProvided → HypothesisReady → ObjectConfirmed
```

- No unexpected state transition occurs.
- `RejectHypothesis`, `UpdateArtistIntent`, and Extraction are not required.

---

# 16. Domain Validation — First Slice

After the happy-path workflow:

- One active SourceImage
- One active ArtistIntent
- One active ObjectHypothesis
- One active ConfirmationRecord
- One active ConfirmedObject
- Active ExtractionResult remains null

Historical entities must remain accessible.

---

# 17. Engine Independence — Later

Replace the Mock Engine with a Real Engine.

Expected Result

- No Domain changes.
- No Application workflow changes.
- Engine replacement requires configuration only.

Not required for the first-slice gate.

---

# 18. Persistence Validation — First Slice

Save and reload a confirmed project.

Expected Result

The following entities are preserved:

- Project
- SourceImage
- ArtistIntent
- ObjectHypothesis
- ConfirmationRecord
- ConfirmedObject
- OperationRecord

All relationships remain valid.

ExtractionResult is not required for the first-slice gate.

---

# 19. Failure Recovery — First Slice

Force failures during:

- Source loading
- Hypothesis generation
- Saving

Expected Result

- Project remains valid.
- No partial state becomes active.
- Previous valid workflow state is preserved.
- Failed operations are recorded on `OperationRecord` only.

---

# 20. First-Slice Acceptance

The first vertical slice is accepted when:

- All **First Slice** tests in this document pass.
- The approved workflow in §15 executes successfully.
- State persistence of ConfirmedObject is verified.
- No architectural rule defined by the implementation documents is violated.

Broader MVP acceptance, including UpdateArtistIntent, RejectHypothesis, Extraction, and real AI replacement, is deferred to later gates.
