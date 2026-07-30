# v1.0 Security Report

## Status

Approved

## Audience

Release Engineer, Maintainer, Integrator

## Authority

Official **security model and trust assumptions** summary for the NOVA Layer **v1.0 RC** product milestone.

Governing product / architecture authority:

- `00_Project/01_Implementation/ARCHITECTURE.md`

Governing limitations and compatibility labels:

- `05_Documents/Release/v1.0/02_KNOWN_LIMITATIONS.md`
- `05_Documents/Release/v1.0/03_COMPATIBILITY.md`

Public plugin contract:

- `05_Documents/API/01_PLUGIN_SDK_REFERENCE.md`

Supports the Release Checklist Documentation Gate (`05_SECURITY_REPORT.md`).

**Non-claims (explicit)**

- No compliance framework (SOC 2, ISO, GDPR certification, etc.).  
- No penetration-test results or formal threat model deliverable beyond this trust description.  
- No invented mitigations or future security features.  
- Does **not** claim GA security readiness.

---

# 1. Scope

### In scope

Verified Object Workflow (Schema **2.0**) Core behaviours that define trust and execution boundaries:

| Area | Verified surface |
|---|---|
| Plugin trust | Local packages; in-process load; no Core marketplace |
| Automation | In-process sessions; permission checks; no Core remote transport |
| Path / package hardening | Plugin archive/entry checks; filesystem export validation |
| Persistence boundaries | Project vs Workspace vs temp; atomic workspace save |
| Host delivery | Baseline filesystem PNG export; other hosts deployment-dependent |

### Out of scope

- Phase 1 / browser depth-pose HTTP bridges (separate bounded context; not OW Automation)  
- Operator OS hardening, antivirus, or enterprise SSO  
- Speculative sandboxing, remote auth, or network Automation  
- Defect triage / CVE databases  

**Evidence standard:** implementation under `02_Source/src/nova_layer/object_workflow/` plus Approved docs above. Deployment-dependent behaviour is labelled as such.

---

# 2. Trust Model

### 2.1 Primary assumption — trust the installer

| Assumption | Verified basis |
|---|---|
| Plugins are **trusted local code** | Known Limitations §4 / §8; Plugin SDK Reference (install only packages you trust) |
| There is **no plugin sandbox** | Plugins load via in-process `importlib` in `PluginManager` (`plugin_sdk/manager.py`); same interpreter as Core |
| Core does **not** download plugins | `resolve_plugin_roots()` / package manager are filesystem-local; ARCHITECTURE §9; Known Limitations §4 |
| Operator chooses what to install | Local `.nova-plugin` / directories only; OW Plugins UI is status-only (no Install button) |

**Implication:** A malicious or buggy plugin can exercise the full privileges of the NOVA Layer process (filesystem, memory, loaded native libs). Isolation is **load-failure isolation** (startup continues if a plugin fails), not security sandboxing (ARCHITECTURE §9; ADR-005).

### 2.2 Automation caller trust

| Assumption | Verified basis |
|---|---|
| Automation runs **in-process** with Core | ARCHITECTURE §10; Known Limitations §5 |
| Session permissions are **caller-supplied** | `AutomationService.create_session(permissions=…)` defaults to all of `read` / `write` / `execute` when omitted (`automation/service.py`) |
| No external auth / token gate in Core | No identity verification layer in AutomationService; permission membership only at `submit()` |
| Commands still obey Application rules | Same confirmation path as UI; no Domain bypass (ARCHITECTURE §10) |

**Implication:** Restricting Automation is a **deployment / caller** concern (pass a reduced permission set). Core does not authenticate remote callers because there is no remote Automation transport in Core.

### 2.3 Host and model trust (deployment-dependent)

| Assumption | Label |
|---|---|
| Host adapters (Send to Host) only when present and configured | **Deployment Dependent** — Compatibility; Known Limitations §2 |
| Inference / GPU / commercial hosts | **Not Verified** as sealed/CI security claim — Compatibility / Known Limitations |
| Baseline deliverable without hosts | **Export PNG** via filesystem adapter |

---

# 3. Execution Boundaries

### 3.1 Process boundary

| Boundary | Behaviour |
|---|---|
| Core + plugins + Automation | Single process; plugins execute as imported Python modules |
| Automation transport | **No** HTTP / REST / WebSocket / RPC in Object Workflow Core (ARCHITECTURE §10) |
| Plugin marketplace / download | **Unsupported** in Core |

### 3.2 Registration and command boundaries

| Boundary | Verified behaviour |
|---|---|
| Capability registration | `PluginRegistrationContext` enforces `plugin_type` for inference / matting / host_adapter |
| Plugin automation commands | Namespaced `{plugin_id}.{name}`; cannot override builtins (`automation/registry.py`) |
| Load failures | Caught and recorded; must not abort application startup |
| Duplicate `plugin_id` | Rejected at registration |

### 3.3 Package install / extract boundaries

Verified in `plugin_sdk/package/` (archive + validation + manager):

| Check | Effect |
|---|---|
| Validate / inspect before extract | Install path runs validation before writing package contents |
| ZIP member path traversal | Rejects absolute / `..` paths (`PLUGIN_PACKAGE_UNSAFE_PATH`) |
| ZIP symlinks | Forbidden (`PLUGIN_PACKAGE_SYMLINK_FORBIDDEN`) |
| Extract resolve escape | Member resolve must stay under destination root |
| Entry module path / symlink | Unsafe entry names and symlink entries rejected |
| Optional SHA-256 | Verified when `checksum_sha256` is set on a `.nova-plugin` archive; **not** a substitute for trust — unpacked directory installs may skip checksum with warning only |

### 3.4 Export path boundary

