# Final Release Candidate Audit

## Status

Approved for review.

---

# Purpose

Determine whether NOVA Layer qualifies as a v1.0 Release Candidate after RC Sprint 1 and RC Sprint 2.

This is a verification phase.

Do not introduce new features.

Do not redesign architecture.

Do not modify code during the initial audit.

---

# Architectural Authority

Review against:

- ARCHITECTURE.md
- Product Features 1–13
- 09_RC_SPRINT_01.md
- 10_RC_SPRINT_02.md
- Release Readiness Review
- Current implementation and test suite

---

# Audit Rules

The reviewer must:

- inspect the actual implementation
- verify previous RC claims
- distinguish verified facts from assumptions
- identify unresolved release blockers
- classify every finding by severity
- avoid code changes during the audit

Severity:

- Critical
- High
- Medium
- Low
- Accepted Risk

---

# Gate 1 — Architecture

Verify:

- Domain dependency purity
- Application and adapter dependency direction
- No competing Workspace architecture
- No duplicate workflow implementation
- Plugin and Automation boundaries
- Runtime ownership and shutdown paths
- No circular dependencies

Result:

- Pass
- Conditional Pass
- Fail

---

# Gate 2 — Domain and Schema

Verify:

- Domain unchanged by RC work
- Schema 2.0 compatibility
- Confirmed-object binding
- Interactive confirmation remains default
- Persistence round trips
- Existing project compatibility

Result:

- Pass
- Conditional Pass
- Fail

---

# Gate 3 — Runtime Lifecycle

Verify:

- Controller shutdown
- Service shutdown
- Executor shutdown
- Automation shutdown
- Plugin cleanup
- Temporary directory cleanup
- Thread-pool cleanup
- Cache cleanup
- GPU and inference-session lifecycle

Result:

- Pass
- Conditional Pass
- Fail

---

# Gate 4 — Workspace

Verify:

- Application-lifetime WorkspaceManager
- Atomic save
- Backup recovery
- Corrupt-workspace handling
- Recent projects
- Active-project restore
- Window geometry
- Dock layout
- Preferences
- Plugin state restore

Result:

- Pass
- Conditional Pass
- Fail

---

# Gate 5 — Batch

Verify:

- Interactive mode is default
- Explicit automatic-confirmation opt-in
- Confirmed-object binding
- Cancellation
- Retry
- Runtime reuse
- Source-cache use
- Post-run cleanup
- Large-batch behaviour

Result:

- Pass
- Conditional Pass
- Fail

---

# Gate 6 — Plugin System

Verify:

- SDK compatibility
- Package validation
- ZIP traversal protection
- ZIP symlink rejection
- Entry-module validation
- Install/update/uninstall
- Workspace integration
- Restart-required behaviour is documented
- No remote downloads

Result:

- Pass
- Conditional Pass
- Fail

---

# Gate 7 — Automation

Verify:

- Existing service reuse
- Permission enforcement
- Event ordering
- Cancellation race resolution
- Bounded operation history
- Future cleanup
- Plugin command isolation
- Shutdown behaviour

Result:

- Pass
- Conditional Pass
- Fail

---

# Gate 8 — Performance

Verify:

- Inference-session reuse
- SAM2 image fingerprint reuse
- Batch cache integration
- Cache memory limits
- Read-only shared frames
- Operation-history bounds
- No obvious unbounded growth
- Large-image and large-batch risk

Result:

- Pass
- Conditional Pass
- Fail

---

# Gate 9 — Security

Verify:

- Project path safety
- Export path safety
- Plugin archive traversal rejection
- Plugin symlink rejection
- Workspace atomic persistence
- Plugin failure isolation
- Automation permission boundaries
- Local-only plugin trust assumptions documented

Result:

- Pass
- Conditional Pass
- Fail

---

# Gate 10 — Testing and CI

Verify:

- Offline regression suite
- Ruff
- CI workflow
- Coverage configuration
- UI smoke tests
- Real-model test lane
- Real-host test lane
- Stress and concurrency coverage

Separate tests into:

- Required for RC
- Required before final v1.0
- Optional post-release

Result:

- Pass
- Conditional Pass
- Fail

---

# Mandatory RC Smoke Matrix

Report the verification status of:

| Environment | Required Check |
|---|---|
| CPU-only | Single-image workflow |
| CPU-only | Batch interactive workflow |
| CPU-only | Automatic batch opt-in |
| CPU-only | Workspace save and restore |
| CPU-only | Plugin package lifecycle |
| CPU-only | Automation command chain |
| GPU-supported machine | Real inference smoke |
| Supported host environment | Export or host-adapter smoke |
| Desktop UI | Startup, restore, cancel, shutdown |

Allowed statuses:

- Verified
- Not Verified
- Not Applicable
- Failed

Do not mark an item Verified without evidence.

---

# Release Decision

Return one:

- RC Approved
- RC Approved with Accepted Risks
- RC Blocked

RC must be blocked when:

- Domain or Schema compatibility fails
- Confirmation semantics are weakened
- Persistent data can be corrupted
- Shutdown leaves reproducible resource leaks
- Critical security issues remain
- Core offline regression fails

---

# Final Report

Return:

1. Executive Summary
2. Gate Results
3. Verified RC Sprint 1 Claims
4. Verified RC Sprint 2 Claims
5. Smoke Matrix
6. Critical Findings
7. High Findings
8. Medium Findings
9. Accepted Risks
10. Required Fixes Before RC
11. Required Checks Before Final v1.0
12. Final Release Decision
13. Updated Release Readiness Percentage

