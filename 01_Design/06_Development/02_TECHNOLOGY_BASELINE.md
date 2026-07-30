# NOVA Layer

# 02_TECHNOLOGY_BASELINE

Version : 1.0 Draft

Status : Approved for Phase 1

Author : Supernova Studios

---

# Decision

Phase 1 will be implemented as a local macOS ARM64 desktop prototype using Python and PySide6.

The application core, persistence model, and AI capabilities will remain separated so the prototype can later support Windows, Linux, and NVIDIA CUDA processing without replacing Object Identity or Smart Layer data.

---

# Validated Development Environment

- Development platform: macOS 14.8.2
- Architecture: Apple Silicon ARM64
- Processor: Apple M1 Pro
- Unified memory: 16 GB
- GPU API: Metal

The system Python 3.9 installation is not suitable for the selected Qt baseline and must not be used for the project environment.

---

# Selected Stack

## Language and Runtime

- Python 3.12
- Isolated virtual environment
- `pyproject.toml` as the package and tool configuration source

Python is selected because the prototype depends on fast integration with computer vision and machine-learning libraries. Python 3.12 provides a stable baseline while remaining compatible with current Qt for Python releases.

## Desktop Interface

- PySide6
- Qt Widgets for Phase 1
- Qt signals and a background task boundary for long-running work

Qt Widgets is selected for a dense professional desktop interface, native file dialogs, mature layout behavior, custom viewer controls, and future cross-platform deployment.

QML is deferred. It may be evaluated later if animation-heavy or highly custom interaction requirements outweigh the complexity of maintaining two UI layers.

## Media Decode and Frame Access

- PyAV as the in-process FFmpeg binding
- NumPy arrays as the common frame interchange format
- FFmpeg command-line tools as diagnostic and conversion utilities, not as the primary application API

The media layer shall expose frame index, presentation timestamp, time base, frame rate, resolution, pixel format, and rotation metadata explicitly.

Frame-number access must not assume that arbitrary compressed video can be seeked accurately without decoder state. Phase 1 may build a lightweight frame index or decode a bounded Shot Range into a managed cache.

## Image and Mask Representation

- NumPy for CPU image and mask data
- `uint8` for display previews
- `float32` for confidence and processing masks
- Binary masks represented explicitly rather than inferred from display images
- PNG for lossless prototype mask persistence

OpenCV may be used for bounded image operations, but it shall not own media decoding, project state, Object Identity, or color management.

## Color Management

- OpenColorIO v2 integration boundary
- Explicit source color-space metadata
- Explicit display transform
- No destructive display transform applied to source processing data

Phase 1 may initially support a small display configuration, but the domain and manifest models must preserve color-management fields from the beginning.

## AI Runtime

- PyTorch
- MPS device on supported Apple Silicon operations
- CPU fallback for unsupported prototype operations
- Future CUDA execution behind the same capability interfaces

Device selection belongs to the capability adapter. UI and domain code shall never branch directly on `mps`, `cpu`, or `cuda`.

## AI Capability Strategy

The first vertical slice will use deterministic mock capabilities. This proves the UI, state transitions, cancellation, persistence, and tests without requiring model weights.

Model evaluation follows the vertical slice:

- Interactive Segmentation candidate: SAM 2.1 small or another point-and-box promptable adapter
- Temporal Propagation candidate: SAM 2.1 video predictor
- Research candidate: SAM 3.1, evaluated separately for memory, device support, licensing, and integration cost

No model name or checkpoint path shall appear in Object Identity or Smart Layer domain logic. Model details are stored only as Capability Provenance.

## Persistence

- Versioned JSON manifest
- Pydantic models for validation and migration boundaries
- UUID identifiers
- Relative asset paths inside the `.nova` project package
- SHA-256 media fingerprint using bounded file metadata/content sampling strategy
- Atomic save using a sibling temporary package followed by replacement

SQLite is deferred. It becomes appropriate when full-sequence frame history, search, concurrent background writes, or large project indexing makes a JSON manifest impractical.

## Testing and Quality

- pytest
- pytest-qt for UI state and signal tests
- Ruff for linting and formatting
- mypy for typed domain and service boundaries
- Built-in temporary-directory fixtures for persistence tests

UI tests shall use mock capabilities by default. Model integration tests shall be separately marked because they require weights, more memory, and longer execution time.

## Logging

