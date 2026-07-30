# Release Document Validation

## Status

Approved

## Audience

Release Engineer, Maintainer

## Authority

**Documentation QA** for versioned Release milestone docs under `05_Documents/Release/`.

Seal workflow (do not duplicate):

- `05_Documents/Release/01_RELEASE_PROCESS.md`

Who may declare RC/GA (do not duplicate):

- `05_Documents/09_GOVERNANCE/04_RELEASE_APPROVAL_POLICY.md`

Evidence vocabulary:

- `05_Documents/Release/vX.Y/00_RELEASE_CHECKLIST.md`
- `05_Documents/Release/vX.Y/07_GO_LIVE_CHECKLIST.md`

## Scope

Validate honesty, freshness, and role split of Release documentation. Does not run tests or seal wheels.

---

# 1. Purpose

Prevent stale release documentation, invented PASS results, and blurred RC vs GA claims.

---

# 2. Milestone Set Completeness

For milestone folder `Release/vX.Y/`, confirm presence and Status:

| Doc | Role |
|---|---|
| `00_RELEASE_CHECKLIST.md` | Evidence gates |
| `01_RELEASE_NOTES.md` | User-facing scope |
| `02_KNOWN_LIMITATIONS.md` | Accepted / Not Verified |
| `03_COMPATIBILITY.md` | Support matrix body |
| `03_SUPPORT_MATRIX.md` | Pointer only (if retained) |
| `04_TEST_REPORT.md` | Verification evidence summary |
| `05_SECURITY_REPORT.md` | Trust model |
| `06_MIGRATION_GUIDE.md` | Upgrade / non-migration |
| `07_GO_LIVE_CHECKLIST.md` | RC vs GA readiness |

Stable Release docs: `00_VERSIONING_POLICY.md`, `01_RELEASE_PROCESS.md` (+ pointers if any).

---

# 3. Stale-Documentation Checks

**FAIL** if Status is **Approved** but the doc still claims:

- Sibling milestone docs are “placeholders” / “stubs” when those siblings are Approved  
- Limitations / Compatibility / Migration are unwritten when they are Approved  
- Verification results not backed by cited seal paths or Checklist PENDING  

**PASS** requires Documentation Gaps (if present) to match current Status of linked docs.

---

# 4. Evidence Honesty (PASS / PENDING)

| Rule | Detail |
|---|---|
| No invented PASS | Every Checklist/Go-Live/Test Report **PASS** cites existing evidence |
| Missing → PENDING | No CI log, no seal, no OW-branded suite → PENDING or N/A |
| RC ≠ GA | Go-Live must keep RC and GA rows distinct |
| Live tree ≠ seal | Packaging `.devN` vs sealed version must not be silently equated |
| Process non-claims | Do not claim in-repo publish/CD unless implemented |

Align with Release Checklist vocabulary; do not invent new result enums.

---

# 5. Role Split Validation

| Document | Must not |
|---|---|
| Release Process | Own GA human approval tables (Governance / Go-Live) |
| Release Approval Policy | Restate seal CLI recipes |
| Checklist | Duplicate full Test Report case lists (link instead) |
| Go-Live | Introduce PASS without Checklist/Test/Security/Migration evidence |
| Release Notes | Become a second Test Report or Compatibility matrix |

---

# 6. Architecture Trace (Release QA)

Before marking milestone Release docs **Approved** for RC:

| Check | Pass criteria |
|---|---|
| Direct or transitive Architecture link | Milestone set traces to `ARCHITECTURE.md` (see `03_TRACEABILITY_RULES.md`) |
| Non-claims match Architecture | No marketplace / remote Automation / Schema 1.0→2.0 migrator claimed as shipped |

---

# 7. Validation Outcome

| Result | Meaning |
|---|---|
| **PASS** | Milestone docs fresh, evidence-honest, roles split, RC/GA separated |
| **FAIL** | Stale gaps, invented PASS, or role blur — block RC/GA doc claims |
| **PENDING** | Acceptable only when Checklist/Go-Live themselves mark the item PENDING |

---

# 8. Related Documents

| Document | Role |
|---|---|
| `00_DOCUMENT_REVIEW_CHECKLIST.md` | General doc QA |
| `01_AUTHORITY_VALIDATION.md` | Dual-surface rules |
| `03_TRACEABILITY_RULES.md` | Release→Architecture links |
| `09_GOVERNANCE/04_RELEASE_APPROVAL_POLICY.md` | Approval authority |