Verified in `FilesystemExportAdapter.validate()` (`adapters/host_filesystem_export.py`):

| Check | Effect |
|---|---|
| Action | Filesystem adapter supports `export_copy` only |
| Extension | Destination must end with `.png` |
| Traversal | `".."` in path parts → `PATH_TRAVERSAL` |
| Resolve escape | Resolved file’s parent must equal resolved destination parent |
| Overwrite | Blocked unless `allow_overwrite` |
| Write pattern | Validate → write → atomic replace (implementation) |

Automation export paths that use this adapter inherit the same validation (Application path; no separate remote exporter in Core).

### 3.5 Persistence / lifecycle boundaries

| Boundary | Behaviour |
|---|---|
| Project packages | Schema **2.0** only; separate from Workspace |
| Workspace (`workspace.json`) | Atomic save (temp + fsync when available + replace; backup best-effort); corrupt load resets workspace defaults without deleting Projects (ARCHITECTURE §§8, 12) |
| Runtime / temp | Session-scoped; must not be persisted into Project or Workspace; cleared on coordinated shutdown |
| Plugin `shutdown()` | **Not** a reliable public callback (Known Limitations §4; Plugin SDK Reference) — cleanup belongs on provider/adapter hooks Core already invokes |

---

# 4. Data Handling

| Data class | Where it lives | Security-relevant rule |
|---|---|---|
| Object Workflow Project | `.nova` package / `JsonProjectStore` | Schema gate; atomic package replace; unknown keys forbidden (`extra="forbid"`) per Known Limitations §3 |
| Workspace preferences / recent / plugin install metadata | `WorkspaceManager` → `workspace.json` | Local app-lifetime state; not a multi-user sync store (ARCHITECTURE non-claims) |
| Extraction / operation temps | Service temp workspace | Ephemeral; removed on shutdown |
| Installed plugins | Local install root + workspace records | Local-only trust model (ARCHITECTURE §12) |
| Automation events | In-process bus | No persistence, replay, remote fan-out, or retry (Known Limitations §5) |
| Sealed release artifacts | `08_Release/` | Content-addressed wheels/reports; prose docs not stored there |

**Not claimed:** encryption-at-rest, secret vaults, multi-tenant isolation, or cloud sync.

---

# 5. Known Security Limitations

Only limitations verified in Approved docs / implementation:

| Limitation | Kind | Expectation |
|---|---|---|
| No plugin sandbox | Intentional | Install only trusted packages |
| No remote plugin marketplace / download in Core | Unsupported | Local install only |
| Trusted-local execution (full process privilege) | Intentional | Treat plugins like local scripts |
| Automation in-process only; no Core remote API | Unsupported (transport) | No network Automation surface in OW Core |
| Automation permissions without external auth | Intentional (current model) | Caller must pass reduced permissions if needed; default is full set |
| Optional package checksum only | Intentional constraint | Presence of checksum ≠ sandbox |
| Plugin-level `shutdown()` unreliable | Intentional (wiring) | Do not rely on it for secure teardown |
| Host send / GPU / commercial hosts | Not Verified / Deployment Dependent | Prefer Export PNG; verify hosts in deployment |
| Full interactive UI suite / `real_model` / `real_host` | Not Verified in CI/seal | Not a security certification gate |
| No in-repo automated publish CD | Unsupported | Manual Release Process only |

---

# 6. Conclusion

### Verified RC security posture

NOVA Layer v1.0 RC Object Workflow Core is a **local, trusted-code** desktop/application model:

1. **Trust the installer** for plugins (no sandbox).  
2. **In-process** Automation with session permission checks and **no** Core remote transport.  
3. **Hardened local package extract and PNG export path checks** as implemented.  
4. **Persistence separation** between Project, Workspace, and ephemeral runtime.  

### Explicit non-claims

- Not a compliance or certification statement.  
- Not GA security approval.  
- Not a claim that Deployment Dependent hosts/plugins are safe by default.  
- Not coverage of Phase 1 HTTP bridges as OW Automation security.

### GA security gaps (documentation / process)

These remain open relative to a stronger GA security claim — they are **gaps in claim strength**, not invented missing products:

1. Formal external review / pen-test evidence (none attached to this report).  
2. Operator runbook for least-privilege Automation sessions beyond API defaults.  
3. Deployment verification for host adapters and GPU environments (still Not Verified / Deployment Dependent).  
4. Live-tree / GA packaging still subject to Release Checklist Artifact and Verification PENDING items.  
5. Optional: stronger package integrity policy (checksum mandatory) — **not** implemented as mandatory today; do not claim it.

---

# 7. Related Documents

| Document | Role |
|---|---|
| `00_Project/01_Implementation/ARCHITECTURE.md` §§9–12 | Plugin, Automation, persistence authority |
| `05_Documents/API/01_PLUGIN_SDK_REFERENCE.md` | Plugin trust and lifecycle non-guarantees |
| `05_Documents/API/02_AUTOMATION_COMMAND_REFERENCE.md` | Command permissions (when consulting catalogs) |
| `v1.0/02_KNOWN_LIMITATIONS.md` | Accepted security-relevant limits |
| `v1.0/03_COMPATIBILITY.md` | Deployment Dependent / Not Verified labels |
| `v1.0/00_RELEASE_CHECKLIST.md` | Gate status |
| `v1.0/04_TEST_REPORT.md` | Verification evidence (not a security audit) |
| `01_RELEASE_PROCESS.md` | Seal / audit workflow |

---

## Document control

| Field | Value |
|---|---|
| Milestone | v1.0 RC |
| Implementation basis | Object Workflow under `02_Source/src/nova_layer/object_workflow/` |
| Compliance / certification | **None claimed** |
| GA security approval | **Not claimed** |
