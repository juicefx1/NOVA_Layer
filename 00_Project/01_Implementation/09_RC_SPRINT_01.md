# RC Sprint 1

## Status

Approved.

---

# Goal

Prepare NOVA Layer for Release Candidate.

This sprint introduces no new product features.

Only release blockers may be addressed.

---

# Rules

Do NOT change:

- Domain
- Schema 2.0
- Product Features
- Plugin SDK
- Automation API

Only improve implementation quality.

---

# Sprint Items

## RC-01 Runtime Lifecycle

Implement coordinated shutdown.

Requirements:

- ObjectWorkflowController.shutdown()
- ObjectWorkflowService.shutdown()
- OperationExecutor shutdown
- Plugin cleanup
- Temporary workspace cleanup
- GPU session cleanup
- Thread pool shutdown

No resource leaks.

---

## RC-02 Workspace Completion

Complete Product Feature 10.

Implement:

- Restore Workspace
- Recent Projects
- Window Geometry
- Dock Layout
- Active Project Restore

WorkspaceManager remains the single application Workspace.

---

## RC-03 Atomic Workspace Save

Workspace persistence must match Project persistence.

Implement:

- temporary file
- fsync if appropriate
- atomic replace

Corruption must never destroy the previous workspace.

---

## RC-04 CI

Create GitHub Actions workflow.

Run:

- Ruff
- pytest (offline)
- Optional coverage

No code style regressions.

---

## RC-05 Documentation

Complete:

- ARCHITECTURE.md
- 07_ARCHITECTURE_DECISIONS.md
- Product Feature 12 specification

Documentation must reflect the implemented architecture.

---

# Out of Scope

No new product features.

No performance optimisation.

No UI redesign.

---

# Acceptance

Sprint complete when:

- shutdown lifecycle implemented
- workspace restore completed
- atomic workspace persistence implemented
- CI pipeline passes
- documentation updated
- regression passes

---

# Completion Report

Return:

1. Files Created
2. Files Modified
3. Runtime Lifecycle
4. Workspace Completion
5. Persistence
6. CI
7. Documentation
8. Regression
9. Remaining RC Blockers
10. Release Readiness

