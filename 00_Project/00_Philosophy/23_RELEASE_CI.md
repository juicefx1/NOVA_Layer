# Release Continuous Integration

## Status

Approved.

This document defines the Continuous Integration (CI) policy for NOVA Layer.

Its purpose is to ensure that every Release Candidate (RC) and General
Availability (GA) build is automatically verified, reproducible, and traceable.

This document defines release policy only.
It does not prescribe any specific CI platform or implementation.

---

# Goal

Guarantee that every release candidate is automatically validated before it can
be considered for release.

CI provides objective engineering evidence for Release Integrity.

---

# Scope

This policy applies to:

- Release Candidate builds
- General Availability releases
- Hotfix releases
- Patch releases

It does not apply to ordinary developer builds.

---

# CI Principles

Continuous Integration shall be:

- Automated
- Repeatable
- Deterministic
- Version-aware
- Traceable

A successful local build is not a substitute for CI evidence.

---

# CI Pipeline

A release pipeline shall execute the following stages.

Source Checkout

↓

Version Validation

↓

Dependency Resolution

↓

Build

↓

Static Analysis

↓

Unit Tests

↓

Integration Tests

↓

Regression Tests

↓

Package

↓

Artifact Verification

↓

Release Evidence

---

# Required Checks

Every Release Candidate shall verify:

- Build completed successfully
- Static analysis completed
- Unit tests passed
- Integration tests passed
- Regression tests passed
- Package created
- Package metadata verified
- Version verified
- Release artifacts generated

---

# Optional Checks

Projects may additionally include:

- Performance benchmarks
- Security scanning
- Dependency vulnerability scanning
- License compliance
- Documentation generation

These checks are recommended but are not mandatory unless specified by the
release plan.

---

# Version Validation

CI shall verify that:

- Package version matches release version.
- Artifact version matches package metadata.
- Release notes reference the same version.
- Git tag corresponds to the released version.

Any mismatch blocks the release.

---

# Package Validation

CI shall validate:

- Wheel package
- Source archive (sdist)
- Package metadata
- Entry points
- Manifest
- Checksums

Package validation must succeed before publication.

---

# Regression Validation

Regression testing shall verify that previously accepted features remain
functional.

Required compatibility checks include:

- Schema compatibility
- Workspace compatibility
- Plugin compatibility
- Batch compatibility
- Automation compatibility (if released)

Regression failures block the release.

---

# Artifact Verification

Release artifacts shall include:

- Wheel
- Source archive
- SHA-256 checksums

Optional artifacts:

- Installer
- Portable package

All published artifacts must originate from the same CI execution.

---

# CI Report

Every release shall archive a CI report containing:

- Release version
- Git commit
- Git tag
- Build environment
- Build duration
- Test summary
- Regression summary
- Generated artifacts
- Checksum summary
- Final CI verdict

The CI report forms part of the Release Evidence.

---

# Blocking Conditions

The release shall be blocked if any of the following occur:

- Build failure
- Test failure
- Regression failure
- Package generation failure
- Version mismatch
- Missing artifacts
- Checksum mismatch
- Incomplete CI report

---

# Release Evidence

The following documents together constitute CI evidence:

- CI Report
- Build Log
- Test Summary
- Regression Summary
- Artifact Manifest
- Checksum Manifest

These records shall be archived with the release.

---

# Completion Criteria

A release satisfies the CI policy when:

- All required pipeline stages succeed.
- Required artifacts are generated.
- Required reports are archived.
- No blocking condition remains.

---

# Expected Audit Report

A CI audit shall report:

1. Pipeline Status
2. Build Status
3. Test Status
4. Regression Status
5. Package Validation
6. Artifact Validation
7. Version Validation
8. Archived Evidence
9. Blocking Issues
10. Final CI Verdict

Possible verdicts:

- PASS
- PASS WITH WARNINGS
- FAIL

