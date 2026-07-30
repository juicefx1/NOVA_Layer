# Architecture Decision Policy

## Status

Approved

## Audience

Maintainer, Developer

## Authority

**Official governance for architecture decisions** (ADRs and structural changes).

Product architecture authority:

- `00_Project/01_Implementation/ARCHITECTURE.md`

Architecture decision records:

- `00_Project/01_Implementation/07_ARCHITECTURE_DECISIONS.md`

Narrative index (links only; may be Stub):

- `05_Documents/Architecture/04_ARCHITECTURE_DECISIONS_INDEX.md`

## Scope

When an ADR is required, who owns it, how it is approved, and how docs must reference it. Does not restate ADR contents or invent a second architecture.

---

# 1. Purpose

Preserve a single architecture direction: Object Workflow Schema 2.0 Core, additive plugins, in-process Automation, Workspace independent of Projects, and related ADRs already recorded under Implementation.

---

# 2. Ownership

| Artifact | Owner | Authority level |
|---|---|---|
| `ARCHITECTURE.md` | Maintainer | **Authoritative** product architecture |
| `07_ARCHITECTURE_DECISIONS.md` | Maintainer | **Authoritative** ADR rationale |
| `05_Documents/Architecture/*` | Maintainer | Narrative / index — must link, not redefine |
| Implementation aligning to ADRs | Developer + Maintainer | Must not fork Domain or invent parallel stacks |

---

# 3. When an Architecture Decision Is Required

Record or update an ADR (and `ARCHITECTURE.md` if behaviour/structure changes) when a change would:

- Alter layer ownership or dependency direction  
- Change confirmation / object lifecycle rules  
- Introduce a second Domain, Schema, Workspace, or workflow stack  
- Add a Core transport (e.g. networked Automation) or remote plugin pipeline  
- Change public Schema / SDK / package-format compatibility model  
- Replace Runtime ownership (executor, caches, shutdown coordination)

Routine bugfixes and additive plugins within existing SDK types do **not** require a new ADR if they obey existing ADRs.

---

# 4. Review Responsibilities

| Role | Responsibility |
|---|---|
| Proposer (Developer / Maintainer) | Draft decision, context, consequences; cite current `ARCHITECTURE.md` |
| Maintainer | Approve or reject; update `07_ARCHITECTURE_DECISIONS.md` and `ARCHITECTURE.md` |
| Release Engineer | Ensure Release Notes / Known Limitations / Compatibility stay honest if user-visible contracts change |
| Documentation owner | Update Architecture / Developer / API docs per Document Policy — link to ADR, do not fork text |

---

# 5. Approval Flow

1. Propose change with architecture impact statement.  
2. Maintainer reviews against existing ADRs (ADR-001 Schema split, additive plugins, confirmation, Workspace, Automation in-process, coordinated shutdown, etc. — see ADR file).  
3. On approval: update `07_ARCHITECTURE_DECISIONS.md` and `ARCHITECTURE.md` in the same change set when practical.  
4. Update dependent `05_Documents/` guides to **link** the authority.  
5. If public contracts break: follow Deprecation Policy + Versioning Policy + Release Notes.  

Rejected proposals must not be documented as implemented behaviour.

---

# 6. Document Authority Rules

| Document type | May redefine architecture? |
|---|---|
| `ARCHITECTURE.md` / Implementation ADRs | Yes (only path) |
| `05_Documents/Architecture/` | No — summarize and link |
| User / Release docs | No — describe consequences only |
| Governance policies | No — point to architecture authority |

---

# 7. Related Documents

| Document | Role |
|---|---|
| `00_Project/01_Implementation/ARCHITECTURE.md` | Architecture authority |
| `00_Project/01_Implementation/07_ARCHITECTURE_DECISIONS.md` | ADR authority |
| `00_DOCUMENT_POLICY.md` | Docs ownership |
| `03_DEPRECATION_POLICY.md` | Retiring surfaces |
| `01_CODE_REVIEW_POLICY.md` | Merge review |
