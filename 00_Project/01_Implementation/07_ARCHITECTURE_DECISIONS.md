# Architecture Decision Records

Status: Living document for NOVA Layer v1.0 RC.

These ADRs record decisions already reflected in the codebase. They do not
authorize Domain or Schema 2.0 changes.

**Architecture narrative (what the system is):**  
[`ARCHITECTURE.md`](./ARCHITECTURE.md) — the single authoritative architecture document.

**This file (why decisions were made):** decision records only. Do not duplicate
full layer rules here; update `ARCHITECTURE.md` when an ADR changes architecture.

---

## ADR-001 — Object Workflow Bounded Context

**Decision:** Implement Schema 2.0 Object Workflow under
`nova_layer.object_workflow` rather than extending Phase 1 Smart Layer Domain.

**Rationale:** Phase 1 (`schema_version: "1.0"`) and Phase 2 (`"2.0"`) have
different aggregates and confirmation semantics. Isolating packages prevents
silent cross-contamination.

**Consequences:** Dual `Project` types exist by design. Persistence loaders
reject mismatched schema versions.

---

## ADR-002 — Ports Over Direct Engine Coupling

**Decision:** CoreInference, PrecisionExtraction, ProjectStore, and
OperationExecutor are Protocol ports. Providers register through registries.

**Rationale:** Engines must not receive the Project aggregate; Application
orchestrates Domain mutations after engine results return.

**Consequences:** New providers are additive. Default executor is the in-process
threaded executor (`MockOperationExecutor` historically named for determinism).

---

## ADR-003 — Explicit Artist Confirmation

**Decision:** No ConfirmedObject without an explicit ConfirmationRecord
(`confirmed_by="artist"`). Automation and Batch must call the same confirmation
path.

**Rationale:** Product philosophy forbids AI auto-confirmation as default.

**Consequences:** Batch interactive mode is default; automatic confirmation is
opt-in only.

---

## ADR-004 — Workspace Independent of Projects

**Decision:** `WorkspaceManager` persists application environment state only
(`workspace.json`). Projects remain separate packages.

**Rationale:** Session restore must not rewrite Project schema documents.

**Consequences:** Corrupt workspace resets to empty app prefs; Projects survive.
Workspace saves are atomic (temp + replace).

---

## ADR-005 — Plugin SDK Additive Registration

**Decision:** Plugins register through `PluginRegistrationContext` into Core
registries. Plugin failures never abort application startup.

**Rationale:** Core must not depend on individual plugins.

**Consequences:** Optional dependencies disable a plugin rather than crashing.
Local `.nova-plugin` packages install into a discoverable install root.

---

## ADR-006 — Automation Is Transport-Independent

**Decision:** AutomationService maps commands to existing service/batch actions
in-process. No HTTP/REST/WebSocket/RPC in v1.0.

**Rationale:** Same operations as UI; Domain rules never bypassed.

**Consequences:** Permissions are session-local. Remote auth is out of scope.

---

## ADR-007 — Coordinated Shutdown (RC Sprint 1)

**Decision:** Controllers expose `shutdown()` that tears down operations,
plugins, caches, executor threads, temp workspaces, and GPU sessions.

**Rationale:** Release readiness required no resource leaks across long sessions.

**Consequences:** UI close paths must call controller shutdown.
