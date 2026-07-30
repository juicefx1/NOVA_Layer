# NOVA Layer Documentation Architecture

## Status

Approved for v1.0 documentation work.

---

# Purpose

This document defines the structure, ownership, audience, and maintenance rules for NOVA Layer documentation.

The goal is to prevent:

- duplicated explanations
- contradictory architecture descriptions
- stale release information
- unclear document ownership
- mixing implementation notes with user guidance

This document does not define product behaviour.

Product and architecture authority remains in:

- `01_Design/`
- `00_Project/01_Implementation/` (especially `ARCHITECTURE.md`)
- `02_Source/` (implementation and public package surfaces)
- approved implementation specifications under `00_Project/01_Implementation/` and product philosophy under `00_Project/00_Philosophy/`

---

# Documentation Principles

## 1. One Source of Truth

Every concept must have one authoritative document.

Other documents may summarize or link to it, but must not redefine it.

---

## 2. Audience First

Every document must declare its intended audience.

Supported audiences:

- End User
- Developer
- Plugin Author
- Integrator
- Release Engineer
- Maintainer

---

## 3. Stable vs Versioned Documents

Stable documents describe concepts that remain valid across releases.

Versioned documents describe a specific release.

Examples:

Stable:

- Architecture Guide
- Plugin SDK Guide
- Testing Guide
- Contribution Guide

Versioned:

- v1.0 Release Notes
- v1.0 Known Limitations
- v1.0 Test Report
- v1.0 Security Report

---

## 4. Documentation Must Match Implementation

Documentation must describe the current implementation.

Do not document:

- planned features as implemented
- unverified platform support
- unsupported migration paths
- optional integrations as mandatory

Unverified behaviour must be labelled clearly.

---

## 5. No Source-Code Modification

Documentation work must not modify product source code unless a separate implementation task is approved.

---

## 6. Build Artifacts Are Not Documentation

`08_Release/` stores build and release artifacts only (wheels, manifests, smoke JSON).

Human-readable release documentation lives under `05_Documents/Release/`.

Do not place guides, checklists, or architecture prose in `08_Release/`.

---

# Directory Structure

```text
05_Documents/
├── 00_DOCUMENTATION_ARCHITECTURE.md
│
├── User/
│   ├── 00_GETTING_STARTED.md
│   ├── 01_USER_GUIDE.md
│   ├── 02_WORKSPACE_GUIDE.md
│   ├── 03_BATCH_GUIDE.md
│   ├── 04_PLUGIN_USER_GUIDE.md
│   ├── 05_TROUBLESHOOTING.md
│   └── 06_FAQ.md
│
├── Developer/
│   ├── 00_DEVELOPER_GUIDE.md
│   ├── 01_PROJECT_STRUCTURE.md
│   ├── 02_ARCHITECTURE_GUIDE.md
│   ├── 03_DOMAIN_MODEL.md
│   ├── 04_APPLICATION_AND_RUNTIME.md
│   ├── 05_WORKSPACE_AND_PERSISTENCE.md
│   ├── 06_PLUGIN_SDK_GUIDE.md
│   ├── 07_AUTOMATION_GUIDE.md
│   ├── 08_BATCH_ARCHITECTURE.md
│   ├── 09_TESTING_GUIDE.md
│   ├── 10_BUILD_GUIDE.md
│   └── 11_CONTRIBUTING.md
│
├── API/
│   ├── 00_PUBLIC_API_OVERVIEW.md
│   ├── 01_PLUGIN_SDK_REFERENCE.md
│   ├── 02_AUTOMATION_COMMAND_REFERENCE.md
│   ├── 03_EVENT_REFERENCE.md
│   └── 04_SCHEMA_REFERENCE.md
│
├── Architecture/
│   ├── 00_ARCHITECTURE_BOOK.md
│   ├── 01_OBJECT_LIFECYCLE.md
│   ├── 02_RUNTIME_MODEL.md
│   ├── 03_EXTENSION_MODEL.md
│   └── 04_ARCHITECTURE_DECISIONS_INDEX.md
│
├── Release/
│   ├── v1.0/
│   │   ├── 00_RELEASE_CHECKLIST.md
│   │   ├── 01_RELEASE_NOTES.md
│   │   ├── 02_KNOWN_LIMITATIONS.md
│   │   ├── 03_SUPPORT_MATRIX.md
│   │   ├── 04_TEST_REPORT.md
│   │   ├── 05_SECURITY_REPORT.md
│   │   ├── 06_MIGRATION_GUIDE.md
│   │   └── 07_GO_LIVE_CHECKLIST.md
│   │
│   ├── VERSIONING_POLICY.md
│   └── RELEASE_PROCESS.md
│
├── 09_GOVERNANCE/
│   ├── 00_DOCUMENT_POLICY.md
│   ├── 01_CODE_REVIEW_POLICY.md
│   ├── 02_ARCHITECTURE_DECISION_POLICY.md
│   ├── 03_DEPRECATION_POLICY.md
│   └── 04_RELEASE_APPROVAL_POLICY.md
│
└── 10_QUALITY/
    ├── 00_DOCUMENT_REVIEW_CHECKLIST.md
    ├── 01_AUTHORITY_VALIDATION.md
    ├── 02_RELEASE_DOCUMENT_VALIDATION.md
    ├── 03_TRACEABILITY_RULES.md
    └── 04_DOCUMENT_LIFECYCLE.md
```

