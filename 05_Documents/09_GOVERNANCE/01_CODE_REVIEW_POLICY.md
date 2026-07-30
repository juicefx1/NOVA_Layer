# Code Review Policy

## Status

Approved

## Audience

Developer, Maintainer, Release Engineer

## Authority

**Official code review governance** for changes under `02_Source/` and related tests.

Does not redefine architecture or release sealing steps.

Authoritative behaviour and layering:

- `00_Project/01_Implementation/ARCHITECTURE.md`

Offline quality gate (commands):

- `05_Documents/Release/01_RELEASE_PROCESS.md` §5.A  
- `.github/workflows/ci.yml`  
- `05_Documents/Developer/00_DEVELOPER_GUIDE.md` (when citing local commands)

## Scope

Who reviews what, what must pass before merge, and how reviews relate to documentation and release authority. Does not invent CI jobs, branch protection rules, or mandatory tool configs beyond what exists in-repo.

---

# 1. Purpose

Keep Object Workflow Core consistent with architecture boundaries, public contracts, and documented non-claims before changes land on the integration branch.

---

# 2. Ownership

| Surface | Owner role | Notes |
|---|---|---|
| Object Workflow Core (`object_workflow/`) | Maintainer | Domain / Application / Runtime boundaries |
| Desktop UI (`app/`, `ui/`) | Maintainer | Must not bypass Application confirmation rules |
| Plugin SDK / Automation public surfaces | Maintainer | Breaking changes → Versioning Policy |
| Tests / offline gate | Developer + Maintainer | Default markers only unless claiming optional lanes |
| Release tooling CLIs | Release Engineer + Maintainer | Seal path integrity |

---

# 3. Review Responsibilities

| Reviewer | Responsible for |
|---|---|
| **Author** | Scoped change; no drive-by refactors; docs updated or follow-up noted; no invented APIs |
| **Peer Developer** | Correctness, tests, readability |
| **Maintainer** | Architecture direction, public contract impact, merge authority |
| **Release Engineer** | When change affects seal tools, version identity, or milestone claims — verify Release docs still honest |

Minimum expectation: at least **Maintainer** approval for architecture-sensitive or public-contract changes. Routine test/doc-only fixes may follow Maintainer judgment.

---

# 4. Required Checks Before Merge

| Check | Requirement | Evidence source |
|---|---|---|
| Offline lint | `ruff check src tests` (or CI equivalent) | Release Process §5.A; CI workflow |
| Offline tests | `pytest -m "not real_model and not real_host" --ignore=tests/ui` | Same |
| Architecture fit | No Domain bypass; plugins additive; Automation in-process | `ARCHITECTURE.md` |
| Contract honesty | Allowlist / schema / command changes called out | `00_VERSIONING_POLICY.md` |
| Docs match | Update owning docs or explicit follow-up | `00_DOCUMENT_POLICY.md` |

Optional lanes (`real_model`, `real_host`, `tests/ui/`) are **not** merge blockers unless the change claims those lanes as Supported (Compatibility / Known Limitations).

---

# 5. Approval Flow

1. Author opens change with clear scope and test evidence.  
2. Peer review (as applicable).  
3. Maintainer approves architecture/contract impact.  
4. Offline gate green (CI or local equivalent recorded).  
5. Merge.  
6. If public behaviour changed: update API/User/Developer/Release docs per Document Policy.  

Sealing a distribution candidate is **not** part of ordinary code review — see Release Approval Policy and Release Process.

---

# 6. Explicit Non-Claims

- This policy does not require a specific PR tool, CODEOWNERS file, or number of reviewers beyond Maintainer judgment where none are configured in-repo.  
- Passing review is not RC or GA approval.  

---

# 7. Related Documents

| Document | Role |
|---|---|
| `00_DOCUMENT_POLICY.md` | Documentation review |
| `02_ARCHITECTURE_DECISION_POLICY.md` | ADR / architecture change gate |
| `03_DEPRECATION_POLICY.md` | Breaking / removal reviews |
| `04_RELEASE_APPROVAL_POLICY.md` | RC / GA authority |
| `Developer/11_CONTRIBUTING.md` | Contributor-facing summary (when filled) |
