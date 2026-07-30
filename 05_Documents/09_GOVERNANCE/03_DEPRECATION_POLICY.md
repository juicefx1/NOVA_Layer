# Deprecation Policy

## Status

Approved

## Audience

Maintainer, Release Engineer, Developer, Plugin Author, Integrator

## Authority

**Official deprecation and removal governance** for public version surfaces and documented contracts.

Compatibility and deprecation semantics (do not invent soft-load behaviour):

- `05_Documents/Release/00_VERSIONING_POLICY.md` §5–§6

Unsupported paths and migration non-support:

- `05_Documents/Release/v1.0/06_MIGRATION_GUIDE.md`
- `05_Documents/Release/v1.0/02_KNOWN_LIMITATIONS.md`
- `05_Documents/Release/v1.0/03_COMPATIBILITY.md`

## Scope

How NOVA Layer announces, documents, and removes public surfaces. Reflects **current implementation reality**: unsupported versions are **hard-rejected**; there is **no** implemented deprecation grace loader (Versioning Policy §6).

---

# 1. Purpose

Prevent silent breaking changes and prevent documentation from promising deprecation windows Core does not implement.

---

# 2. Ownership

| Surface | Owner | Gate |
|---|---|---|
| Project Schema / Intent schema | Maintainer | Domain + Versioning Policy |
| Plugin SDK / package format allowlists | Maintainer | Plugin SDK + Versioning Policy |
| Automation builtins / events | Maintainer | API references + Versioning Policy |
| Distribution package exports | Maintainer | `pyproject` / public API overview |
| Milestone Release Notes / Migration Guide | Release Engineer + Maintainer | Evidence of last supporting version |

---

# 3. Terms (aligned with Versioning Policy)

| Term | Meaning |
|---|---|
| **Unsupported** | Rejected at validation/load today |
| **Deprecated (docs-only)** | Announced in Release Notes before a future removal; announcement **alone** does not keep old versions loading |
| **Removed** | No longer in allowlists / no longer exported |
| **Breaking** | Existing conforming artifacts/callers fail without modification (Versioning Policy §5) |

---

# 4. Review Responsibilities

| Role | Responsibility |
|---|---|
| Maintainer | Decide allowlist growth vs removal; forbid inventing soft-load |
| Release Engineer | Ensure Release Notes + Migration Guide + Compatibility state last version, rejection behaviour, migrator existence (**none** for Schema 1.0→2.0 today) |
| Developer | Implement hard reject consistently; no dual-schema OW loader without Architecture Decision Policy approval |
| Reviewers | Block PRs that remove allowlist values without Release doc updates |

---

# 5. Approval Flow

### 5.1 Prefer additive change

Grow `SUPPORTED_*` / keep Schema `"2.0"` compatible within major when possible (Versioning Policy §4.2).

### 5.2 Docs-only deprecation announcement

1. Maintainer approves announcement text.  
2. Release Notes for the milestone state the surface and intent to remove later.  
3. Do **not** document a grace period unless Core implements one.  

### 5.3 Removal / breaking change

1. Architecture Decision Policy if structural.  
2. Implementation hard-rejects or removes export.  
3. Same milestone (or coordinated docs): Release Notes, Migration Guide, Compatibility, Known Limitations updated.  
4. Release Approval Policy before claiming RC/GA with the narrowed contract.  

### 5.4 Explicit non-migrators

Do not invent Schema 1.0→2.0 or cross-major SDK migrators. State **Unsupported** and point to Migration Guide manual paths.

---

# 6. Document Authority

| Question | Authoritative answer |
|---|---|
| Soft-load exists? | **No** (Versioning Policy §6) |
| Schema 1.0→2.0 migrator? | **Not provided** (Migration Guide; Compatibility §3) |
| How to label platforms | Compatibility / Known Limitations — Not Verified vs Unsupported |

---

# 7. Related Documents

| Document | Role |
|---|---|
| `Release/00_VERSIONING_POLICY.md` | Breaking + deprecation rules |
| `Release/v1.0/06_MIGRATION_GUIDE.md` | Supported / unsupported upgrade paths |
| `02_ARCHITECTURE_DECISION_POLICY.md` | Structural removals |
| `04_RELEASE_APPROVAL_POLICY.md` | Shipping narrowed contracts |
