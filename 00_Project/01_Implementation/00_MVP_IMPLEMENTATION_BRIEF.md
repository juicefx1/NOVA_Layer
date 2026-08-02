# NOVA Layer

# 00_MVP_IMPLEMENTATION_BRIEF

Version : 1.0 Draft

Status : Internal — mirrors executable Phase 1 code

Author : Supernova Studios

---

# Authority Note

This brief documents **Phase 1** executable capabilities (`schema_version "1.1"`, Smart Layer / Shot workflow; optional `Project.color_settings`).

The approved **object-workflow first vertical slice** (`schema_version "2.0"`, `NoSource` initial state, headless Mock Core Inference path) is specified in:

- `02_DOMAIN_MODEL_SPEC.md`
- `03_ENGINE_INTERFACE_SPEC.md`
- `05_VERTICAL_SLICE_SPEC.md`
- `06_ACCEPTANCE_TESTS.md`

Do not treat this Phase 1 brief as the schema `"2.0"` first-slice definition. Do not introduce an `mvp` package namespace.

---

# One-Sentence MVP

Prove that an artist-confirmed Object Identity remains consistent when propagated from a Master Frame toward both ends of a selected Shot Range, then produce a versioned Smart Layer render artists can export.

---

# Product Claim Under Test

Artificial Intelligence should not replace artistic judgment.

The artist decides → the system proposes → the artist confirms → the system executes.

Phase 1 validates this loop on one Shot and one Smart Layer inside a standalone desktop app.

---

# Delivered Capabilities

## Project and media

- Create / open atomic `.nova` packages
- Import video via PyAV inspection and RGB frame decode
- Shot Range and Master Frame editing with persistence
- Missing / changed media detection and explicit relink

## Understanding loop

- Positive / negative points and bounding-region guidance
- Artist-drawn skeleton guidance (semantic labels, BODY_25 preset)
- Object Hypothesis generation (Mock or SAM 2.1)
- Accept / reject / refine with Evidence and Reasoning history
- Bidirectional temporal propagation
- Low-confidence frames forced into artist review
- Local correction recomputation without discarding project state

## Temporal identity

- Per-frame Object Identity observations
- Tracked → Temporarily Lost → Recovered transitions
- Mask + skeleton confidence fusion (70% / 30%)
- Skeleton correction keyframes and multi-anchor retracking
- Artist-guided Depth/Pose fusion via optional browser bridge

## Production outputs

- Transparent RGBA extraction previews
- Versioned full-Shot Smart Layer renders with SHA-256 integrity
- Protected render versions and checksum comparison
- Export formats: PNG sequence, OpenEXR half-float RGBA, RGBA QuickTime (`qtrle`)

## Quality and release tooling

- Phase 1 acceptance suite P1-AT-001 … P1-AT-009
- Real-footage and Depth/Pose benchmark / regression CLIs
- Wheel verify, install smoke, and immutable release candidates

---

# Explicit Non-Goals (Phase 1)

- Host DCC plug-ins (Nuke, After Effects, Resolve, Premiere, …)
- Multi-project / multi-shot concurrent workspace editing
- Advanced precision modules (hair, fur, glass, smoke reconstruction)
- Cloud collaboration or remote processing
- Model training or fine-tuning inside NOVA
- Shipping model weights inside the Wheel

Enums already reserve `PRODUCTION_READY`, `PERSISTENT`, and `COMPLETED` states, but Phase 1 code does not promote into them yet.

---

# Success Criteria (Executable)

| Criterion | Evidence |
|---|---|
| Artist can confirm an object on the Master Frame | P1-AT-001 |
| Shot Range is non-zero and persisted | P1-AT-002 |
| Backward and forward propagation preserve frame mapping | P1-AT-003 / 004 |
| Ambiguity stops for artist validation | P1-AT-005 |
| Correction recomputes locally | P1-AT-006 |
| Project round-trips with identity intact | P1-AT-007 |
| Missing media requires relink | P1-AT-008 |
| Capability failure does not corrupt authoritative state | P1-AT-009 |

Run:

```bash
nova-acceptance --output ../06_Test/reports
```

---

# Primary Code Entry Points

| Concern | Path |
|---|---|
| Domain models | `02_Source/src/nova_layer/domain/models.py` |
| Orchestration | `02_Source/src/nova_layer/app/project_controller.py` |
| Capability ports | `02_Source/src/nova_layer/ports/capabilities.py` |
| Desktop UI | `02_Source/src/nova_layer/ui/workspace.py` |
| Export | `02_Source/src/nova_layer/export/smart_layer.py` |
| Acceptance | `02_Source/src/nova_layer/acceptance.py` |

---

# Immediate Follow-On Work

1. Concrete Nuke/AE bootstrap scripts that call the adapter skeletons
2. Expand host session toward in-host review / media push-pull
3. Licensed real-footage Depth/Pose and segmentation measurement
