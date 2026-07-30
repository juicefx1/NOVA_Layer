# Product Feature 11 — Batch Workflow

## Status

Approved for implementation.

---

# Goal

Introduce a Batch Workflow that executes the existing NOVA Layer pipeline across multiple images while preserving the single-image workflow.

Batch orchestration must reuse the existing architecture and never introduce a separate processing pipeline.

---

# Architectural Authority

Must preserve:

- ARCHITECTURE.md
- Domain
- Schema 2.0
- Workspace
- Plugin SDK
- Runtime Architecture
- OperationExecutor
- Existing Providers

---

# Design Philosophy

Batch processing is an orchestration layer.

Each image executes the same workflow:

Image

↓

Inference

↓

Candidate

↓

Confirmation

↓

Extraction

↓

Host Export

Batch repeats this pipeline.

---

# BatchJob

BatchJob is a Runtime object.

It contains:

- Job ID
- Image List
- Queue
- Statistics
- Progress
- Status

Never stored in Project persistence.

---

# Queue

Each image supports:

- Waiting
- Running
- Completed
- Failed
- Cancelled
- Skipped

Queue ordering is deterministic.

---

# Runtime Reuse

Batch processing reuses:

- Runtime Cache
- Plugin Instances
- ONNX Sessions
- Neural Matting Sessions
- Host Adapters

Never duplicate expensive initialization.

---

# ArtistIntent

One immutable ArtistIntent snapshot is shared by the batch.

Images never modify ArtistIntent.

---

# Confirmation

Batch never bypasses confirmation.

Only Confirmed objects are extracted.

---

# Extraction

Use PrecisionExtractionPort unchanged.

No Batch Extraction Port.

---

# Host Integration

Use existing Host Adapter architecture.

No Batch Host Adapter.

---

# Cancellation

Cancelling a Batch:

- cancels active OperationExecutor
- prevents queued jobs

Completed jobs remain committed.

---

# Retry

Support:

- Retry Failed
- Retry Cancelled

Never rerun successful jobs automatically.

---

# Statistics

Expose:

- Completed
- Failed
- Cancelled
- Remaining
- Average Time
- ETA (optional)

---

# Logging

Provide:

- Per-image log
- Batch summary
- Failure summary

---

# Workspace Integration

Workspace restores:

- Recent Batch History
- Queue Metadata

Runtime execution is never restored.

---

# UI

Add:

- Batch Queue
- Progress
- Current Image
- Retry Failed
- Cancel Batch
- Batch Summary

---

# Testing

Add tests:

- Queue
- Retry
- Cancellation
- Runtime Reuse
- Plugin Reuse
- Mixed Success
- Workspace Restore
- Regression

---

# Regression

Features 1–10 must remain unchanged.

---

# Out of Scope

- Distributed workers
- Cloud execution
- Cluster scheduling
- Priority queues

---

# Acceptance Criteria

Feature is complete when:

- BatchManager implemented
- Queue implemented
- Retry implemented
- Cancellation implemented
- Runtime reuse verified
- Plugin reuse verified
- Workspace integration completed
- Regression suite passes

---

# Completion Report

Return:

1. Public API Compatibility
2. Files Created
3. Files Modified
4. BatchManager Architecture
5. Queue Design
6. Runtime Reuse
7. Plugin Integration
8. Workspace Integration
9. UI Changes
10. Tests Added
11. Regression Results
12. Remaining Limitations
13. Final Readiness Verdict

