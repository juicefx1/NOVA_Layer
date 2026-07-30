# NOVA Layer

# 01_PHASE_1_IMPLEMENTATION_SPEC

Version : 1.0 Draft

Status : Internal

Author : Supernova Studios

---

# Purpose

This document converts Phase 1 of the Development Roadmap into an implementable prototype specification.

The prototype must validate the central product claim:

> An artist-confirmed Object Identity can remain consistent when propagated from a Master Frame toward both ends of a selected Shot Range.

Phase 1 is a validation prototype. It is not a production release.

---

# Phase 1 Scope

## Required

- Create or open a local prototype project.
- Import one supported video or image sequence.
- Represent one Sequence and one Shot.
- Define a Shot Range.
- Navigate the timeline and select any frame as the Master Frame.
- Create one Smart Layer for one intended object.
- Provide positive and negative point guidance and a bounding region.
- Generate and preview an Object Hypothesis.
- Accept, reject, or refine the hypothesis.
- Establish a confirmed Object Identity.
- Propagate the identity backward and forward.
- Validate the Start, Master, and End Frames.
- Display confidence and processing state.
- Stop on uncertainty instead of silently accepting identity drift.
- Generate preview extraction outputs.
- Save and restore the project and Smart Layer.

## Explicitly Out of Scope

- Multiple projects open at the same time.
- Multiple shots or multiple Smart Layers in the active workspace.
- Automatic shot detection.
- Full-sequence production-quality processing.
- Hair, fur, glass, smoke, and advanced transparency reconstruction.
- Distributed or cloud processing.
- Collaborative editing.
- DCC plug-ins and commercial packaging.
- Model training or fine-tuning.

The data model must remain compatible with future multi-sequence, multi-shot, and multi-layer workflows even though the Phase 1 interface exposes only one of each.

---

# User Workflow

Project Creation or Load

↓

Media Import

↓

Shot Range Definition

↓

Master Frame Selection

↓

Artist Guidance

↓

Initial Evidence Collection

↓

Object Hypothesis Generation

↓

Artist Confirmation or Refinement

↓

Confirmed Object Identity

↓

Backward and Forward Propagation

↓

Start / Master / End Validation

↓

Preview Extraction

↓

Smart Layer Save and Restore

---

# Functional Requirements

## P1-FR-001 Project Lifecycle

The application shall create, save, open, and restore a local NOVA Layer project without losing confirmed meaning or artist edits.

## P1-FR-002 Media Import

The application shall import one video or image sequence and record its source path, frame count, frame rate, resolution, and media fingerprint.

Missing or changed source media shall produce a recoverable relink state.

## P1-FR-003 Shot Range

The artist shall select inclusive start and end frames. The application shall reject an invalid or empty range.

## P1-FR-004 Master Frame

The artist shall select any frame inside the Shot Range as the Master Frame.

## P1-FR-005 Artist Guidance

The Master Frame shall accept positive points, negative points, and a bounding region. Guidance shall remain editable and be stored as Artist Intent.

## P1-FR-006 Object Hypothesis

The system shall generate a hypothesis mask and confidence information from Artist Intent and available evidence.

The hypothesis shall not become Object Identity automatically.

## P1-FR-007 Confirmation

The artist shall be able to accept, reject, or refine the Object Hypothesis. Only acceptance establishes a Confirmed Object Identity.

## P1-FR-008 Bidirectional Propagation

The system shall propagate from the confirmed Master Frame independently toward the Shot Range start and end.

Propagation shall update the existing Object Identity rather than create a new identity.

## P1-FR-009 Validation

The application shall present Start, Master, and End validation frames together with mask overlays and confidence states.

The artist shall confirm or correct each validation result.

## P1-FR-010 Failure Handling

Propagation shall pause when confidence falls below a configurable threshold or when a capability reports ambiguity, loss, or incompatible output.

## P1-FR-011 Correction and Re-Propagation

An accepted correction shall be stored as high-priority evidence. Only the affected temporal direction or range shall be invalidated and recomputed.