- Python standard `logging`
- Human-readable development log
- Structured capability run records stored with the project
- No image pixels, media contents, or personal paths in diagnostic logs by default

---

# Architecture Boundaries

```text
UI (PySide6)
    ↓ commands and view state
Application Services
    ↓ domain operations
Domain Model
    ↓ ports
Media Adapter | Capability Adapters | Project Store
```

Dependency direction always points inward. Domain objects do not import PySide6, PyAV, PyTorch, or a model package.

---

# Background Processing

Phase 1 will use a bounded local job service.

- UI events create application commands.
- Commands submit cancellable jobs.
- Workers report immutable progress events.
- Results are validated before entering the domain model.
- Partial automatic results remain provisional.
- Only completed and accepted results update authoritative Smart Layer state.

Thread ownership must respect Qt object affinity. AI and decode work may not mutate widgets directly.

Separate processes may replace threads later if model runtimes block the interpreter, leak memory, or require isolated GPU lifecycle management.

---

# Initial Repository Layout

```text
02_Source/
├── pyproject.toml
├── src/nova_layer/
│   ├── app/
│   ├── domain/
│   ├── services/
│   ├── ports/
│   ├── adapters/
│   │   ├── media/
│   │   ├── capabilities/
│   │   └── persistence/
│   └── ui/
└── tests/
    ├── unit/
    ├── integration/
    └── ui/
```

Generated caches, virtual environments, model weights, local media, and project packages shall not be committed.

---

# Dependency Policy

- Pin direct dependencies to compatible version ranges during prototyping.
- Generate a reproducible lock file before model integration.
- Keep AI/model dependencies in optional groups.
- Record model license and checkpoint source before downloading weights.
- Do not import optional AI packages during application startup.
- Verify macOS ARM64 wheels before adding a compiled dependency.

---

# Rejected Baselines

## Electron or Tauri as the Primary UI

Rejected for Phase 1 because they add a frontend/backend boundary before the Python AI and media pipeline is validated. A web-based UI may be reconsidered after the domain and capability APIs stabilize.

## OpenCV as the Complete Media Layer

Rejected because the project requires explicit timestamps, stream metadata, pixel formats, and controlled FFmpeg behavior.

## Direct SAM Integration in UI Code

Rejected because it would couple artist workflow and Smart Layer persistence to one model generation.

## SQLite as the Initial Authoritative Store

Deferred because the three-frame Phase 1 validation state is small and benefits from a readable, inspectable manifest.

---

# Risks and Mitigations

## Apple Silicon Memory

Sixteen GB of unified memory may be insufficient for larger video models or high-resolution frames.

Mitigation:

- Begin with mock adapters.
- Evaluate small checkpoints first.
- Decode bounded ranges.
- Limit resident frame caches.
- Preserve a future remote/CUDA capability adapter boundary.

## MPS Operation Coverage

Some PyTorch or model operations may not execute correctly or efficiently on MPS.

Mitigation:

- Run adapter-level compatibility tests.
- Support explicit CPU fallback only where correctness is verified.
- Report the active device in Capability Provenance.

## Variable-Frame-Rate Media

Frame number alone may not identify presentation time reliably.

Mitigation:

- Store frame number and presentation timestamp.
- Preserve stream time base.
- Build the Shot Range index during import.

## Color Errors

Display transforms may accidentally contaminate AI input or exported data.

Mitigation:

- Separate source, working, and display color spaces.
- Apply display transforms only in the viewer path.
- Record transforms in project metadata.

---

# Technology Gate Exit Criteria

The Technology Baseline is accepted when:

- The target development machine is documented.
- Runtime and UI stack are selected.
- Media, color, AI device, persistence, testing, and logging policies are defined.
- AI dependencies remain behind replaceable capability contracts.
- The vertical-slice repository layout is defined.
- Known Apple Silicon risks and CUDA expansion path are documented.

All criteria are satisfied by this document. The project may proceed to Gate 2: Vertical Slice.

---

# Official References

- Qt for Python: https://doc.qt.io/qtforpython-6/
- PyTorch MPS backend: https://docs.pytorch.org/docs/stable/notes/mps.html
- PyAV: https://pyav.basswood.io/docs/stable/
- OpenColorIO: https://opencolorio.readthedocs.io/en/latest/
- SAM 2: https://github.com/facebookresearch/sam2
- SAM 3: https://github.com/facebookresearch/sam3
