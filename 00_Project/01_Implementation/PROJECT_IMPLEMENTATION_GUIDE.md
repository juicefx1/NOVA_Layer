# NOVA Layer

# PROJECT_IMPLEMENTATION_GUIDE

Version : 1.0 Draft

Status : Internal — mirrors executable Phase 1 code

Author : Supernova Studios

---

# Purpose

This guide is the entry point for implementing and extending NOVA Layer.

Philosophy documents under `00_Project/00_Philosophy/` define *why*.

This folder defines *how the current executable system is built*, grounded in
`02_Source/src/nova_layer/`.

If a statement here conflicts with code, the code wins and this guide must be updated.

---

# Reading Order

1. `00_MVP_IMPLEMENTATION_BRIEF.md` — what Phase 1 delivers and what it excludes
2. `01_OBJECT_LIFECYCLE_SPEC.md` — maturity, lifecycle, and validation states
3. `02_DOMAIN_MODEL_SPEC.md` — Project → Smart Layer data model
4. `03_ENGINE_INTERFACE_SPEC.md` — capability ports and adapters
5. `ARCHITECTURE.md` — sole Object Workflow architecture reference (`04_PROJECT_STRUCTURE.md` is a superseded pointer)
6. `05_VERTICAL_SLICE_SPEC.md` — end-to-end artist workflow
7. `06_ACCEPTANCE_TESTS.md` — P1-AT evidence map

Related living documents:

- `01_Design/06_Development/00_DEVELOPMENT_ROADMAP.md`
- `01_Design/06_Development/01_PHASE_1_IMPLEMENTATION_SPEC.md`
- `02_Source/README.md`
- `00_Project/00_Philosophy/13_CHANGELOG.md`

---

# Architecture Snapshot

```
Production Layer (exports: PNG / OpenEXR / RGBA MOV)
        ↑
Smart Layer Layer (renders, previews, versioned assets)
        ↑
Object Identity Layer (maturity + lifecycle)
        ↑
Evidence & Reasoning Layer
        ↑
AI Capability Layer (ports → adapters → optional models)
```

Hard rule: domain modules must not import PySide6, PyAV, PyTorch, or named model packages.

Infrastructure lives under `nova_layer.adapters` and implements `nova_layer.ports`.

---

# Current Executable Surface

- Desktop app: `nova-layer` (PySide6)
- Phase 1 acceptance: `nova-acceptance`
- Production export: `nova-export-render`
- Depth/Pose bridge and QA CLIs: `nova-depth-pose-*`
- Release pipeline: `nova-release-*`

Primary orchestrator: `nova_layer.app.project_controller.ProjectController`

Persistence: atomic `.nova` packages via `JsonProjectStore`

---

# Implementation Rules

1. Understand before precision — never auto-promote identity without artist confirmation paths.
2. Every model output is Evidence, not truth.
3. Authoritative Smart Layer state updates only through commit-on-completion jobs or explicit artist actions.
4. External adapters must pass contract validators before project commit.
5. Export requires render integrity verification (SHA-256).
6. Do not embed model weights in the repository or release Wheel.

---

# Next Implementation Frontiers

Already delivered in Phase 1 source:

- Vertical slice through render and multi-format export
- Skeleton tracking, correction, fusion, Depth/Pose bridge
- Benchmark and release tooling

Not yet started as full DCC plug-ins:

- Nuke / After Effects / Resolve UI panels and ofx/cep packaging

Started foundation:

- `nova_layer.host.HeadlessHostSession` and `nova-host-session` CLI (`host_api_version` 1.0)

External blockers (not solvable by code alone):

- Licensed real-footage QA datasets
- Browser model commercial redistribution license gate

---

# How to Extend Safely

| Goal | Start here |
|---|---|
| New domain field | `domain/models.py` + migration registry + round-trip test |
| New AI model | Implement a port in `ports/capabilities.py`, adapter under `adapters/capabilities/`, wire `capability_selection.py` |
| New export format | `export/smart_layer.py` + Workspace + `nova-export-render` |
| Host / DCC plugin | Prefer a headless session over Qt widgets; do not import UI into host adapters |
| New acceptance gate | Add case to `acceptance.py` with a dedicated evidence test |

---

# Verification Baseline

```bash
cd 02_Source
python -m pip install -e '.[desktop,dev]'
pytest
nova-acceptance --output ../06_Test/reports
```

Optional AI path:

```bash
python -m pip install -e '.[ai]'
nova-model-preflight
```