## P1-FR-012 Preview Extraction

The system shall generate a preview alpha, foreground preview, and matte overlay for the three validation frames.

These outputs are derivatives and are not the authoritative Smart Layer asset.

## P1-FR-013 Persistence

The saved project shall restore the hierarchy, media references, Shot Range, Master Frame, Artist Intent, Object Identity, evidence history, reasoning decisions, validation state, capability provenance, and preview outputs.

---

# Application Areas

## Welcome

- Create Project
- Open Project
- Recent Projects

## Import

- Select media
- Display detected metadata
- Report unsupported media clearly

## Workspace

- Viewer with image, mask, and matte overlay modes
- Timeline with Shot Range handles
- Current-frame indicator
- Master Frame marker
- Smart Layer panel
- Artist Guidance tools
- Processing and confidence panel
- Save state indicator

## Hypothesis Review

- Proposed mask preview
- Accept
- Reject
- Add positive guidance
- Add negative guidance
- Replace bounding region
- Regenerate

## Validation Review

- Start, Master, and End frame comparison
- Per-frame confidence and validation state
- Accept or correct
- Re-propagate affected range

---

# Domain Model

## Project

- id
- name
- schema_version
- created_at
- updated_at
- settings
- sequences

## Sequence

- id
- name
- shots

## Shot

- id
- name
- media_reference
- media_metadata
- range_start
- range_end
- master_frame
- smart_layers

## Smart Layer

- id
- name
- object_identity
- artist_intent
- evidence_history
- reasoning_history
- validation_history
- extraction_settings
- preview_outputs
- capability_provenance
- version

## Object Identity

- id
- maturity_state
- confirmed_subject_reference
- appearance_features
- structural_features
- boundary_reference
- confidence_state
- lifecycle_state

## Artist Intent

- positive_points
- negative_points
- bounding_region
- corrections
- master_frame_reference

## Frame Result

- frame_number
- direction
- mask_reference
- confidence
- status
- evidence_references
- capability_run_reference

---

# State Models

## Object Lifecycle State

Not Detected → Candidate → Confirmed → Tracked → Temporarily Lost → Recovered → Completed

## Identity Maturity State

Hypothesis → Confirmed → Validated

`Production Ready` and `Persistent` belong to later phase completion. Phase 1 may serialize a Validated identity, but must not label preview extraction as production ready.

## Processing State

Idle → Preparing → Running → Awaiting Artist → Completed

Any running state may transition to Paused, Failed, or Cancelled.

---

# Capability Contracts

Phase 1 shall depend on capabilities rather than named AI models.

## Interactive Segmentation Capability

Input:

- Master Frame image
- Positive points
- Negative points
- Optional bounding region

Output:

- Candidate mask
- Confidence
- Capability provenance
- Optional alternate candidates

## Temporal Propagation Capability

Input:

- Confirmed reference frame and mask
- Target frames
- Direction
- Existing Object Identity context

Output:

- Frame masks
- Per-frame confidence
- Lost or ambiguous state
- Capability provenance

## Preview Extraction Capability

Input:

- Frame image
- Validated mask
- Preview settings

Output:

- Preview alpha
- Foreground preview
- Matte overlay

Each capability adapter shall expose a stable interface, report its version, and fail without corrupting the Smart Layer.

---

# Persistence Format

The initial implementation should use a readable, versioned project manifest with referenced binary assets.

Suggested prototype package:

```text
project.nova/
├── manifest.json
├── evidence/
├── masks/
├── previews/
├── cache/
└── logs/
```

`manifest.json` is authoritative for semantic state. Cache files and generated previews may be deleted and rebuilt.

Every manifest shall include `schema_version`. Unknown incompatible versions must fail safely without overwriting the project.

Project saving shall use an atomic temporary-write-and-replace strategy.

---

# Evidence and Reasoning Records

Every important decision shall be traceable.

An Evidence Record shall include:

