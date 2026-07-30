# Document Review Checklist

## Status

Approved

## Audience

Maintainer, Release Engineer, Developer

## Authority

**Documentation QA checklist** for reviewing changes under `05_Documents/`.

Governance (who owns / approves docs) — do not redefine here:

- `05_Documents/09_GOVERNANCE/00_DOCUMENT_POLICY.md`

Structure and one-source-of-truth rules:

- `05_Documents/00_DOCUMENTATION_ARCHITECTURE.md`

## Scope

Operational checks before marking a document **Approved** or merging doc-only changes. Not a product behaviour spec. Not a release seal procedure.

---

# 1. Purpose

Prevent documentation drift, invented features, and contradictory guidance by applying a repeatable review gate.

---

# 2. Pre-Review Identity

Confirm for every changed document:

| Check | Pass criteria |
|---|---|
| Header | Title, Status, Audience present |
| Status honesty | Stub / Draft / Approved matches content depth |
| Audience | Matches Documentation Architecture supported audiences |
| Folder ownership | File lives in the folder that Owns that concern |
| Listed in hierarchy | Path appears in Documentation Architecture Directory Structure **or** change updates that tree in the same PR |

---

# 3. Content Checks

| Check | Pass criteria |
|---|---|
| Matches implementation | No planned-as-shipped features; no unsupported platforms as Supported |
| Unverified labelled | GPU / hosts / full UI / optional markers = **Not Verified** unless evidence cited |
| No invented APIs | Commands, schema fields, UI controls exist in `02_Source/` or Approved API refs |
| Links over copy | Prefer links to authority; no forked lifecycle/architecture tables |
| Stub rules | Stubs point to equivalent Implementation / Approved docs; not cited as product authority |

---

# 4. Cross-Document Checks

| Check | Pass criteria |
|---|---|
| One authority | Authority section names a single owning concept location (see `01_AUTHORITY_VALIDATION.md`) |
| No responsibility clash | Does not take over another folder’s Owns row |
| Related docs | Related / governing links resolve; pointers stay pointer-only |
| Stale gaps | “Documentation Gaps” / “placeholder” notes updated if Status is now Approved |

---

# 5. Review Outcome

| Outcome | When |
|---|---|
| **Approve** | All applicable checks pass; Maintainer may set Status **Approved** (Document Policy) |
| **Request changes** | Drift, invented claims, stale gaps, or hierarchy omission |
| **Keep Stub/Draft** | Intentional incomplete narrative; must not be treated as release authority |

Release milestone docs additionally require `02_RELEASE_DOCUMENT_VALIDATION.md`.

---

# 6. Related Documents

| Document | Role |
|---|---|
| `01_AUTHORITY_VALIDATION.md` | Authority conflict checks |
| `02_RELEASE_DOCUMENT_VALIDATION.md` | Milestone / RC–GA doc QA |
| `03_TRACEABILITY_RULES.md` | Required link chains |
| `04_DOCUMENT_LIFECYCLE.md` | Status transitions |
| `09_GOVERNANCE/00_DOCUMENT_POLICY.md` | Ownership / approval governance |
