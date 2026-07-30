# Release Approval Policy

## Status

Approved

## Audience

Release Engineer, Maintainer

## Authority

**Official release approval governance** — who may declare RC vs GA, and which documents are required.

Does **not** duplicate seal commands or CI recipes. Those live in:

- `05_Documents/Release/01_RELEASE_PROCESS.md`

Milestone evidence and PASS/PENDING vocabulary:

- `05_Documents/Release/vX.Y/00_RELEASE_CHECKLIST.md` (e.g. v1.0)
- `05_Documents/Release/vX.Y/07_GO_LIVE_CHECKLIST.md`

Version identity:

- `05_Documents/Release/00_VERSIONING_POLICY.md`

## Scope

Approval authority and decision flow for Development → RC → GA claims. Publish beyond `08_Release/` remains out-of-band when not automated in-repo (Release Process Explicit Non-Claims).

---

# 1. Purpose

Separate **how** a candidate is sealed (Release Process) from **who** may approve **RC** or **GA** documentation claims, using evidence-only checklists.

---

# 2. Ownership and Release Authority

| Decision | Authority | Required evidence |
|---|---|---|
| Run seal / audit tooling | Release Engineer (or Maintainer) | Release Process §§5–6 |
| Declare **docs milestone RC** | Maintainer + Release Engineer | Milestone Release docs Approved; honesty on Not Verified lanes |
| Approve **sealed candidate** as valid RC artifact | Release Engineer + Maintainer | Release Checklist Artifact + Verification gates **PASS** for that seal |
| Approve **live tree** as that seal | Release Engineer + Maintainer | Packaging version and commit match seal — else **PENDING** |
| Declare **GA / public release** | Maintainer + Release Engineer | Go-Live Checklist GA section **PASS**; GA blockers cleared with new evidence |
| Out-of-band publish (PyPI, GitHub Release, etc.) | Maintainer (explicit) | Not granted by seal alone; no in-repo CD authority invented here |

Human sign-off tables: milestone `00_RELEASE_CHECKLIST.md` and `07_GO_LIVE_CHECKLIST.md`.

---

# 3. Review Responsibilities

| Role | Responsibility |
|---|---|
| **Release Engineer** | Execute Process; fill Checklist / Test Report / Go-Live with cited evidence; no invented PASS |
| **Maintainer** | Final RC/GA claim authority; architecture and contract integrity |
| **Developer** | Supply fix commits; do not self-approve GA |
| Checklist/Go-Live authors | Every PASS cites existing evidence; missing → PENDING |

---

# 4. Approval Flow

### 4.1 Development

- Packaging may be `.devN` (Versioning Policy §7).  
- No RC/GA claim from Development alone.  

### 4.2 Release Candidate

1. Satisfy Release Process entry criteria (link only — do not restate commands here).  
2. Seal and audit per Release Process.  
3. Complete milestone Release Checklist gates with PASS/PENDING.  
4. Maintainer + Release Engineer sign RC decisions when Checklist §7 RC rows are evidence-backed **PASS**.  
5. Go-Live may record **RC ready PASS** while **GA remains PENDING**.  

**RC does not imply GA.** Docs milestone may differ from packaging `1.0.0` until intentionally aligned (Versioning Policy).

### 4.3 GA / public release

1. Clear Go-Live §6 GA blockers with **new** attached evidence (updated Checklist / Test Report / seal).  
2. Align packaging identity if GA requires it (Versioning Policy §7).  
3. Go-Live §7.2 GA decisions → **PASS** only with evidence.  
4. Maintainer + Release Engineer human sign-off for GA.  
5. Any public publish is a **separate** Maintainer action (Process non-claims).  

### 4.4 Rejection

If evidence is missing, mark **PENDING** or **REJECT** on sign-off tables. Do not backfill invented CI logs or seals.

---

# 5. Document Authority (release claims)

| Claim type | Authoritative docs |
|---|---|
| How to seal | `01_RELEASE_PROCESS.md` |
| What versions mean | `00_VERSIONING_POLICY.md` |
| Whether this milestone’s RC/GA gates pass | `vX.Y/00_RELEASE_CHECKLIST.md`, `vX.Y/07_GO_LIVE_CHECKLIST.md` |
| Verification summary | `vX.Y/04_TEST_REPORT.md` |
| Trust model | `vX.Y/05_SECURITY_REPORT.md` |
| Upgrade / non-migration | `vX.Y/06_MIGRATION_GUIDE.md` |

Governance policies define **who approves**; they do not replace milestone checklists.

---

# 6. Related Documents

| Document | Role |
|---|---|
| `Release/01_RELEASE_PROCESS.md` | Seal workflow |
| `Release/00_VERSIONING_POLICY.md` | RC vs GA identity |
| `Release/v1.0/00_RELEASE_CHECKLIST.md` | Current milestone gates |
| `Release/v1.0/07_GO_LIVE_CHECKLIST.md` | RC vs GA readiness |
| `00_DOCUMENT_POLICY.md` | Docs ownership |
| `03_DEPRECATION_POLICY.md` | Breaking changes before ship |
