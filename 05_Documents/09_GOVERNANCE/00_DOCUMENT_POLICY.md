# Document Policy

## Status

Approved

## Audience

Maintainer, Release Engineer, Developer, Integrator

## Authority

**Official documentation governance** for NOVA Layer under `05_Documents/`.

Does not redefine product behaviour. Structure and ownership rules originate in:

- `05_Documents/00_DOCUMENTATION_ARCHITECTURE.md`

Product / architecture behaviour remains in:

- `00_Project/01_Implementation/ARCHITECTURE.md`
- `02_Source/`

## Scope

Ownership, status labels, authority, and change rules for human documentation. Does not govern sealed artifacts under `08_Release/` (artifacts only — Documentation Architecture §6).

---

# 1. Purpose

Ensure every concept has one authoritative document, clear audience, and an accountable owner so guides do not contradict specs or invent unsupported behaviour.

---

# 2. Ownership

| Area | Primary owner role | Folder / location |
|---|---|---|
| Documentation structure | Maintainer | `05_Documents/00_DOCUMENTATION_ARCHITECTURE.md` |
| End-user guides | Maintainer (product docs) | `05_Documents/User/` |
| Developer guides | Maintainer / Developer | `05_Documents/Developer/` |
| Public API references | Maintainer / Plugin Author liaison | `05_Documents/API/` |
| Architecture narratives | Maintainer | `05_Documents/Architecture/` (links only; does not replace `ARCHITECTURE.md`) |
| Release milestone docs | Release Engineer + Maintainer | `05_Documents/Release/` |
| Governance policies | Maintainer | `05_Documents/09_GOVERNANCE/` |
| Documentation QA policies | Maintainer / Release Engineer | `05_Documents/10_QUALITY/` |
| Product architecture | Maintainer | `00_Project/01_Implementation/ARCHITECTURE.md` |
| Implementation | Maintainer / Developer | `02_Source/` |
| Release artifacts | Release Engineer | `08_Release/` (artifacts only) |

Folder-level “Owns” summary: Documentation Architecture **Ownership by Folder**.

---

# 3. Document Status

Every document under `05_Documents/` (except Documentation Architecture, which uses its own status wording) must declare:

| Status | Meaning |
|---|---|
| **Stub** | Placeholder; not authority |
| **Draft** | In progress; not release authority until Approved |
| **Approved** | May be cited as documentation authority for its Scope |

Stub documents must not be treated as product or API authority (Documentation Architecture header rules).

---

# 4. Document Authority

| Rule | Detail |
|---|---|
| One source of truth | Prefer links over copying tables/prose (Documentation Architecture principles) |
| Product behaviour | `ARCHITECTURE.md` + implementation specs + `02_Source/` win over narrative guides |
| Public contracts | `05_Documents/API/` indexes package surfaces; field truth remains in source validators |
| Versioning / release stages | `05_Documents/Release/00_VERSIONING_POLICY.md` |
| Release workflow steps | `05_Documents/Release/01_RELEASE_PROCESS.md` (do not duplicate here) |
| Milestone evidence | `05_Documents/Release/vX.Y/` checklists and reports |
| Artifacts vs prose | Never place guides in `08_Release/` |

Authority map: Documentation Architecture **Authority Map**.

---

# 5. Review Responsibilities

| Change type | Who reviews | Gate |
|---|---|---|
| User / Developer / API / Architecture docs | Maintainer (required); Developer as needed | Matches implementation; no invented APIs |
| Release milestone docs | Release Engineer + Maintainer | Evidence-backed; PASS/PENDING honesty |
| Governance (`09_GOVERNANCE/`) | Maintainer | Consistent with Documentation Architecture + Release policies |
| Docs that claim Supported / Not Verified | Release Engineer when release-facing | Compatibility / Known Limitations labels |

Documentation changes that describe behaviour changes should land with the behaviour change or an explicit docs follow-up (Documentation Architecture **Maintenance Rules**).

---

# 6. Approval Flow

1. Author updates the owning document under the correct folder.  
2. Reviewer checks authority links, audience header, and Status.  
3. Maintainer sets Status to **Approved** only when content matches implementation and does not invent platforms/features.  
4. Versioned `Release/vX.Y/` docs: after a milestone is tagged/shipped, treat as frozen except errata (Documentation Architecture Maintenance Rule 4).  

Release Candidate vs GA claims use milestone checklists — see `04_RELEASE_APPROVAL_POLICY.md`.

---

# 7. Related Documents

| Document | Role |
|---|---|
| `05_Documents/00_DOCUMENTATION_ARCHITECTURE.md` | Structure / ownership / headers |
| `09_GOVERNANCE/01_CODE_REVIEW_POLICY.md` | Code vs docs review |
| `09_GOVERNANCE/04_RELEASE_APPROVAL_POLICY.md` | RC / GA doc approval |
| `Developer/11_CONTRIBUTING.md` | Contribution entry (when filled) |
