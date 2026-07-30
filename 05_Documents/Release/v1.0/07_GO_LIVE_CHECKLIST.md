# v1.0 Go-Live Checklist

## Status

Approved

## Audience

Release Engineer, Maintainer

## Authority

Official **go-live / public-release readiness** summary for the NOVA Layer **v1.0** product milestone, based solely on existing Release evidence.

Governing sources (do not invent new verification):

- `05_Documents/Release/v1.0/00_RELEASE_CHECKLIST.md`
- `05_Documents/Release/v1.0/04_TEST_REPORT.md`
- `05_Documents/Release/v1.0/05_SECURITY_REPORT.md`
- `05_Documents/Release/v1.0/06_MIGRATION_GUIDE.md`
- `05_Documents/Release/01_RELEASE_PROCESS.md`
- `05_Documents/Release/00_VERSIONING_POLICY.md`
- `00_Project/01_Implementation/08_RELEASE_READINESS_REVIEW.md` (RC review **process** areas — not a scored GA pass)

**Result vocabulary** (same as Release Checklist)

| Result | Meaning |
|---|---|
| **PASS** | Existing document cites evidence today |
| **PENDING** | Required for **GA / public ship** claim; evidence missing or explicitly incomplete |
| **N/A** | Out of scope for the stated claim |

### Critical separation

| Claim | Status in this document |
|---|---|
| **v1.0 RC** documentation + sealed **`0.1.4`** candidate readiness | Evaluated below; may **PASS** where Release Checklist / Test Report already PASS |
| **GA / public release** (including packaging `1.0.0`, live-tree seal, publish) | **PENDING** — see §6–§7 |

This document does **not** invent human sign-off, PyPI publish, or CI run IDs.

---

# 1. Scope

### In scope

- Whether existing Approved Release docs and the sealed `0.1.4` artifact set support an **RC** readiness statement.  
- Whether the same evidence supports a **GA / public release** statement.  
- Exact **GA blockers** already recorded in Checklist / Test / Security / Migration / Process.

### Out of scope

- Rerunning tests, seals, or audits.  
- Speculative work plans or invented mitigations.  
- Claiming Compliance / certification (Security Report non-claims).

| Field | Value (from existing docs) |
|---|---|
| Docs milestone | **v1.0 RC** |
| Latest sealed candidate | `nova-layer` **`0.1.4`** → `08_Release/nova-layer-0.1.4-fc1b1af9ad04/` |
| Live packaging (Checklist write) | **`0.1.5.dev0`** — not the sealed version |
| In-repo automated publish / CD | **Not provided** (Release Process / Known Limitations) |

---

# 2. Documentation Readiness

| Item | RC claim | GA claim | Evidence |
|---|---|---|---|
| Versioning Policy | **PASS** | **PASS** (rules exist) | Checklist §2; Status Approved |
| Release Process | **PASS** | **PASS** (process exists) | Checklist §2 |
| Release Notes | **PASS** | **PENDING** (GA ship narrative / version alignment) | Checklist §2; Versioning Policy §7 |
| Known Limitations | **PASS** | **PASS** (limits disclosed) | Checklist §2 |
| Compatibility | **PASS** | **PASS** (matrix disclosed) | Checklist §2 |
| Release Checklist | **PASS** | **PENDING** (GA decisions PENDING) | Checklist §7 |
| Test Report | **PASS** (sealed `0.1.4`) | **PENDING** (no GA-commit CI / live seal) | Test Report §§2–5 |
| Security Report | **PASS** (RC trust model) | **PENDING** (no GA security approval claimed) | Security Report §§6–7 |
| Migration Guide | **PASS** (unsupported paths honest) | **PENDING** (does not unblock GA alone) | Migration Guide §7 |
| This Go-Live Checklist | **PASS** (filled) | Evaluates GA below | this document |
| ARCHITECTURE + Public API Overview | **PASS** | **PASS** as RC authority | Checklist §2 |

**Documentation readiness verdict**

