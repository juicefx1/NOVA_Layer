# v1.0 Release Checklist

## Status

Approved

## Audience

Release Engineer, Maintainer

## Authority

Official **Release Candidate approval checklist** for the NOVA Layer **v1.0 RC** product milestone.

Governing process (do not duplicate steps):

- `05_Documents/Release/01_RELEASE_PROCESS.md`

Governing versioning:

- `05_Documents/Release/00_VERSIONING_POLICY.md`

**Rules for this checklist**

| Result | Meaning |
|---|---|
| **PASS** | Evidence exists today and is cited below |
| **PENDING** | Required for a stronger claim (current-tree seal, GA, or unfilled doc) — **no invented evidence** |
| **N/A** | Explicitly out of scope for this RC claim |

This checklist evaluates:

1. **Docs milestone v1.0 RC** (architecture / Release docs)  
2. **Sealed distribution candidate `0.1.4`** under `08_Release/`  

It does **not** claim that live `pyproject.toml` equals that seal, or that GA is approved.

---

# 1. Release Information

| Field | Value | Evidence |
|---|---|---|
| Product milestone | **v1.0 RC** | `ARCHITECTURE.md` status; `v1.0/01_RELEASE_NOTES.md` |
| Sealed package | `nova-layer` **`0.1.4`** | `08_Release/nova-layer-0.1.4-fc1b1af9ad04/release_manifest.json` |
| Seal directory | `08_Release/nova-layer-0.1.4-fc1b1af9ad04/` | filesystem + Release Notes §1 |
| Wheel SHA-256 | `fc1b1af9ad0485d1c40478912cfe7271aee20e3332d810aa7b131aef931619e6` | `release_manifest.json` |
| Seal created_at | `2026-07-23T16:16:31.448332+00:00` | `release_manifest.json` |
| Live tree packaging version | **`0.1.5.dev0`** (as read from `02_Source/pyproject.toml` at checklist write) | `pyproject.toml` — **not** the sealed version |
| Checklist purpose | RC documentation + sealed-`0.1.4` evidence review | this document |

| Item | Result | Evidence |
|---|---|---|
| Docs milestone ≠ packaging `1.0.0` is allowed for RC | **PASS** | Versioning Policy §3 / §7; Release Notes §1 |
| Live tree is the sealed `0.1.4` commit | **PENDING** | Live version `0.1.5.dev0` ≠ sealed `0.1.4` |

---

# 2. Documentation Gate

| Item | Result | Evidence |
|---|---|---|
| Versioning Policy Approved | **PASS** | `05_Documents/Release/00_VERSIONING_POLICY.md` Status: Approved |
| Release Process Approved | **PASS** | `05_Documents/Release/01_RELEASE_PROCESS.md` Status: Approved |
| Release Notes Approved | **PASS** | `v1.0/01_RELEASE_NOTES.md` Status: Approved |
| Known Limitations Approved | **PASS** | `v1.0/02_KNOWN_LIMITATIONS.md` Status: Approved |
| Compatibility / support matrix Approved | **PASS** | `v1.0/03_COMPATIBILITY.md` Status: Approved (`03_SUPPORT_MATRIX.md` pointer) |
| Release Notes do not claim marketplace / HTTP Automation / Schema 1.0→2.0 migrator | **PASS** | Release Notes §3 “Explicitly not claimed…” |
| Known Limitations label Not Verified lanes (GPU, hosts, full UI CI) | **PASS** | Known Limitations §§2, 6, 7 |
| Compatibility lists Supported vs Unsupported vs Not Verified | **PASS** | Compatibility §§2–5 |
| `v1.0/04_TEST_REPORT.md` filled | **PASS** | Status: Approved; cites sealed `0.1.4` reports only |
| `v1.0/05_SECURITY_REPORT.md` filled | **PASS** | Status: Approved; trust model from ARCHITECTURE / Known Limitations / Plugin SDK / OW implementation |
| `v1.0/06_MIGRATION_GUIDE.md` filled | **PASS** | Status: Approved; Schema 1.0→2.0 unsupported; within-2.0 back-fill documented |
| `v1.0/07_GO_LIVE_CHECKLIST.md` filled | **PASS** | Status: Approved; RC PASS / GA PENDING with evidenced blockers |
| ARCHITECTURE authoritative for v1.0 RC | **PASS** | `00_Project/01_Implementation/ARCHITECTURE.md` header |
| Public API Overview Approved | **PASS** | `05_Documents/API/00_PUBLIC_API_OVERVIEW.md` Status: Approved |

