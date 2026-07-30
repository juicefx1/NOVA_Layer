# Release Integrity Audit

## Status

Approved.

This document defines the release integrity requirements for NOVA Layer v1.0.

Its purpose is to guarantee that every released build is reproducible,
traceable, versioned, and supported by verifiable release evidence.

This document is part of the Release Track and is not a Product Feature.

---

# Goal

Prevent accidental, inconsistent, or unverifiable releases.

Every Release Candidate (RC) and General Availability (GA) release must be
cryptographically and procedurally reproducible from a uniquely identified
source revision.

---

# Scope

This document applies to:

- Release Candidate builds
- General Availability releases
- Hotfix releases
- Patch releases

It does not apply to ordinary development builds.

---

# Release Integrity Principles

A release is considered valid only if all of the following are true:

- Source revision is uniquely identified.
- Package version matches the release version.
- Release notes correspond to the released code.
- Acceptance evidence exists.
- CI evidence exists.
- Release artifacts are reproducible.
- Human approval has been completed.

Failure of any requirement invalidates the release.

---

# Release Identity

Each release must have:

- Version
- Git commit
- Git tag
- Build date
- Release type
- Artifact checksum
- Release notes
- Acceptance report

All fields must uniquely identify one release.

---

# Version Policy

Development builds:

```
0.x.y.devN
```

Release Candidates:

```
1.0.0-rcN
```

General Availability:

```
1.0.0
```

Hotfix:

```
1.0.1
```

Package metadata, release notes and release artifacts must all reference the
same version.

---

# Release Artifacts

Each release must produce:

- Wheel
- Source archive
- Release notes
- Acceptance report
- CI report
- Checksums

Optional:

- Installer
- Portable package

---

# Acceptance Evidence

Every release must include evidence that:

- Product Features are accepted.
- Regression tests passed.
- Schema compatibility verified.
- Workspace compatibility verified.
- Plugin compatibility verified.
- Batch compatibility verified.
- Automation compatibility verified.

Evidence may consist of:

- automated test reports
- manual QA reports
- release audit documents

---

# CI Evidence

The release must include CI evidence for the exact released revision.

Required evidence:

- Build succeeded
- Tests passed
- Lint passed
- Packaging succeeded

The CI run must reference the exact release commit.

---

# Release Notes

Release notes must include:

- New features
- Bug fixes
- Breaking changes
- Known limitations
- Supported environments

Release notes must describe the released artifact only.

---

# Reproducibility

Given:

- release tag
- commit
- version
- build instructions

another developer must be able to reproduce the released artifacts.

---

# Integrity Verification

Before approval verify:

- Package version
- Git tag
- Commit hash
- Release notes
- Acceptance report
- CI report
- Artifact checksum

Any mismatch blocks release.

---

# Human Approval

A release is not considered complete until approved by:

- Development
- QA
- Product Owner

Approval records must include:

- Name
- Date
- Version
- Commit
- Decision

---

# Release Blockers

The following block release immediately:

- Version mismatch
- Missing release notes
- Missing acceptance evidence
- Missing CI evidence
- Artifact checksum mismatch
- Unknown commit
- Missing approval

---

# Out of Scope

This document does not define:

- Product Features
- Architecture
- UX
- Plugin implementation
- Runtime behavior

These are defined by their respective specifications.

---

# Release Checklist

Before publishing verify:

- Version matches release
- Commit identified
- Tag created
- Package built
- Acceptance completed
- CI completed
- Checksums generated
- Release notes completed
- Approval completed

---

# Completion Criteria

A release satisfies Release Integrity when:

- Every required artifact exists.
- Every artifact references the same release version.
- Every artifact references the same commit.
- Acceptance evidence exists.
- CI evidence exists.
- Release approval is complete.

Only then may the release be published.

---

# Expected Audit Report

The Release Integrity Audit must report:

1. Release Version
2. Git Commit
3. Git Tag
4. Artifact Versions
5. Package Metadata
6. Acceptance Evidence
7. CI Evidence
8. Checksum Verification
9. Release Notes Consistency
10. Approval Status
11. Release Integrity Verdict

Possible verdicts:

- PASS
- PASS WITH WARNINGS
- FAIL
