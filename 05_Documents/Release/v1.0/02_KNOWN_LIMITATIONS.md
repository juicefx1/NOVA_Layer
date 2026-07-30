# v1.0 Known Limitations

## Status

Approved

## Audience

End User, Integrator, Developer, Release Engineer, Maintainer

## Authority

Official list of **intentional limitations** and **accepted unverified lanes** for the NOVA Layer **v1.0 RC** product milestone.

Governing documents:

- `05_Documents/Release/v1.0/01_RELEASE_NOTES.md`
- `05_Documents/Release/00_VERSIONING_POLICY.md`
- `05_Documents/Release/01_RELEASE_PROCESS.md`
- `00_Project/01_Implementation/ARCHITECTURE.md`

This document lists **verified** product/contract limits. It does **not** catalog temporary bugs, speculate on roadmaps, or invent unsupported features as if planned.

**How to read entries**

| Label | Meaning |
|---|---|
| **Unsupported** | Not provided by Core; attempts fail or have no API |
| **Not Verified** | May exist in code/tests but is outside the sealed/CI claim for this RC |
| **Intentional** | By design; not a defect |

---

# 1. Scope

Applies to the **v1.0 RC** Object Workflow milestone (Schema **2.0**), including desktop Object Workflow, Plugin SDK, Automation, and distribution sealing as documented in Release Notes.

**Out of this limitations list**

- Defect triage / issue tracker items  
- Phase 1 Smart Layer feature gaps (separate bounded context), except where they affect upgrade expectations  
- Speculative future platforms or cloud services  

Platform matrices: see `03_COMPATIBILITY.md` (support matrix). Treat GPU / commercial-host / full UI automation as **Not Verified** unless that document or a sealed/CI report says otherwise.

---

# 2. Desktop UI

| Limitation | Kind | Expectation |
|---|---|---|
| Welcome **Create Project** / **Open Project** are Smart Layer paths, not Object Workflow | Intentional | Use **Object Workflow** for Schema 2.0 work ([Getting Started](../../User/00_GETTING_STARTED.md)) |
| Object Workflow **Plugins** panel is status-only (no Install button) | Unsupported (UI) | Observe discovered plugins in-app; package install is via Plugin SDK / package manager APIs, not this panel ([User Guide](../../User/01_USER_GUIDE.md)) |
| Source images limited to PNG/JPEG in the Load Source dialog | Intentional | Use supported filters only |
| Precision Extraction UI spin ranges may be **narrower** than Domain Schema maxima | Intentional (UI clamp) | Schema allows wider ranges; desktop controls may cap lower (e.g. feather/blur/expand) |
| Host delivery (**Send to Host**) depends on installed/available adapters | Not Verified / conditional | **Export PNG** remains the baseline deliverable when hosts are unavailable |
| Full interactive UI test suite (`tests/ui/`) is **not** a CI gate | Not Verified as CI | Sealed install-smoke includes an offscreen GUI probe only (Release Notes) |
| GPU quality / commercial host production behaviour | Not Verified | Do not assume seal or CI covered these lanes |

---

# 3. Project Compatibility

| Limitation | Kind | Expectation |
|---|---|---|
| Only Project `schema_version` **`"2.0"`** loads in Object Workflow | Unsupported otherwise | Non-`2.0` → unsupported schema error |
| No Schema **1.0 → 2.0** project migrator | Unsupported | Phase 1 Schema 1.0 projects are a separate type/path; not convertible by Core |
| Unknown Project JSON keys rejected (`extra="forbid"`) | Intentional | Do not hand-edit unknown fields into packages |
| Intent instruction must be `nova.intent.guidance.v1` on Application validation | Unsupported otherwise | Wrong schema id rejected |
| Deep intent signal geometry is not re-validated solely by `JsonProjectStore.load` | Intentional (layering) | Application validation enforces signals on use-case paths (Schema Reference) |
| In-memory generation-history back-fill does not rewrite disk by itself | Intentional | Save explicitly if persistence of derived records is required |

Details: Versioning Policy; Schema Reference.

---

# 4. Plugin System

| Limitation | Kind | Expectation |
|---|---|---|
| Local packages only — **no** remote marketplace / download pipeline | Unsupported | Install from local `.nova-plugin` / directories |
| Plugins are **trusted local code** (no sandbox) | Intentional | Install only packages you trust |
| `sdk_version` / `package_format` outside allowlists are **hard-rejected** | Intentional | No soft-load / deprecation grace loader today |
| No cross-major SDK migration tools | Unsupported | Versioning Policy non-guarantee |
| Reloading an already-registered `plugin_id` may require **application restart** | Intentional (constraint) | Architecture §9 |
| Plugin-level `shutdown()` is **not** a reliable public callback | Intentional (current wiring) | Clean up in provider/adapter `shutdown`/`close`; see Plugin SDK Reference / Guide |
| Unknown capability strings allowed; Core does not guarantee behaviour for unknown tokens | Intentional | Use known capability vocabulary when targeting Core features |

---

# 5. Automation