---

# Standard Document Header

Every document under `05_Documents/` (except this architecture file) must begin with:

```markdown
# <Document Title>

## Status

Stub | Draft | Approved

## Audience

<one or more of: End User | Developer | Plugin Author | Integrator | Release Engineer | Maintainer>

## Authority

This document does not redefine product behaviour.
Authoritative sources:

- <link or path to the owning specification / package surface>

## Scope

<one short paragraph>
```

Stub documents add a `## TODO` section listing what must be written next.

---

# Ownership by Folder

| Folder | Primary audience | Owns |
|---|---|---|
| `User/` | End User | How to use the product |
| `Developer/` | Developer, Maintainer | How to navigate, extend, and test the codebase |
| `API/` | Plugin Author, Integrator | Public package surfaces and command/event/schema indexes |
| `Architecture/` | Developer, Maintainer | Narrative architecture that **links** to `ARCHITECTURE.md` and implementation specs |
| `Release/` | Release Engineer, Maintainer | Versioned release docs and process |
| `09_GOVERNANCE/` | Maintainer, Release Engineer | Project governance policies (docs, review, ADR, deprecation, release approval) |
| `10_QUALITY/` | Maintainer, Release Engineer | Documentation QA gates (review, authority, release-doc validation, traceability, lifecycle) |

---

# Authority Map (Do Not Duplicate)

| Concept | Authoritative location |
|---|---|
| Architecture (layers, ownership, extension) | `00_Project/01_Implementation/ARCHITECTURE.md` |
| Architecture decision rationale (ADRs) | `00_Project/01_Implementation/07_ARCHITECTURE_DECISIONS.md` |
| Domain model | `00_Project/01_Implementation/02_DOMAIN_MODEL_SPEC.md` |
| Object lifecycle | `00_Project/01_Implementation/01_OBJECT_LIFECYCLE_SPEC.md` |
| Physical repository / package map | `05_Documents/Developer/01_PROJECT_STRUCTURE.md` |
| Product features / philosophy | `00_Project/00_Philosophy/` |
| Implementation | `02_Source/src/nova_layer/` |
| Object Workflow package | `02_Source/src/nova_layer/object_workflow/` |
| Public Plugin SDK exports | `nova_layer.object_workflow.plugin_sdk` |
| Public Automation exports | `nova_layer.object_workflow.automation` |
| Build artifacts | `08_Release/` (artifacts only) |
| Documentation / review / ADR / deprecation / release **approval** governance | `05_Documents/09_GOVERNANCE/` (policies; does not replace Release Process steps) |
| Documentation **QA** (review checklists, authority validation, release-doc freshness, traceability, lifecycle) | `05_Documents/10_QUALITY/` (does not replace Governance ownership or Release Process) |

---

# Maintenance Rules

1. Update documentation in the same change set that changes documented behaviour, or open an explicit documentation follow-up.
2. Prefer links to authoritative specs over copying tables or lifecycle prose.
3. Mark unverified environments (GPU, commercial host, Desktop UI smoke) as **Not Verified** until evidence exists.
4. Versioned release docs under `Release/vX.Y/` must not be edited after that release is tagged, except for errata notes.
5. Never invent APIs, commands, or supported platforms that are not present in `02_Source/`.
