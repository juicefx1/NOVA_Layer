# Document Lifecycle

## Status

Approved

## Audience

Maintainer, Release Engineer, Developer

## Authority

**Documentation QA lifecycle** for Status transitions and maintenance of `05_Documents/`.

Status label meanings (governance):

- `05_Documents/09_GOVERNANCE/00_DOCUMENT_POLICY.md`

Structure / freeze rules:

- `05_Documents/00_DOCUMENTATION_ARCHITECTURE.md` — Maintenance Rules

## Scope

When documents may be created, approved, frozen, errata’d, or retired. Does not govern code release sealing (Release Process) or who signs GA (Release Approval Policy).

---

# 1. Purpose

Keep documentation maintainable: intentional stubs, fresh Approved content, and no silent drift after behaviour or release changes.

---

# 2. Status Lifecycle

```text
(new) → Stub → Draft → Approved
              ↘ (remain Stub if intentional placeholder)
Approved → Errata / Revision → Approved
Approved → Superseded (pointer) → (optional archive note)
```

| Status | May be cited as | QA gate before enter |
|---|---|---|
| **Stub** | Not product/API/release authority | Points to equivalents; listed in tree |
| **Draft** | Work-in-progress only | Review Checklist started |
| **Approved** | Authority within Scope | `00_DOCUMENT_REVIEW_CHECKLIST.md` (+ Release validation if Release/) |
| **Approved (pointer)** | Redirect only | Target canonical path exists |

---

# 3. Transition Rules

### 3.1 Stub → Draft / Approved

- Content must match implementation.  
- Authority and traces per `03_TRACEABILITY_RULES.md`.  
- Remove or rewrite “placeholder only” language.  

### 3.2 Keeping Stub intentional

Allowed when:

- Equivalent Implementation / Approved doc exists and is linked; and  
- Developer Guide / folder index lists Stub status honestly.  

Not allowed: citing Stubs from Release Checklist as Documentation Gate **PASS**.

### 3.3 Approved revision

Trigger a revision when:

- Behaviour in `02_Source/` changes for documented surfaces  
- Allowlists / schema / commands change (Versioning Policy)  
- Seal evidence or packaging identity for a milestone changes  
- Documentation Architecture Audit / QA finds stale Gaps  

Same-PR update preferred (Documentation Architecture Maintenance Rule 1).

### 3.4 Versioned Release freeze

After a milestone is tagged/shipped: `Release/vX.Y/` frozen except **errata** (Documentation Architecture Maintenance Rule 4). Errata must not invent new GA PASS without new evidence elsewhere.

### 3.5 Supersede via pointer

When renaming (e.g. Support Matrix → Compatibility):

1. Canonical body at new path.  
2. Old path becomes **Approved (pointer)** with single target.  
3. Update Documentation Architecture tree to prefer canonical (pointers noted).  

---

# 4. Drift Prevention Cadence

| Event | Required doc action |
|---|---|
| Behaviour change merged | Update owning Approved docs or open explicit docs follow-up |
| New seal under `08_Release/` | Update Release Notes / Test Report / Checklist citations for that milestone |
| Sibling Status → Approved | Clear stale “still placeholder” Gaps in related docs |
| Hierarchy folder added | Update Documentation Architecture Directory Structure + ownership table |
| Audit finds conflict | Fix before next RC/GA doc claim (`01_AUTHORITY_VALIDATION.md`) |

---

# 5. Retirement

| Step | Action |
|---|---|
| 1 | Confirm no Checklist/Go-Live **PASS** depends on the doc body |
| 2 | Replace with pointer or remove from tree in Documentation Architecture |
| 3 | Do not leave Approved dual bodies |

---

# 6. Related Documents

| Document | Role |
|---|---|
| `00_DOCUMENT_REVIEW_CHECKLIST.md` | Entering Approved |
| `02_RELEASE_DOCUMENT_VALIDATION.md` | Milestone freshness |
| `03_TRACEABILITY_RULES.md` | Link requirements on transitions |
| `09_GOVERNANCE/00_DOCUMENT_POLICY.md` | Who sets Status |
| `09_GOVERNANCE/04_RELEASE_APPROVAL_POLICY.md` | RC/GA claims vs lifecycle |
