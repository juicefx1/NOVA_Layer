# NOVA Layer Implementation Specifications

Version: 0.1  
Status: Active  
Document Type: Implementation Entry Point

---

## 1. Purpose

This directory contains the executable implementation specifications for NOVA Layer.

The documents in this directory define:

- What must be implemented
- What must not be implemented
- How major systems interact
- How object state changes
- How project data is represented
- How implementation completion is evaluated

These specifications are the primary implementation contract for developers and AI coding agents.

---

## 2. Document Authority

NOVA Layer documentation is divided into two categories.

### Product Philosophy

Location:

`00_Project/00_Philosophy/`

These documents define:

- Product intent
- Design principles
- Artist workflow
- Conceptual architecture
- Long-term product direction

Philosophy documents explain why NOVA Layer exists and how it should behave as a product.

### Implementation Specifications

Location:

`00_Project/01_Implementation/`

These documents define:

- Executable behaviour
- System boundaries
- Domain models
- Interfaces
- State transitions
- Acceptance criteria
- Testing requirements

When implementation details are required, the specifications in this directory take precedence.

Implementation specifications must remain consistent with the product philosophy.

---

## 3. Core Product Rule

All NOVA Layer implementation must preserve the following principle:

> AI proposes.  
> The artist decides.  
> AI executes.

An AI-generated result must never become artist-confirmed state without an explicit artist action.

---

## 4. Implementation Priorities

Development must follow this priority order:

1. Correct system boundaries
2. Explicit object state
3. Artist-controlled confirmation
4. Reliable project persistence
5. Replaceable inference interfaces
6. Testable domain behaviour
7. Visual quality
8. Performance optimisation

Visual quality must not be used to hide an incomplete or unstable object lifecycle.

---

## 5. Specification Reading Order

Implementation work must use the following reading order.

### 00_MVP_IMPLEMENTATION_BRIEF.md

Defines the first implementable NOVA Layer product slice.

Read this document first to understand:

- MVP goals
- Scope
- Out-of-scope features
- System boundaries
- Completion criteria

### 01_OBJECT_LIFECYCLE_SPEC.md

Defines:

- Object states
- Valid state transitions
- Artist confirmation behaviour
- Failure and recovery behaviour (operation status; not a `Failed` workflow state)

This document is the authority for workflow state.

Authoritative first-slice states: `NoSource`, `SourceReady`, `IntentProvided`, `HypothesisReady`, `ObjectConfirmed`. Do not use `Empty`, `Failed`, or `Cancelled` as workflow states.

### 02_DOMAIN_MODEL_SPEC.md

Defines:

- Core domain entities
- Required fields
- Identity rules
- Persistence relationships
- Validation constraints

This document is the authority for domain data.

### 03_ENGINE_INTERFACE_SPEC.md

Defines:

- Artist Intent System interfaces
- Core Inference Engine interfaces
- Precision Extraction Engine interfaces
- Request and response contracts
- Cancellation and failure contracts

This document is the authority for communication between systems.

### 03A_USE_CASE_SPEC.md

Defines use-case preconditions, steps, postconditions, and failure behaviour, including `CreateArtistIntent` and `UpdateArtistIntent`.

### ARCHITECTURE.md

**Sole authoritative architecture document** for NOVA Layer Object Workflow
(layers, ownership, workspace, plugins, automation, batch, persistence).

### COLOR_PIPELINE.md

Authoritative pixel-contract and cache document for Viewer / Processing /
Propagation / Render color policies (PREVIEW / SOURCE / SCENE), raw/preview/source
caches, and Smart Layer export color metadata. System-layer architecture stays in
`ARCHITECTURE.md`; this file locks the Phase 8 color pipeline for regression.

### 04_PROJECT_STRUCTURE.md

**Superseded** as an architecture specification. Retained as a historical
pointer to `ARCHITECTURE.md`. Physical repository layout lives in
`05_Documents/Developer/01_PROJECT_STRUCTURE.md`.

### 05_VERTICAL_SLICE_SPEC.md

Defines the first end-to-end implementation.

The vertical slice must demonstrate:

- Image input (PNG / JPEG)
- Artist intent (`CreateArtistIntent`)
- Object hypothesis (Mock Core Inference)
- Artist confirmation (`ConfirmationRecord` + `ConfirmedObject`)
- Project persistence (`schema_version "2.0"`) and ConfirmedObject restoration

Extraction, `UpdateArtistIntent` implementation, and `RejectHypothesis` are outside the first-slice gate.

### 06_ACCEPTANCE_TESTS.md

Defines:

- Behavioural tests
- Integration tests
- Persistence tests
- Failure tests
- MVP completion requirements

Implementation is not complete until the relevant acceptance tests pass.

---

## 6. Source Directory Responsibilities

The existing repository structure must be preserved unless an approved specification explicitly requires a change.

### `01_Design`

Contains user interface and visual design resources.

It must not contain core domain logic.

### `02_Source`

Contains application and product source code.

Phase 1 code remains under the existing `nova_layer` packages.

The approved object-workflow bounded context root is:

```text
02_Source/src/nova_layer/object_workflow/
```

with logical areas equivalent to domain, application, ports, and adapters. Do not introduce an `mvp` namespace. Do not move or rename Phase 1 code.

### `03_AI`

Contains AI-specific implementation resources.

Possible responsibilities include:

- Model adapters
- Inference providers
- Model configuration
- Model loading
- Preprocessing and postprocessing
- AI experiments

Core product domain objects must not depend directly on a specific model implementation.

### `04_Assets`

Contains application assets and approved test media.

### `05_Documents`

Contains supporting or external documentation that is not part of the authoritative product specifications.

### `06_Test`

Contains automated tests, test fixtures, and test utilities.

### `07_Build`

Contains build output or build-related resources.

Generated build artefacts must not be treated as source files.

### `08_Release`

Contains release packages and release-specific artefacts.

---

## 7. Dependency Direction

The intended dependency direction is:

```text
User Interface
      ↓
Application Services
      ↓
Domain Model
      ↑
Engine Interfaces
      ↑
Concrete AI Providers