---

# 3. Verification Gate

Process tools: Release Process §§5–6. Evidence below is from the **sealed `0.1.4` directory** unless noted.

| Item | Result | Evidence |
|---|---|---|
| Wheel verification report `valid: true` | **PASS** | `…/nova_layer-0.1.4-wheel.json` → `"valid": true` |
| Install-smoke `valid: true` | **PASS** | `…/nova_layer-0.1.4-install-smoke.json` → `"valid": true` |
| Install-smoke `gui_startup_passed: true` | **PASS** | same file → `"gui_startup_passed": true` |
| Acceptance embedded `passed == total` | **PASS** | `release_manifest.json` acceptance `9/9`; `phase1_acceptance_latest.json` all `passed` |
| Acceptance suite identity disclosed | **PASS** | Suite title “NOVA Layer Phase 1 Acceptance”; Release Notes §4.1 caveat |
| Object Workflow–branded sealed acceptance suite | **PENDING** | No separate OW-named sealed acceptance artifact; Known Limitations §5 |
| `nova-release-audit` on seal directory | **PASS** | CLI output: `NOVA release candidate: VALID · 4 files checked` (re-run for this checklist) |
| Offline CI green for **sealed `0.1.4` commit** | **PENDING** | No CI run log attached to this checklist for that commit SHA |
| Offline CI green for **live `0.1.5.dev0` tree** | **PENDING** | Not cited here; run Release Process §5.A to produce evidence |
| `real_model` lane verified for RC claim | **N/A** | Explicitly Not Verified — Known Limitations / Compatibility |
| `real_host` lane verified for RC claim | **N/A** | Explicitly Not Verified |
| Full `tests/ui/` as CI gate | **N/A** | Explicitly Not Verified / excluded from CI |

---

# 4. Compatibility Gate

| Item | Result | Evidence |
|---|---|---|
| Project Schema Supported = `"2.0"` only | **PASS** | Compatibility §2.1; Versioning Policy; Schema Reference |
| Plugin SDK Supported = `"1.0"` | **PASS** | Compatibility §2.1 |
| Package format Supported = `"1.0"` | **PASS** | Compatibility §2.1 |
| Intent schema Supported = `nova.intent.guidance.v1` | **PASS** | Compatibility §2.1 |
| Python packaging range `>=3.12,<3.14` | **PASS** | `pyproject.toml`; Compatibility §4 |
| CI Python 3.12 on Ubuntu documented | **PASS** | Compatibility §4; `.github/workflows/ci.yml` |
| macOS/Windows claimed as CI-supported | **N/A** | Compatibility marks **Not Verified** |
| GPU production claimed Supported | **N/A** | Compatibility / Known Limitations: **Not Verified** |
| Unsupported list includes no Schema 1.0→2.0 migrator | **PASS** | Compatibility §3; Known Limitations §3 |
| Deployment-dependent hosts/plugins called out | **PASS** | Compatibility §5 / operator checklist |

---

# 5. Artifact Gate

| Item | Result | Evidence |
|---|---|---|
| Seal directory present under `08_Release/` | **PASS** | `08_Release/nova-layer-0.1.4-fc1b1af9ad04/` |
| Manifest `format_version` 3 | **PASS** | `release_manifest.json` → `format_version: 3` |
| Wheel file present | **PASS** | `nova_layer-0.1.4-py3-none-any.whl` |
| Wheel + smoke + acceptance reports present | **PASS** | listed in `release_manifest.json` `artifacts` |
| Manifest SHA matches wheel file entry | **PASS** | `wheel_sha256` == files[0].sha256 in manifest |
| Seal audit VALID | **PASS** | `nova-release-audit` → VALID |
| Prose docs not stored inside `08_Release/` | **PASS** | Directory contains only wheel/reports/manifest (Release Process §7) |
| Current live tree sealed as RC candidate | **PENDING** | Live `0.1.5.dev0`; no `08_Release/nova-layer-0.1.5*` seal observed |
| Distribution version `1.0.0` sealed | **PENDING** | No such seal; Versioning Policy allows RC without it |

