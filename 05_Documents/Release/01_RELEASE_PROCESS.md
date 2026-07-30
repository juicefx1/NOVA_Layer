# Release Process

## Status

Approved

## Audience

Release Engineer, Maintainer

## Authority

**Official release workflow** for NOVA Layer.

Governing versioning document:

- `05_Documents/Release/00_VERSIONING_POLICY.md`

Architecture / docs ownership:

- `00_Project/01_Implementation/ARCHITECTURE.md`
- `05_Documents/00_DOCUMENTATION_ARCHITECTURE.md`

This process describes the **current manual** release workflow and the **existing** local CLI tools. It does **not** invent CI/CD publish pipelines, PyPI upload automation, or GitHub Release automation — those are not implemented.

---

# 1. Purpose

Define how maintainers move from development builds to a **sealed release candidate** under `08_Release/`, what must be true before sealing, what documentation must accompany a product milestone, and what happens after sealing.

---

# 2. Scope

**In scope**

- Offline CI gate (automated lint/tests only)  
- Manual wheel build, verify, install-smoke, acceptance, seal, and audit  
- Placement of **artifacts** under `08_Release/`  
- Placement of **human release docs** under `05_Documents/Release/`  
- Alignment of distribution version (`pyproject.toml`) with Versioning Policy  

**Out of scope**

- Automated wheel build or publish in GitHub Actions  
- PyPI / private index upload scripts in-repo  
- Guaranteeing `real_model` / `real_host` / full desktop UI suites (optional / not CI)  
- Schema 1.0 → 2.0 migration as a release step (unsupported)  

---

# 3. Release Stages

Aligned with Versioning Policy §7 and existing tools:

| Stage | Distribution version | What happens |
|---|---|---|
| **Development** | Often `*.devN` (e.g. current `0.1.5.dev0`) | Day-to-day work; editable install; CI on push/PR |
| **Pre-seal preparation** | Stable packaging version without unintended `.dev` suffix when cutting a candidate | Manual bump in `pyproject.toml` if needed; docs milestone folder prepared |
| **Release Candidate (sealed)** | Version embedded in the built wheel | Wheel + reports sealed into `08_Release/nova-layer-<version>-<sha12>/` via `nova-release-candidate` |
| **Audit (on demand)** | Same sealed directory | `nova-release-audit` re-validates integrity |
| **GA / final (docs claim)** | Deliberately aligned packaging version when maintainers choose | Only after sealed candidate + completed milestone Release docs; **publish remains manual/out-of-band** |

**Important:** Docs milestone **v1.0 RC** and packaging version are independent until maintainers align them (Versioning Policy).

---

# 4. Entry Criteria

Do **not** start sealing a candidate until all of the following are true:

### 4.1 Required (implemented gates)

1. **Offline CI green** for the commit to release (or equivalent local commands):  
   - `ruff check src tests`  
   - `pytest -m "not real_model and not real_host" --ignore=tests/ui`  
   (See `.github/workflows/ci.yml` and Developer Guide.)  
2. **Distribution version** in `02_Source/pyproject.toml` is the intended candidate identity (read Versioning Policy before bumping).  
3. **Public contracts** reviewed for unintended breaking changes (Schema / SDK / package format / Automation) per Versioning Policy §5.  
4. **Milestone Release docs** under `05_Documents/Release/vX.Y/` started or updated enough to record Known Limitations / Support Matrix labels for unverified lanes (placeholders must not claim false verification).  

### 4.2 Optional / labelled (not entry blockers unless the milestone claims them)

- `real_model` tests  
- `real_host` tests  
- `tests/ui/` Qt suites  
- Commercial host or GPU environment verification  

If a milestone claims these, they become checklist items for that milestone’s Known Limitations / Support Matrix — not inventing new CI jobs.

---

# 5. Release Checklist

Execute from a clean tree at the release commit. Paths below are relative to the repository root unless noted.

### A. Quality gate (mirror CI)

```bash
cd 02_Source
source .venv/bin/activate   # or equivalent
python -m pip install -e ".[desktop,dev]"
python -m ruff check src tests
python -m pytest -m "not real_model and not real_host" --ignore=tests/ui --tb=short
```

