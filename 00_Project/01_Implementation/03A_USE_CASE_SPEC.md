# NOVA Layer

# 03A_USE_CASE_SPEC

Version: 0.2  
Status: Draft  
Document Type: Application Behaviour Specification

---

# 1. Purpose

This document defines the execution flow of the primary application use cases in NOVA Layer.

It specifies:

- Preconditions
- Execution Steps
- Postconditions
- Failure Behaviour

This document describes application behaviour only.

Public interfaces are defined in `03_ENGINE_INTERFACE_SPEC.md`.

Domain entities are defined in `02_DOMAIN_MODEL_SPEC.md`.

---

# 2. General Rules

Every mutating use case must follow the same execution pattern.

```text
Validate Request
        ↓
Validate Project State
        ↓
Execute Operation
        ↓
Validate Result
        ↓
Commit Domain Changes
        ↓
Return Response
```

A failed operation must never leave the project in a partially updated state.

A failed, cancelled, discarded, or obsolete operation must preserve the latest valid workflow state. Do not set workflow state to `Failed`, `Cancelled`, or `Empty`.

---

# 3. LoadSource

## Purpose

Load a source image into the current project.

## Preconditions

- Project exists
- Source image is accessible
- Supported image format

## Steps

1. Validate request
2. Load image
3. Validate image
4. Create SourceImage
5. Set Active Source
6. Clear source-dependent active entities
7. Return success

## Postconditions

- Active SourceImage exists
- Workflow state becomes `SourceReady`

## Failure

- Active source remains unchanged
- No partial data is committed

---

# 4. ReplaceSource

## Purpose

Replace the current source image.

## Preconditions

- Active SourceImage exists

## Steps

1. Load new source
2. Validate image
3. Create new SourceImage
4. Replace active source
5. Invalidate active Intent
6. Invalidate active Hypothesis
7. Invalidate active ConfirmedObject
8. Invalidate active ExtractionResult

## Postconditions

- New source becomes active
- Previous entities remain in history

## Failure

- Previous source remains active

---

# 5. CreateArtistIntent

## Purpose

Create the initial ArtistIntent when no active ArtistIntent exists.

## Preconditions

- Active SourceImage exists
- No active ArtistIntent exists

## Steps

1. Validate artist input (`positive_point` and optional `bounding_box` for the first slice)
2. Create ArtistIntent revision
3. Set active intent
4. Clear downstream active entities

## Postconditions

- Active ArtistIntent exists
- Workflow state becomes `IntentProvided`

## Failure

- No new revision is created
- Existing active state is not invalidated
- Workflow state is unchanged

---

# 6. UpdateArtistIntent

## Purpose

Create a new immutable ArtistIntent revision.

## Preconditions

- Active ArtistIntent exists

## Steps

1. Validate new input
2. Create a new immutable revision
3. Preserve the previous revision in history
4. Set the new revision as active
5. Invalidate the active ObjectHypothesis and all downstream active entities

## Postconditions

- Previous revision remains in history and is not mutated in place
- New revision becomes active

## Notes

- Do not recreate an updated intent through `CreateArtistIntent`.
- Specified now; implementation may be deferred until the next slice after the first vertical slice.

## Failure

- No new revision is created
- Existing active state is not invalidated

---

# 7. GenerateHypothesis

## Purpose

Generate an ObjectHypothesis using the active source and intent.

## Preconditions

- Active SourceImage exists
- Active ArtistIntent exists

## Steps

1. Validate inputs
2. Build inference request
3. Execute Core Inference Engine
4. Validate engine output
5. Create ObjectHypothesis
6. Set active hypothesis

## Postconditions

- Active ObjectHypothesis exists
- Workflow state becomes `HypothesisReady`

## Failure

- `OperationRecord.status` is `failed`
- No hypothesis is created or activated
- Latest valid workflow state is preserved (example: remains `IntentProvided`)
- Workflow state is not set to `Failed`

---

# 8. RejectHypothesis

## Purpose

Reject the current ObjectHypothesis.

## Preconditions

- Active ObjectHypothesis exists

## Steps

1. Mark hypothesis as rejected
2. Remove active hypothesis

## Postconditions

- Rejected hypothesis remains in history
- Artist may generate another hypothesis

## Notes

- Later MVP use case.
- Excluded from first-slice implementation and first-slice acceptance gate.

---

# 9. ConfirmHypothesis

## Purpose

Convert an ObjectHypothesis into a ConfirmedObject.

## Preconditions

- Active ObjectHypothesis exists
- Explicit user confirmation

## Steps

1. Validate hypothesis
2. Create ConfirmationRecord
3. Create ConfirmedObject
4. Set active confirmed object

## Postconditions

- ConfirmationRecord exists
- ConfirmedObject becomes active
- Workflow state becomes `ObjectConfirmed`

## Failure

- No confirmed object is created
- Latest valid workflow state is preserved

---

# 10. GenerateExtraction

## Purpose

Generate the final extraction result.

## Preconditions

- Active ConfirmedObject exists

## Steps

1. Execute Precision Extraction Engine
2. Validate result
3. Create ExtractionResult
4. Set active extraction result

## Postconditions

- ExtractionResult becomes active
- Workflow state becomes `ExtractionReady`

## Failure

- Previous extraction remains active
- Latest valid workflow state is preserved
- Workflow state is not set to `Failed`

---

# 11. SaveProject

## Purpose

Persist the current project.

## Preconditions

- Project is valid

## Steps

1. Validate project
2. Serialize metadata
3. Save assets
4. Save project file

## Postconditions

- Project can be reopened

## Failure

- Existing project file remains valid

---

# 12. LoadProject

## Purpose

Restore a saved project.

## Preconditions

- Project file exists

## Steps

1. Read `schema_version` first
2. Load project metadata for schema `"2.0"` only
3. Validate entities
4. Restore active references
5. Restore workflow state

## Postconditions

- Project is fully reconstructed

## Failure

- Current project remains unchanged
- Schema `"1.0"` and unknown versions return explicit errors without migration

---

# 13. Query Use Cases

The application shall provide read-only queries.

```text
GetCurrentState
GetActiveSource
GetActiveIntent
GetActiveHypothesis
GetActiveConfirmedObject
GetActiveExtractionResult
GetOperation
```

Queries must never modify project state.

---

# 14. Minimum Vertical Slice

The first implementation milestone shall support:

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

Excluded from this milestone: `RejectHypothesis`, `UpdateArtistIntent` implementation, Extraction, real AI, Depth, Pose, host plugins, Phase 1 migration, and new production UI.

This milestone validates the headless application workflow before integrating real AI providers.