| Verdict | Result | Evidence |
|---|---|---|
| RC documentation package ready | **PASS** | Checklist §7.1 |
| GA documentation / ship package ready | **PENDING** | Checklist §7.1; this §7 |

---

# 3. Verification Readiness

| Item | RC (`0.1.4` seal) | GA / live tree | Evidence |
|---|---|---|---|
| Wheel `valid: true` | **PASS** | **PENDING** (new seal needed if shipping live) | Test Report §2; Checklist §3 |
| Install-smoke + `gui_startup_passed` | **PASS** | **PENDING** | Test Report §2; Checklist §3 |
| Acceptance 9/9 (Phase 1 suite) | **PASS** | **PENDING** | Test Report §3; Checklist §3 |
| Suite identity disclosed (not OW-branded) | **PASS** | **PENDING** if OW-branded suite required for GA | Test Report §3; Checklist §3 |
| `nova-release-audit` VALID | **PASS** | **PENDING** for any new seal | Checklist §3 / §5 |
| Offline CI for sealed commit | **PENDING** | **PENDING** | Checklist §3; Test Report §4 |
| Offline CI for live `0.1.5.dev0` | **PENDING** | **PENDING** | Checklist §3 |
| `real_model` / `real_host` / full `tests/ui/` | **N/A** (Not Verified for RC claim) | **PENDING** only if GA claims them | Compatibility; Known Limitations |

**Verification readiness verdict**

| Verdict | Result | Evidence |
|---|---|---|
| Sealed `0.1.4` Release Process verification | **PASS** | Test Report §5; Checklist §7.2 |
| Verification sufficient for GA / public ship of live tree | **PENDING** | Checklist §3 PENDING rows; Test Report gaps |

---

# 4. Packaging Readiness

| Item | Result | Evidence |
|---|---|---|
| Sealed `0.1.4` directory present + manifest format 3 | **PASS** | Checklist §5; Test Report |
| Wheel SHA matches manifest | **PASS** | Checklist §5 |
| Prose docs not inside `08_Release/` | **PASS** | Checklist §5; Release Process §7 |
| Live tree equals sealed `0.1.4` | **PENDING** | Checklist §1 / §5 / §7.2 (`0.1.5.dev0`) |
| Sealed distribution `1.0.0` | **PENDING** | Checklist §5; Versioning Policy §7 |
| Docs milestone may differ from packaging for **RC** | **PASS** | Versioning Policy §3 / §7; Checklist §1 |

**Packaging readiness verdict**

| Verdict | Result | Evidence |
|---|---|---|
| RC packaging candidate (`0.1.4` seal) | **PASS** | Checklist §7.2 |
| GA packaging identity / live-tree seal | **PENDING** | Checklist §7.2 |

---

# 5. Distribution Readiness

| Item | Result | Evidence |
|---|---|---|
| Manual seal toolchain documented | **PASS** | Release Process §§5–6 |
| Artifacts redistributable after `nova-release-audit` | **PASS** for `0.1.4` | Checklist audit PASS; Release Process §9 |
| In-repo CI builds/seals/publishes wheels | **PENDING** / **Unsupported** as automation | Known Limitations §7; Release Process Explicit Non-Claims |
| In-repo PyPI / GitHub Release publish pipeline | **PENDING** / **Unsupported** | Known Limitations §7; Release Process; Compatibility §6 |
| Corporate/PyPI publish runbook in-repo | **PENDING** | Release Process Documentation Gaps |
| Claim “public GA release completed” | **PENDING** | No publish evidence in Release docs |

**Distribution readiness verdict**

| Verdict | Result | Evidence |
|---|---|---|
| Local sealed-candidate distribution (`08_Release/`) for RC | **PASS** | Seal + audit evidence |
| Public / automated GA distribution | **PENDING** | Process non-claims; Checklist GA blockers |

---

# 6. GA Blockers

Exact blockers evidenced in Approved Release docs (not speculative roadmap items):