### B. Build wheel (manual)

```bash
cd 02_Source
python -m pip wheel . --no-deps --wheel-dir ../07_Build/wheels
```

Expect a wheel such as `07_Build/wheels/nova_layer-<version>-py3-none-any.whl`.  
`07_Build/` is a **build output** location (may be untracked).

### C. Verify wheel artifact

```bash
nova-release-verify path/to/nova_layer-<version>-py3-none-any.whl \
  --report path/to/wheel-report.json
```

Must exit **0** (`valid`).

### D. Install smoke (includes offscreen GUI probe)

```bash
nova-install-smoke path/to/nova_layer-<version>-py3-none-any.whl \
  --report path/to/install-smoke-report.json
```

Must exit **0** with `valid` and `gui_startup_passed` true in the report.

### E. Acceptance report

```bash
nova-acceptance
# default report dir: 06_Test/reports/ → phase1_acceptance_latest.json
```

Sealing requires the acceptance JSON to show **all** cases passed (`passed == total > 0`, every result `passed`).

### F. Seal release candidate

```bash
nova-release-candidate \
  path/to/wheel.whl \
  path/to/wheel-report.json \
  path/to/install-smoke-report.json \
  path/to/phase1_acceptance_latest.json \
  --release-root path/to/08_Release
```

Creates an immutable content-addressed directory:

`08_Release/nova-layer-<version>-<sha256[:12]>/`

containing the wheel, the three reports, and `release_manifest.json`.

### G. Audit (recommended before declaring RC ready)

```bash
nova-release-audit path/to/08_Release/nova-layer-<version>-<sha12>
```

Must exit **0**.

### H. Documentation (human, not under `08_Release/`)

For milestone `vX.Y`, update or complete as applicable:

| Doc | Role |
|---|---|
| `05_Documents/Release/vX.Y/00_RELEASE_CHECKLIST.md` | Milestone checklist |
| `01_RELEASE_NOTES.md` | User-visible changes; call out breakages |
| `02_KNOWN_LIMITATIONS.md` | Accepted risks / Not Verified lanes |
| `03_SUPPORT_MATRIX.md` | Verified vs optional environments |
| `04_TEST_REPORT.md` | Cite CI + seal tools results |
| `05_SECURITY_REPORT.md` | Trust model / accepted risks |
| `06_MIGRATION_GUIDE.md` | Only real migrators (none for Schema 1.0→2.0 today) |
| `07_GO_LIVE_CHECKLIST.md` | Final go/no-go |

Follow Versioning Policy for what may be claimed.

### Checklist summary

- [ ] CI / offline gate green  
- [ ] Version identifiers reviewed (Versioning Policy)  
- [ ] Wheel built  
- [ ] `nova-release-verify` passed + report  
- [ ] `nova-install-smoke` passed + report (`gui_startup_passed`)  
- [ ] `nova-acceptance` fully passed + report  
- [ ] `nova-release-candidate` sealed under `08_Release/`  
- [ ] `nova-release-audit` passed  
- [ ] Milestone Release docs updated without inventing verification  
- [ ] No prose release docs placed inside `08_Release/`  

---

# 6. Exit Criteria

A candidate may be **declared sealed / RC-ready** only when:

1. Seal directory exists under `08_Release/` with matching `release_manifest.json`.  
2. `nova-release-audit` succeeds on that directory (or equivalent fresh seal + audit).  
3. Embedded reports still satisfy verify + install-smoke (`gui_startup_passed`) + full acceptance pass.  
4. Milestone documentation states distribution version, docs milestone label, and Known Limitations honestly.  
5. Breaking changes (if any) are listed per Versioning Policy.  

A candidate is **not** automatically:

- Published to PyPI  
- Attached to a GitHub Release  
- Proven on GPU / commercial hosts  

Those require separate, currently **manual/out-of-band** actions and explicit documentation if performed.

---

# 7. Release Artifacts

### 7.1 Build intermediates (`07_Build/` — optional local)

