# v1.0 Migration Guide

## Status

Approved

## Audience

End User, Integrator, Developer, Plugin Author, Release Engineer, Maintainer

## Authority

Official **migration / upgrade path** guidance for the NOVA Layer **v1.0 RC** product milestone.

Governing rules (do not invent alternate semantics):

- `05_Documents/Release/00_VERSIONING_POLICY.md`
- `05_Documents/Release/v1.0/03_COMPATIBILITY.md`
- `05_Documents/Release/v1.0/02_KNOWN_LIMITATIONS.md`

Schema field behaviour:

- `05_Documents/API/04_SCHEMA_REFERENCE.md`

**Non-claims**

- No Schema **1.0 → 2.0** project migrator.  
- No cross-major Plugin SDK migration tooling.  
- No soft-load / deprecation grace for wrong version strings.  
- No speculative future migrators.  
- Does **not** claim GA packaging alignment (`1.0.0`).

---

# 1. Scope

### In scope

| Topic | Covered |
|---|---|
| Object Workflow Project Schema **`"2.0"`** load / continue-use | Yes |
| Same-major Schema **2.0** in-memory generation history back-fill | Yes (verified) |
| Distribution package install / seal swap | Yes (packaging identity only) |
| Plugin packages already on Supported SDK / package format | Yes (reinstall / replace) |
| Explicit **unsupported** upgrade paths | Yes |

### Out of scope

- Phase 1 Smart Layer Schema **1.0** as an Object Workflow input format  
- Invented converters, dual-schema loaders, or network migration services  
- Host application / GPU environment upgrades (Deployment Dependent / Not Verified — Compatibility §§4–5)  
- Changing Versioning Policy allowlists (breaking-change process, not a migrator)

**Product reminder:** Welcome-screen **Create Project** / **Open Project** are Smart Layer paths. Object Workflow uses the **Object Workflow** window (**Getting Started** / **User Guide**).

---

# 2. Supported Migration Paths

Only paths with verified Core behaviour:

### 2.1 Continue Schema `"2.0"` Object Workflow projects

| From | To | Behaviour |
|---|---|---|
| Existing OW Project with `schema_version` **`"2.0"`** | Same Schema 2.0 under v1.0 RC Core | **Supported** — `JsonProjectStore` accepts only `"2.0"`; conforming documents load |

Evidence: Versioning Policy §4.1; Compatibility §2.1; `JsonProjectStore` rejects non-`"2.0"`.

### 2.2 Same-major Schema 2.0 generation-history back-fill (in memory)

| From | To | Behaviour |
|---|---|---|
| Older Schema **2.0** documents with empty `generation_records` but existing `candidate_sets` | In-memory project with synthesized `generation_records` | **Supported** via `migrate_project_generation_history` after successful parse |

| Property | Verified fact |
|---|---|
| Schema change | Remains **`"2.0"`** — not a Schema 1.0→2.0 path |
| Disk rewrite | **Does not** rewrite the on-disk package by itself (Schema Reference §8; Known Limitations §3) |
| Persist derived records | Save the project explicitly if disk persistence of back-filled records is required |

### 2.3 Distribution package upgrade (wheel / install)

| From | To | Behaviour |
|---|---|---|
| Prior `nova-layer` install | Newer wheel (e.g. sealed `0.1.4` or later packaging) | **Supported as packaging install** when contracts remain Compatible per Versioning Policy |

| Caveat | Evidence |
|---|---|
| Docs milestone **v1.0 RC** ≠ requirement for packaging `1.0.0` | Versioning Policy §3 / §7; Compatibility §2.2 |
| Live tree `.devN` ≠ sealed candidate until Release Process re-seal | Compatibility §2.2; Release Notes |
| Contract allowlist removals are **breaking** | Versioning Policy §5 — must be called out in Release Notes |

This path does **not** convert Project Schema or Plugin SDK versions by itself.