1. **Live packaging not sealed** — Checklist: live **`0.1.5.dev0`** ≠ sealed **`0.1.4`**; Artifact Gate PENDING for current-tree seal.  
2. **No sealed `1.0.0`** — Checklist / Versioning Policy: GA packaging alignment not cut.  
3. **Offline CI evidence missing** for sealed commit and for live tree — Checklist §3; Test Report §4.  
4. **OW-branded sealed acceptance suite missing** — Checklist §3; Test Report; Known Limitations §5 (Phase 1 suite used; disclosed).  
5. **No in-repo publish / CD evidence** — Known Limitations §7; Release Process Explicit Non-Claims; Compatibility §6.  
6. **GA security approval not claimed** — Security Report §6 / GA gaps (trust model documented; compliance/pen-test not attached).  
7. **Human GA sign-off blank** — Checklist §7.3; this §7.  
8. **Release Readiness Review** (`08_RELEASE_READINESS_REVIEW.md`) defines review **areas**; it is **not** recorded here as a completed scored GA pass.

Optional lanes (GPU, commercial hosts, full UI CI, macOS/Windows CI) remain **Not Verified**. They block GA **only if** GA Release Notes / Compatibility claim them as Supported — today they do not claim Supported (Compatibility §§4–5).

---

# 7. Approval Summary

### 7.1 Release Candidate

| Decision | Result | Evidence |
|---|---|---|
| Approve **v1.0 RC documentation set** for the milestone | **PASS** | Checklist §7.1; docs Status Approved |
| Approve **sealed `0.1.4`** as a valid Release Process candidate | **PASS** | Checklist §7.2; Test Report §5 |
| Approve **live `0.1.5.dev0` tree** as that sealed candidate | **PENDING** | Checklist §7.2 |

### 7.2 General Availability / public release

| Decision | Result | Evidence |
|---|---|---|
| Approve **GA / public release** of v1.0 | **PENDING** | §6 GA Blockers; Checklist §7.2 |
| Approve packaging identity **`1.0.0`** ship | **PENDING** | No such seal; Versioning Policy §7 |
| Approve public publish (PyPI / GitHub Release / CD) | **PENDING** | No in-repo publish evidence |

### 7.3 Final approval status (this document)

| Claim | Final status |
|---|---|
| **RC ready** (docs + sealed `0.1.4`) | **PASS** (evidence-backed) |
| **GA / public release ready** | **PENDING** (blocked — §6) |

### 7.4 Human sign-off

| Role | Name | Date | Outcome for **RC** | Outcome for **GA** |
|---|---|---|---|---|
| Release Engineer | | | | |
| Maintainer | | | | |

Record seal path, wheel SHA-256, and `pyproject.toml` version at sign-off. Do not mark GA **PASS** without clearing §6 blockers and attaching new evidence to Checklist / Test Report.

---

# 8. Related Documents

| Document | Role |
|---|---|
| `v1.0/00_RELEASE_CHECKLIST.md` | Master PASS/PENDING gates |
| `v1.0/04_TEST_REPORT.md` | Sealed verification evidence |
| `v1.0/05_SECURITY_REPORT.md` | Trust model / non-claims |
| `v1.0/06_MIGRATION_GUIDE.md` | Upgrade / non-migration paths |
| `v1.0/01_RELEASE_NOTES.md` | RC scope + seal citation |
| `v1.0/02_KNOWN_LIMITATIONS.md` | Accepted / Not Verified limits |
| `v1.0/03_COMPATIBILITY.md` | Support matrix |
| `01_RELEASE_PROCESS.md` | Seal / non-publish automation |
| `00_VERSIONING_POLICY.md` | RC vs GA version identity |
| `08_Release/nova-layer-0.1.4-fc1b1af9ad04/` | Artifact evidence |
| `00_Project/01_Implementation/08_RELEASE_READINESS_REVIEW.md` | RC engineering review process |

---

## Document control

| Field | Value |
|---|---|
| Evidence basis | Existing Approved v1.0 Release docs + sealed `0.1.4` citations only |
| New verification for this doc | **None** |
| Invented approvals | **None** |
| GA / public release | **PENDING** |
