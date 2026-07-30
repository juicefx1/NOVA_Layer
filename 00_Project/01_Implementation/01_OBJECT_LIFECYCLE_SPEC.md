# NOVA Layer

# 01_OBJECT_LIFECYCLE_SPEC

Version: 0.1  
Status: Draft  
Document Type: Behaviour Specification

---

## 1. Purpose

This document defines the lifecycle of an object inside NOVA Layer.

It specifies:

- Object workflow states
- Valid state transitions
- Invalid state transitions
- Artist confirmation behaviour
- Failure and recovery behaviour
- State persistence requirements
- Lifecycle invariants

This document is the authority for object workflow state.

---

## 2. Core Principle

The object lifecycle must preserve the following rule:

> AI proposes.  
> The artist decides.  
> AI executes.

An AI-generated Object Hypothesis must never become a Confirmed Object without explicit artist confirmation.

---

## 3. Lifecycle Scope

This specification applies to the MVP workflow for:

- A single project
- A single source image
- A single intended object
- A single active Object Hypothesis
- A single Confirmed Object
- A single latest Extraction Result

This specification does not yet define:

- Multiple objects
- Video tracking
- Temporal object identity
- Shared object identities across shots
- Collaborative confirmation
- Object version merging
- Automatic batch approval

---

## 4. Lifecycle Entities

The lifecycle operates on the following domain entities:

- `Project`
- `SourceImage`
- `ArtistIntent`
- `ObjectHypothesis`
- `ConfirmedObject`
- `ExtractionResult`
- `OperationRecord`

Detailed fields are defined in `02_DOMAIN_MODEL_SPEC.md`.

---

## 5. Object Workflow States

The MVP defines the following workflow states.

### 5.1 `NoSource`

No valid source image has been loaded.

The project cannot accept artist intent or request inference.

---

### 5.2 `SourceReady`

A valid source image has been loaded.

The system is ready to receive artist intent.

---

### 5.3 `IntentProvided`

The artist has provided valid intent for the intended object.

Intent may contain:

- Positive regions
- Negative regions
- Selection points
- Selection strokes
- Bounding regions

The exact MVP input format is defined elsewhere.

---

### 5.4 `HypothesisReady`

A valid Object Hypothesis has been generated and is available for artist review.

The hypothesis remains unconfirmed.

The artist may:

- Confirm it
- Reject it (later use case; excluded from the first vertical slice gate)
- Modify intent via `UpdateArtistIntent` (specified; implementation may be deferred)
- Request regeneration

In-flight inference is not a workflow state. Concurrent-request and cancellation rules belong to operation handling, not to a persistent `HypothesisGenerating` state.

---

### 5.5 `HypothesisRejected`

The artist has explicitly rejected the current Object Hypothesis.

The rejected hypothesis may remain stored for history and diagnostics.

It must not be used for extraction.

This state supports a later MVP use case. It is outside the first vertical slice acceptance gate.

---

### 5.6 `ObjectConfirmed`

The artist has explicitly approved an Object Hypothesis.

A Confirmed Object now exists.

This state represents trusted object identity.

The confirmation event must be stored explicitly as a ConfirmationRecord.

---

### 5.7 `ExtractionReady`

A valid Extraction Result exists.

The result must remain associated with:

- The source image
- The confirmed object
- The confirmed hypothesis version
- The extraction provider
- The extraction operation

`ExtractionReady` remains in the complete specification and is outside the first vertical slice.

In-flight extraction is not a workflow state. Do not use a persistent `ExtractionGenerating` workflow state.

---

### 5.8 Operation Failure (not a workflow state)

The latest requested operation may fail, cancel, be discarded, or become obsolete.

Failure does not automatically invalidate the last valid state.

The project must preserve:

- The last valid workflow state
- The failed, cancelled, or discarded operation record
- Recoverability information
- A human-readable failure message

Do not use `Failed`, `Cancelled`, or `Empty` as workflow states. Those outcomes belong to `OperationRecord.status` (and related operation handling), not to workflow state.

---

## 6. State Model

Canonical workflow states for the approved first slice:

```text
NoSource
    ↓
SourceReady
    ↓
IntentProvided
    ↓
HypothesisReady
    ↓
ObjectConfirmed
```

Complete specification may additionally use:

```text
HypothesisRejected   (later use case)
ExtractionReady      (outside first slice)
```

Forbidden as workflow states: `Empty`, `Failed`, `Cancelled`, `HypothesisGenerating`, `ExtractionGenerating`.