| Artifact | Source |
|---|---|
| Wheel (`.whl`) | `pip wheel` |
| Wheel / smoke JSON reports | CLI `--report` outputs (often stored under `07_Build/reports/`) |

### 7.2 Sealed candidate (`08_Release/` — artifacts only)

Per sealed directory (typical current layout):

| File | Role |
|---|---|
| `nova_layer-<version>-*.whl` | Distributable package |
| Wheel verification JSON | Output of `nova-release-verify` |
| Install-smoke JSON | Output of `nova-install-smoke` |
| Acceptance JSON | Output of `nova-acceptance` (e.g. `phase1_acceptance_latest.json`) |
| `release_manifest.json` | Seal manifest (format_version as written by the tool; current seal path expects smoke GUI flag) |

**Rule:** `08_Release/` holds **artifacts only** — never guides, checklists, or architecture prose (`00_DOCUMENTATION_ARCHITECTURE.md`).

### 7.3 Human documentation (`05_Documents/Release/`)

Process + policy + `vX.Y/` milestone docs.

---

# 8. Documentation Requirements

Before calling a product milestone “RC” or “GA” in docs:

1. Obey **Versioning Policy** (identifiers, breaking changes, non-guarantees).  
2. Keep API / User / Developer Approved docs consistent with the sealed behaviour.  
3. Label unverified lanes (**Not Verified**) instead of implying CI covered them.  
4. Do not claim Schema 1.0 → 2.0 migration or remote Automation.  
5. After a milestone is tagged/shipped, treat `Release/vX.Y/` as frozen except errata (`00_DOCUMENTATION_ARCHITECTURE.md`).  

---

# 9. Post-Release Activities

After a successful seal (and any out-of-band publish you choose to perform):

1. **Record** the sealed directory path, wheel SHA-256, and distribution version in Test Report / Release Notes.  
2. **Re-audit** sealed directories after copy/move with `nova-release-audit` if redistributing from archival storage.  
3. **Do not mutate** files inside a sealed content-addressed directory; cut a new candidate instead.  
4. **Open follow-ups** for Known Limitations (GPU, hosts, UI smoke) if the next milestone will claim them.  
5. **Align** packaging version with docs milestone only when intentionally cutting GA (Versioning Policy).  
6. **Monitor** CI on the release branch/tag commit; regressions require a new wheel + new seal.  

There is **no** in-repo automated post-publish webhook or rollback job.

---

# 10. Related Documents

| Document | Role |
|---|---|
| `05_Documents/Release/00_VERSIONING_POLICY.md` | Versioning authority |
| `05_Documents/Release/v1.0/*` | Current milestone release docs |
| `05_Documents/Developer/00_DEVELOPER_GUIDE.md` | Offline gate commands |
| `05_Documents/00_DOCUMENTATION_ARCHITECTURE.md` | Docs vs `08_Release/` ownership |
| `00_Project/01_Implementation/ARCHITECTURE.md` | Product architecture |
| `.github/workflows/ci.yml` | Automated offline checks only |

CLI entry points (implemented): `nova-release-verify`, `nova-install-smoke`, `nova-release-candidate`, `nova-release-audit`, `nova-acceptance`.

Canonical path for this process: **`05_Documents/Release/01_RELEASE_PROCESS.md`**.  
`RELEASE_PROCESS.md` is a pointer for older listings.

---

## Explicit Non-Claims

- CI does not build, smoke-test, accept, seal, or publish wheels.  
- Sealing is local/manual.  
- Publish/distribute beyond `08_Release/` is outside this documented automation.  
- Phase 1 acceptance report naming (`phase1_acceptance_*`) is what the current tool writes; Object Workflow product milestones still use that sealing input until a different acceptance producer is implemented and documented.  

## Documentation Gaps

- Milestone `v1.0/` Release docs remain placeholders until filled with evidence from a specific seal.  
- No documented corporate/PyPI publish runbook (none in-repo).  
- Acceptance suite naming still reflects Phase 1 report filenames while product docs speak to Object Workflow v1.0 RC — call this out in Test Report when writing it.  