| Limitation | Kind | Expectation |
|---|---|---|
| **In-process only** — no HTTP/REST/WebSocket/RPC Core transport | Unsupported | Automation Guide / ARCHITECTURE §10 |
| Plugin commands cannot override builtins | Intentional | Namespaced plugin commands only |
| Event bus: no persistence, replay, remote fan-out, or retry | Unsupported | Event Reference non-guarantees |
| Not every cancel/closed-session path emits a lifecycle event | Intentional (current emit sites) | Do not treat the bus as a complete state machine log |
| Desktop batch default is **interactive**; Automation `batch_execute` parameter defaults differ | Intentional | Pass confirmation modes explicitly; see Command Reference §6.11 |
| `batch_execute` requires a wired `BatchManager` | Unsupported otherwise | Invalid state without batch manager |
| Sealed acceptance report used by release tooling is still the **Phase 1** suite name | Not Verified as OW-named suite | Release Notes §4 — do not equate P1-AT-* with Object Workflow Schema 2.0 acceptance branding |

---

# 6. Runtime

| Limitation | Kind | Expectation |
|---|---|---|
| Runtime caches are **session-scoped** and must not be persisted into Project or Workspace | Intentional | ARCHITECTURE §7 |
| Runtime is Application-owned infrastructure, not a separate product layer | Intentional | Application and Runtime developer guide |
| Generate / extract must go through OperationExecutor | Intentional | Do not bypass for those paths |
| Coordinated shutdown is required to release executor/temp/provider resources | Intentional | Controller / service shutdown paths |
| Optional `real_model` inference behaviour | Not Verified in default CI / seal claim | Offline CI excludes that marker |

---

# 7. Distribution

| Limitation | Kind | Expectation |
|---|---|---|
| Docs milestone **v1.0 RC** ≠ packaging version `1.0.0` unless deliberately aligned | Intentional | Latest sealed example on disk: `0.1.4`; tree may be `.devN` |
| No in-repo automated wheel build, seal, or publish in CI | Unsupported (automation) | Manual Release Process only |
| No in-repo PyPI / GitHub Release publish pipeline | Unsupported | Out-of-band if performed at all |
| CI does not run `real_model`, `real_host`, or `tests/ui/` | Not Verified in CI | Developer Guide / Release Process |
| `08_Release/` holds artifacts only — not prose docs | Intentional | Documentation Architecture |
| Seal acceptance input filename remains `phase1_acceptance_*` | Intentional (tooling) | Same as Release Notes caveat |

---

# 8. Intentional Design Decisions

These are **not defects**:

1. **Explicit confirmation** — no silent AI auto-confirm as the desktop default.  
2. **Single Workspace** abstraction separate from Project Schema packages.  
3. **Additive plugins** — failures isolated; Core startup continues.  
4. **Automation mirrors Application rules** — no Domain bypass.  
5. **Hard version gates** — unsupported schema/SDK/package versions reject rather than soft-migrate.  
6. **Schema 2.0 / Schema 1.0 split** — separate bounded contexts (ADR-001).  
7. **Trusted local plugins** — security model is trust-the-installer, not sandboxing.  
8. **In-process Automation** — transport independence without shipping a remote API in Core.  

---

# 9. Related Documents

| Document | Role |
|---|---|
| `05_Documents/Release/v1.0/01_RELEASE_NOTES.md` | What is in the RC + verification evidence |
| `05_Documents/Release/v1.0/03_SUPPORT_MATRIX.md` | Environments (fill with verified rows only) |
| `05_Documents/Release/v1.0/06_MIGRATION_GUIDE.md` | Migration non-support detail when written |
| `05_Documents/Release/00_VERSIONING_POLICY.md` | Compatibility / deprecation |
| `05_Documents/Release/01_RELEASE_PROCESS.md` | Seal / CI scope |
| `05_Documents/API/00_PUBLIC_API_OVERVIEW.md` | Public API non-guarantees |
| `05_Documents/API/03_EVENT_REFERENCE.md` | Event delivery limits |
| `05_Documents/API/01_PLUGIN_SDK_REFERENCE.md` | Plugin contract limits |
| `05_Documents/User/01_USER_GUIDE.md` | Desktop expectations |
| `00_Project/01_Implementation/ARCHITECTURE.md` | Design authority |

---

## User Expectations (short)

- Use **Object Workflow** for Schema 2.0; do not expect Schema 1.0 projects to open there.  
- Confirm before extract; do not expect silent auto-confirm on the desktop default path.  
- Prefer **Export PNG** when host adapters are missing.  
- Do not expect an in-app plugin store or remote Automation.  
- Treat GPU / commercial hosts / full UI automation as **Not Verified** for this RC unless Support Matrix says otherwise.  
- Match sealed wheel version to Release Notes; do not assume the live `.devN` tree is that seal.  

## Documentation Gaps

- Support Matrix still needs verified environment rows.  
- Migration Guide still placeholder (should restate “no 1.0→2.0 migrator”).  
- No separate Object Workflow–branded sealed acceptance report yet.  
