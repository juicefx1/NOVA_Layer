# Traceability Rules

## Status

Approved

## Audience

Maintainer, Release Engineer, Developer

## Authority

**Documentation QA rules** for required link chains so the hierarchy stays acyclic and auditable.

Structure:

- `05_Documents/00_DOCUMENTATION_ARCHITECTURE.md`

Product architecture root:

- `00_Project/01_Implementation/ARCHITECTURE.md`

## Scope

Defines **minimum traceability** between documentation layers. Does not define product behaviour or Governance ownership.

---

# 1. Purpose

Ensure every Approved behavioural or release claim can be traced upward to Architecture (and, for seals, to Process + evidence) without circular authority.

---

# 2. Hierarchy Direction (acyclic)

Allowed dependency direction for **authority**:

```text
02_Source / Implementation specs / ARCHITECTURE.md / ADRs
        ↑
05_Documents/00_DOCUMENTATION_ARCHITECTURE.md   (docs structure)
        ↑
Folder owners (User, Developer, API, Architecture, Release, Governance, Quality)
        ↑
Individual documents (summarize / link)
```

| Rule | Detail |
|---|---|
| Downward summary OK | Guides may summarize Architecture |
| Upward redefine forbidden | Guides must not become Architecture |
| Related-doc links OK | Bidirectional “Related Documents” tables are allowed |
| Authority cycles forbidden | Two docs must not each claim to own the other’s normative rules |

---

# 3. Required Traces by Document Class

### 3.1 User / Developer / Architecture narratives

| Must link (directly) | To |
|---|---|
| Behaviour claims | `ARCHITECTURE.md` and/or owning Implementation spec / Approved API ref |
| Stub placeholders | Equivalent Implementation or Approved doc path |

### 3.2 API references

| Must link | To |
|---|---|
| Overview / references | `ARCHITECTURE.md` + package export paths |
| Field/command truth | Source modules / validators (named) |

### 3.3 Governance

| Must link | To |
|---|---|
| Document Policy | Documentation Architecture |
| Architecture Decision Policy | `ARCHITECTURE.md` + `07_ARCHITECTURE_DECISIONS.md` |
| Release Approval Policy | Release Process + Checklist/Go-Live (**not** seal command bodies) |
| Deprecation Policy | Versioning Policy semantics |

### 3.4 Quality (`10_QUALITY/`)

| Must link | To |
|---|---|
| All QA policies | Documentation Architecture and/or Governance (by reference) |
| Must not | Assign RC/GA sign-off rights (Governance) or seal steps (Process) |

### 3.5 Release milestone docs

| Document | Minimum Architecture / Process trace |
|---|---|
| Versioning Policy / Release Process | Direct `ARCHITECTURE.md` |
| Release Notes / Known Limitations / Security | Direct `ARCHITECTURE.md` |
| Compatibility / Migration / Test Report / Go-Live | Direct `ARCHITECTURE.md` **or** explicit chain: doc → Versioning or Process or Checklist → `ARCHITECTURE.md` |
| Release Checklist | Direct Architecture gate or cite Architecture status |

**QA preference:** prefer **direct** `ARCHITECTURE.md` in Authority/Related for Approved Release milestone docs (addresses Documentation Architecture Audit gap).

---

# 4. Pointer Traceability

| Pointer file | Must resolve to | Must not |
|---|---|---|
| `VERSIONING_POLICY.md` | `00_VERSIONING_POLICY.md` | Own policy body |
| `RELEASE_PROCESS.md` | `01_RELEASE_PROCESS.md` | Own process body |
| `03_SUPPORT_MATRIX.md` | `03_COMPATIBILITY.md` | Own matrix body |

Documentation Architecture Directory Structure should list **canonical** paths (and may note pointers). Drift = hierarchy defect under review.

---

# 5. Orphan Prevention

A document is an **orphan** for QA purposes if:

1. It is not listed in Documentation Architecture Directory Structure, and the PR does not update that tree; or  
2. It has Status **Approved** but no inbound link from its folder index, Developer Guide status table, Release Checklist, or Documentation Architecture.

Stubs listed in the tree with “Where Equivalent Information Exists” are **not** orphans.

---

# 6. Cycle Checks (soft)

| Pattern | Action |
|---|---|
| Checklist ↔ Go-Live both normative for the same PASS | Keep Checklist as evidence master; Go-Live summarizes |
| Doc Architecture ↔ Document Policy | Structure vs process — keep roles distinct |
| Related-only bidirection | Allowed |

---

# 7. Related Documents

| Document | Role |
|---|---|
| `01_AUTHORITY_VALIDATION.md` | Conflict detection |
| `02_RELEASE_DOCUMENT_VALIDATION.md` | Release-specific traces |
| `04_DOCUMENT_LIFECYCLE.md` | When traces must be re-checked |