### 2.4 Plugins already on Supported SDK / package format

| From | To | Behaviour |
|---|---|---|
| Local `.nova-plugin` / directory with `sdk_version` ∈ `SUPPORTED_SDK_VERSIONS` and `package_format` ∈ `SUPPORTED_PACKAGE_FORMATS` (currently `"1.0"`) | Reinstall / replace on the same allowlists | **Supported** (local package manager; `replace=True` when updating an existing install) |

Wrong `sdk_version` / `package_format` → **hard reject** (no migrator). Compatibility §3; Versioning Policy §4.3.

### 2.5 New Object Workflow work (greenfield)

| Action | Status |
|---|---|
| Create a new OW project in the Object Workflow UI and re-do source → intent → confirm → extract → export | **Supported** product path (User Guide) |
| Use this to replace Phase 1 assets that cannot load in OW | **Manual** only — see §4 |

---

# 3. Unsupported Migration Paths

| Path | Status | Verified basis |
|---|---|---|
| Schema **1.0** (Phase 1 Smart Layer) → Schema **2.0** Object Workflow automatic conversion | **Unsupported** | Versioning Policy §4.3 / §8; Compatibility §3; Known Limitations §3; no migrator in Core |
| Load `schema_version` ≠ `"2.0"` in Object Workflow | **Unsupported** | Hard reject (`UNSUPPORTED_SCHEMA`) |
| Soft-load / deprecation grace for wrong schema, SDK, or package format | **Unsupported** | Versioning Policy §6 |
| Cross-major Plugin SDK migration tools | **Unsupported** | Versioning Policy §4.3; Compatibility §3; Known Limitations §4 |
| Automatic rewrite of on-disk Project after generation-history back-fill | **Unsupported** as automatic behaviour | Schema Reference; Known Limitations §3 |
| Guaranteed forward-compat for unknown Project JSON keys | **Unsupported** | `extra="forbid"`; Compatibility §3 |
| Remote plugin marketplace “upgrade” pipeline | **Unsupported** | Compatibility §3 |
| HTTP/REST/WebSocket/RPC Automation “version upgrade” | **Unsupported** | No such transport in Core |
| Treating Welcome **Create Project** projects as OW Schema 2.0 | **Unsupported** expectation | Separate bounded context (ADR-001); User Guide |

---

# 4. Manual Migration

When an automatic path does not exist, operators may use these **manual** steps. They are operational procedures, not Core migrators.

### 4.1 Phase 1 / Schema 1.0 work → Object Workflow

1. Keep Phase 1 projects on the Smart Layer path if still needed (separate context).  
2. Open **Object Workflow** (not welcome **Create Project**).  
3. **Create Project** in the OW window.  
4. Load PNG/JPEG sources and recreate intent / candidates / confirmation / extraction / export as required.  
5. Do **not** expect Core to open or convert Schema 1.0 packages in OW.

### 4.2 Persist in-memory generation-history back-fill

1. Load a Schema **2.0** project that triggers `migrate_project_generation_history`.  
2. **Save** the project if derived `generation_records` must exist on disk.  
3. Without Save, disk may still lack those records (Known Limitations §3).

### 4.3 Plugin package out of allowlist

1. Update the plugin’s `manifest.json` / `package.json` so `sdk_version` and `package_format` match Supported sets (currently `"1.0"`).  
2. Rebuild the local `.nova-plugin` if applicable.  
3. Install with the local package manager (`replace=True` if already installed).  
4. There is **no** Core tool that rewrites old major SDK packages into new majors.

### 4.4 Distribution / sealed candidate swap

1. Prefer audited seal under `08_Release/` (Release Process).  
2. Install the wheel from that directory; verify SHA against Release Notes / Test Report.  
3. Do not assume live `pyproject.toml` matches the seal.  
4. Re-check plugins and Deployment Dependent hosts after install.

### 4.5 Intent schema mismatch