---

# 6. Known Limitations Review

| Item | Result | Evidence |
|---|---|---|
| Limitations doc Approved and cited by Release Notes | **PASS** | `02_KNOWN_LIMITATIONS.md`; Release Notes §5/§7 |
| Explicit confirmation / no silent desktop auto-confirm | **PASS** | Known Limitations §8; ARCHITECTURE |
| Local plugins only / no marketplace | **PASS** | Known Limitations §4 |
| In-process Automation only | **PASS** | Known Limitations §5 |
| Plugin Install UI absent in OW panel | **PASS** | Known Limitations §2 |
| Phase 1 acceptance naming caveat acknowledged | **PASS** | Known Limitations §5; Release Notes §4.1 |
| GA publish/CD not claimed | **PASS** | Known Limitations §7; Release Process non-claims |

---

# 7. Approval Summary

### 7.1 RC documentation package

| Decision | Result | Rationale |
|---|---|---|
| Approve **v1.0 RC documentation set** (policy, process, notes, limitations, compatibility) | **PASS** | All five Approved with cross-consistent non-claims |
| Approve **GA documentation package** | **PENDING** | Go-Live Checklist Approved but GA decisions remain PENDING (§7 / Go-Live §7) |

### 7.2 Sealed distribution `0.1.4`

| Decision | Result | Rationale |
|---|---|---|
| Approve **sealed candidate `0.1.4`** as a valid Release Process seal | **PASS** | Wheel/smoke/acceptance reports + `nova-release-audit` VALID |
| Approve **live tree `0.1.5.dev0`** as that same sealed candidate | **PENDING** | Version mismatch; needs new seal |
| Approve **GA / `1.0.0` ship** | **PENDING** | GA blockers below |

### 7.3 Sign-off (human)

| Role | Name | Date | Outcome (PASS / PENDING / REJECT) |
|---|---|---|---|
| Release Engineer | | | |
| Maintainer | | | |

Record the seal path and live `pyproject` version at sign-off time.

---

## GA Blockers (from this checklist)

1. Live packaging **`0.1.5.dev0`** not sealed; only **`0.1.4`** audit **PASS**.  
2. No sealed **`1.0.0`** (if GA identity requires it per Versioning Policy alignment).  
3. Offline CI evidence for the **exact** GA commit **PENDING** (not attached here).  
4. OW-branded sealed acceptance suite **PENDING** (Phase 1 suite used as seal input — disclosed).  
5. No in-repo publish / CD evidence (Release Process / Known Limitations non-claims).  
6. GA security approval not claimed (Security Report).  
7. Human GA sign-off blank (Checklist §7.3; Go-Live §7.4).  
8. See `07_GO_LIVE_CHECKLIST.md` §6 for the consolidated GA blocker list.  

---

## Related Documents

| Document | Role |
|---|---|
| `01_RELEASE_PROCESS.md` | How to produce evidence |
| `00_VERSIONING_POLICY.md` | Version identity rules |
| `01_RELEASE_NOTES.md` | RC scope + seal citation |
| `02_KNOWN_LIMITATIONS.md` | Accepted limits |
| `03_COMPATIBILITY.md` | Support matrix |
| `08_Release/nova-layer-0.1.4-fc1b1af9ad04/` | Artifact evidence |

---

## Documentation Gaps Noted in Checklist

- No commit SHA recorded in seal manifest for mapping live git → `0.1.4`.  
- Release Notes “Documentation Gaps” still mentions Limitations/Support Matrix as placeholders (stale relative to current Approved status) — does not change PASS on those docs’ Status headers.  
