# RC Sprint 2

## Status

Approved.

---

# Goal

Improve product quality without changing product behaviour.

No new user-facing features.

No Domain changes.

No Schema changes.

---

# Rules

Must preserve:

- Domain
- Schema 2.0
- Runtime Architecture
- Plugin SDK
- Automation
- Workspace
- Batch Workflow

Only implementation quality may improve.

---

# Sprint Items

## RC-06 Performance

Improve runtime efficiency.

Requirements:

- Batch image cache integration
- Avoid unnecessary image copies
- Improve inference reuse
- Improve cache hit rate
- Remove obvious allocation hotspots

Do not change inference results.

---

## RC-07 Runtime Cleanup

Improve lifecycle.

Requirements:

- Stable engine identity
- Cleanup after Batch
- Cleanup after Automation
- Remove completed operation history
- Bound long-lived caches

---

## RC-08 Security Hardening

Improve safety.

Requirements:

- Reject plugin symlinks
- Improve package validation
- Harden workspace persistence
- Improve export path validation

---

## RC-09 UX

Improve recovery.

Requirements:

- Better error messages
- Retry guidance
- Workspace recovery dialog
- Plugin installation feedback
- Cancellation feedback

No redesign.

---

## RC-10 Testing

Expand:

- Concurrency tests
- Batch stress
- Plugin package adversarial tests
- Automation race conditions
- Workspace recovery tests

---

# Out of Scope

No new Features.

No new APIs.

No architecture redesign.

---

# Acceptance

Sprint complete when:

- Performance improvements merged
- Security improvements merged
- UX improvements merged
- Additional tests pass
- No regressions

---

# Completion Report

Return:

1. Files Created
2. Files Modified
3. Performance Improvements
4. Runtime Improvements
5. Security Improvements
6. UX Improvements
7. Tests Added
8. Regression Results
9. Remaining Release Risks
10. Updated Release Readiness