1. Ensure Artist Intent uses `nova.intent.guidance.v1` (Application validation).  
2. Wrong intent schema id is **rejected** — fix at authoring time; no intent-schema migrator.

---

# 5. Compatibility Notes

| Topic | Migration implication |
|---|---|
| Independent version surfaces | Bumping `nova-layer` packaging does not migrate Schema or SDK strings (Versioning Policy §3) |
| Exact string membership | Schema / SDK / package format are allowlist/literal checks — not SemVer range negotiation |
| Additive allowlist growth | New Supported SDK/format values would be Compatible for newly built plugins; removal is Breaking (§5 Versioning Policy) |
| Within Schema 2.0 | Optional field / in-memory back-fill rules per Schema Reference — still not Schema 1.0 support |
| Deployment Dependent | Hosts, models, plugins must be re-validated after package upgrades (Compatibility §5) |
| Platform | Python 3.12 CI-supported; macOS/Windows / GPU Not Verified — no OS migrator claims |

Full matrix: **Compatibility**. Rules authority: **Versioning Policy**.

---

# 6. Known Limitations

Migration-relevant limits (see Known Limitations for full tables):

| Limitation | Kind |
|---|---|
| No Schema **1.0 → 2.0** migrator | Unsupported |
| Only `"2.0"` loads in Object Workflow | Unsupported otherwise |
| No cross-major SDK migration tools | Unsupported |
| Hard reject of wrong version strings (no soft-load) | Intentional |
| Generation-history back-fill does not rewrite disk alone | Intentional |
| Docs milestone v1.0 RC may use packaging ≠ `1.0.0` | Intentional |
| Schema 2.0 / Schema 1.0 split (ADR-001) | Intentional |

---

# 7. Conclusion

### What v1.0 RC supports for “migration”

1. **Stay on Schema 2.0** Object Workflow projects.  
2. **In-memory** generation-history back-fill within Schema 2.0 (Save to persist).  
3. **Packaging** upgrades that preserve public contracts.  
4. **Local plugin** reinstall when already on Supported SDK / package format.  
5. **Manual** recreation of work that lived only in Phase 1 Schema 1.0.

### What it does not support

- Any automatic Schema **1.0 → 2.0** conversion.  
- Soft compatibility or invented migration tooling.  

### Remaining migration gaps

1. No Core project converter for Phase 1 → OW.  
2. No mandatory on-disk rewrite after generation back-fill.  
3. No cross-major SDK migrator.  
4. Packaging identity may still be pre-`1.0.0` while docs say v1.0 RC.  
5. GA checklist / Go-Live still separate from this guide.

### GA impact

This guide **documents RC non-support honestly**. It does **not** unblock GA by itself. GA still needs Go-Live checklist completion, intentional packaging alignment if required, and Release Checklist Artifact/Verification PENDING items — not a Schema 1.0 migrator claim.

---

# 8. Related Documents

| Document | Role |
|---|---|
| `00_VERSIONING_POLICY.md` | Compatibility rules / non-guarantees |
| `v1.0/03_COMPATIBILITY.md` | Supported / Unsupported matrix |
| `v1.0/02_KNOWN_LIMITATIONS.md` | Accepted limits |
| `v1.0/01_RELEASE_NOTES.md` §6 | Upgrade notes |
| `v1.0/00_RELEASE_CHECKLIST.md` | Gate status |
| `05_Documents/API/04_SCHEMA_REFERENCE.md` | Generation back-fill detail |
| `05_Documents/User/00_GETTING_STARTED.md` | Correct OW entry path |
| `05_Documents/User/01_USER_GUIDE.md` | Create Project in OW |

---

## Document control

| Field | Value |
|---|---|
| Milestone | v1.0 RC |
| Schema 1.0 → 2.0 migrator | **Not provided** |
| Invented tooling | **None** |
| GA migration completeness | **Not claimed** |
