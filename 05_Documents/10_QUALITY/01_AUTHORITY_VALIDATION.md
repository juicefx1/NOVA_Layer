# Authority Validation

## Status

Approved

## Audience

Maintainer, Release Engineer, Developer

## Authority

**Documentation QA rules** for validating that each concept has exactly one authority and that docs do not redefine it.

Authority map (structure):

- `05_Documents/00_DOCUMENTATION_ARCHITECTURE.md` — Authority Map

Product / ADR authority (content):

- `00_Project/01_Implementation/ARCHITECTURE.md`
- `00_Project/01_Implementation/07_ARCHITECTURE_DECISIONS.md`

Governance of who may change docs — not redefined here:

- `05_Documents/09_GOVERNANCE/00_DOCUMENT_POLICY.md`
- `05_Documents/09_GOVERNANCE/02_ARCHITECTURE_DECISION_POLICY.md`

## Scope

Detect and prevent authority conflicts and duplicated responsibilities in `05_Documents/`. Does not replace Governance decision rights.

---

# 1. Purpose

Keep the documentation graph acyclic for **behaviour authority**: one owner per concept; others summarize and link.

---

# 2. Single-Authority Rule

For each concept under review, identify **exactly one** authoritative location from Documentation Architecture Authority Map (or Release/API rows below). All other docs must:

1. Link to that location, and  
2. Not redefine tables, allowlists, or lifecycle rules.

| Concept class | Authoritative location |
|---|---|
| Layers / extension / confirmation / runtime ownership | `ARCHITECTURE.md` |
| ADR rationale | `07_ARCHITECTURE_DECISIONS.md` |
| Domain / object lifecycle specs | Implementation specs cited in Authority Map |
| Version identifiers / breaking / deprecation **semantics** | `Release/00_VERSIONING_POLICY.md` |
| Seal **steps** | `Release/01_RELEASE_PROCESS.md` |
| Who approves RC/GA | `09_GOVERNANCE/04_RELEASE_APPROVAL_POLICY.md` |
| Milestone PASS/PENDING evidence | `Release/vX.Y/00_RELEASE_CHECKLIST.md` + `07_GO_LIVE_CHECKLIST.md` (roles: see §4) |
| Support matrix body | `Release/vX.Y/03_COMPATIBILITY.md` (`03_SUPPORT_MATRIX.md` = pointer only) |
| Public API field/command catalogs | Matching `API/*` reference + package exports |
| Documentation structure | `00_DOCUMENTATION_ARCHITECTURE.md` |
| Docs QA gates | `05_Documents/10_QUALITY/` (this folder) |

---

# 3. Conflict Detection Checklist

Mark **FAIL** if any apply:

| Failure mode | Example |
|---|---|
| Dual body | Two non-pointer files maintain the same matrix/process/policy prose |
| Competing Approved claim | Two Approved docs disagree on Supported / Unsupported for the same surface |
| Narrative redefine | `Architecture/` or Developer guide restates ADR outcomes as new rules |
| Governance as process | Governance doc lists seal CLI steps (belongs in Release Process) |
| QA as governance | Quality doc assigns merge/GA sign-off rights (belongs in Governance) |
| Pointer with body | Pointer file gains a second full matrix/process |
| Naming collision without deferral | e.g. “Deprecation Policy” title in two places without one clearly owning **semantics** |

**Allowed:** Guide + Reference (how-to vs catalog); Checklist + Go-Live if roles differ (evidence gates vs readiness summary) — see §4.

---

# 4. Known Dual-Surface Rules (allowed if roles stay distinct)

| Pair | Required split |
|---|---|
| Versioning Policy §6 ↔ `09_GOVERNANCE/03_DEPRECATION_POLICY.md` | Versioning = **semantics**; Governance = **who/how to announce/remove** |
| `00_RELEASE_CHECKLIST.md` ↔ `07_GO_LIVE_CHECKLIST.md` | Checklist = milestone **gates/evidence**; Go-Live = **RC vs GA readiness summary** — Go-Live must not invent new PASS without Checklist/Test evidence |
| API Reference ↔ Developer Guide | Reference = contract; Guide = workflow |
| Canonical `00_`/`01_`/`03_COMPATIBILITY` ↔ pointer filenames | Pointers only; tree should list both or note pointer→canonical |

If roles blur → treat as **authority conflict** and fix before Approved.

---

# 5. Validation Outcome

| Result | Meaning |
|---|---|
| **PASS** | Single authority named; no competing Approved claims; pointers clean |
| **FAIL** | Conflict or dual body — block Approved / request changes |
| **WAIVED** | Maintainer records why (rare); must not waive invented product behaviour |

---

# 6. Related Documents

| Document | Role |
|---|---|
| `00_DOCUMENT_REVIEW_CHECKLIST.md` | General review gate |
| `03_TRACEABILITY_RULES.md` | Required upward links |
| `09_GOVERNANCE/02_ARCHITECTURE_DECISION_POLICY.md` | ADR change governance |