- id
- source type
- frame number
- payload reference
- confidence
- created time
- capability provenance or artist source

A Reasoning Record shall include:

- id
- input evidence references
- decision
- confidence
- previous and resulting identity state
- whether artist confirmation is required
- created time

Artist confirmation and correction records always have higher authority than automatic model evidence.

---

# Error and Recovery Requirements

- Unsupported media shall not create a partial project state.
- Missing source media shall enter Relink Required state.
- Capability initialization failure shall identify the unavailable capability.
- Out-of-memory failure shall preserve the last valid state.
- Cancellation shall preserve confirmed results and discard incomplete frame results.
- Identity drift or ambiguity shall pause for artist review.
- Save failure shall never replace the last valid project package.
- Corrupt cache files shall be rebuildable from authoritative project state.

---

# Non-Functional Requirements

## Reliability

- No automatic result may overwrite artist-confirmed guidance.
- Autosave shall occur after confirmation, correction, and completed propagation.
- Long-running operations shall be cancellable.

## Responsiveness

- Timeline navigation and guidance editing shall remain interactive while processing runs in the background.
- Progress shall report direction, current frame, completed frames, and current state.

## Reproducibility

- Every generated result shall record the capability identifier, adapter version, model identifier when applicable, settings, and source frame reference.

## Portability

- Platform-specific paths shall not be embedded as the only media identity.
- Project packages shall support media relinking.

---

# Acceptance Test Set

## P1-AT-001 Basic Flow

Import a short shot, select a middle Master Frame, confirm one object, propagate to both ends, validate all three frames, save, close, and restore successfully.

## P1-AT-002 Non-Zero Shot Range

Define a range that begins after the first media frame and ends before the last. Processing must remain inside the selected range.

## P1-AT-003 Backward Propagation

Select a Master Frame near the end of the range. The object must propagate toward earlier frames without creating another Object Identity.

## P1-AT-004 Forward Propagation

Select a Master Frame near the beginning. The object must propagate toward later frames while retaining the same identity identifier.

## P1-AT-005 Ambiguity Stop

Use a shot containing a similar distractor or occlusion. The system must pause or flag uncertainty instead of silently switching identity.

## P1-AT-006 Correction

Correct one failed validation frame. The correction must be stored as artist evidence and re-propagation must affect only the required temporal region.

## P1-AT-007 Persistence

Restore the saved project and verify identical hierarchy identifiers, Shot Range, Master Frame, Artist Intent, maturity state, and validation decisions.

## P1-AT-008 Missing Media

Move the source media, reopen the project, relink it, and recover the prior Smart Layer state.

## P1-AT-009 Capability Failure

Simulate an unavailable capability. The project must remain open, editable, and saveable without state corruption.

---

# Definition of Done

Phase 1 implementation is complete only when:

- P1-FR-001 through P1-FR-013 are implemented.
- P1-AT-001 through P1-AT-009 pass with recorded evidence.
- The same Object Identity identifier is preserved across Start, Master, and End validation frames.
- Artist confirmation is required before propagation.
- Low-confidence propagation cannot silently become validated state.
- A saved Smart Layer restores without semantic data loss.
- Capability adapters can be replaced without changing the domain model.
- Known limitations and failed test cases are documented.

---

# Implementation Gates

## Gate 1 - Technology Baseline

Choose the desktop application stack, supported operating system, media pipeline, GPU backend, and project serialization library.

## Gate 2 - Vertical Slice

Implement project creation, media import, timeline navigation, Shot Range, and Master Frame selection with no AI dependency.

## Gate 3 - Interactive Hypothesis

Integrate one Interactive Segmentation adapter and complete artist confirmation.

## Gate 4 - Bidirectional Validation

Integrate one Temporal Propagation adapter and validate Start, Master, and End Frames.

## Gate 5 - Persistence

Save, restore, relink, and safely migrate the Phase 1 project package.

## Gate 6 - Prototype Acceptance

Run the complete acceptance test set on representative shots and record limitations.
