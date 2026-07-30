# Product Feature 8 --- Neural Matting Backend

> **Note:** This specification is intended to be read together with
> `ARCHITECTURE.md`. It extends the existing architecture and must not
> redesign Domain, workflow, persistence, or Schema 2.0.

## 1. Status

Approved for implementation.

## 2. Goal

Introduce an optional Neural Matting backend behind the existing
`MattingBackend` abstraction while preserving:

-   Domain
-   Schema 2.0
-   Confirmed-object binding
-   OperationExecutor
-   Existing workflow
-   Existing Color Affinity backend

## 3. Architecture

Existing:

``` text
Confirmed Candidate
        │
PrecisionExtractionPort
        │
LocalMattingExtractionProvider
        │
ColorAffinityMattingBackend
        │
RGBA Asset
```

Target:

``` text
Confirmed Candidate
        │
PrecisionExtractionPort
        │
LocalMattingExtractionProvider
        │
MattingBackend
 ├── ColorAffinityMattingBackend
 └── NeuralMattingBackend
        │
RGBA Asset
```

## 4. Architectural Rules

-   Do not redesign Domain.
-   Do not redesign Project persistence.
-   Do not redesign Confirmation.
-   Do not redesign Candidate workflow.
-   Preserve existing registry architecture.
-   Preserve existing extraction provider interface.

## 5. Backend Selection

Supported backend identifiers:

-   `color_affinity`
-   `neural_onnx`

Backend selection must be explicit and included in the extraction
settings snapshot.

## 6. Dependency Policy

Neural support is optional.

The application must remain usable without:

-   ONNX Runtime
-   CUDA
-   GPU
-   Model checkpoints

Imports must not fail if optional dependencies are missing.

## 7. Model Resolution

Resolution order:

1.  Explicit runtime configuration
2.  Environment variable (`NOVA_MATTING_ONNX_MODEL`)
3.  Bundled model directory
4.  Application model directory

No automatic downloading.

## 8. Runtime Rules

-   Lazy session creation
-   Session reuse
-   Runtime-only cache
-   No persistence of model sessions
-   No persistence of tensor buffers

## 9. Input Contract

Inputs:

-   Confirmed RGB image
-   Deterministic trimap
-   Cancellation callback
-   Matting settings

Never use hovered or unconfirmed candidates.

## 10. Output Contract

Output:

-   Float alpha
-   Source resolution
-   Preserve known foreground
-   Preserve known background
-   Compose original RGB + neural alpha into RGBA

## 11. Cancellation

Respect existing OperationExecutor cancellation.

Never commit partial extraction results.

## 12. Metadata

Include:

-   backend id
-   provider id
-   runtime
-   execution provider
-   model fingerprint
-   inference resolution
-   timing

Do not store absolute model paths.

## 13. Error Handling

Translate runtime failures into stable application errors:

-   DependencyMissing
-   ModelMissing
-   ModelInvalid
-   BackendUnavailable
-   InferenceFailed
-   Cancelled

## 14. UI

Extend the existing Matting UI only.

Allow backend selection.

Unavailable neural backends must display the reason.

## 15. Performance

-   Reuse runtime sessions
-   Avoid repeated validation
-   Reuse preprocessing buffers where possible
-   Integrate with runtime metrics

## 16. Testing

Retain all existing tests.

Add tests for:

-   availability
-   missing dependency
-   missing model
-   invalid model
-   lazy initialization
-   session reuse
-   preprocessing
-   postprocessing
-   cancellation
-   metadata
-   backend selection
-   no silent fallback

Use a fake inference session for CI.

## 17. Regression

Verify unchanged behaviour for:

-   ArtistIntent
-   CandidateSet
-   Generation History
-   Confirmation
-   Precision Extraction
-   Classical Matting
-   Host Integration
-   Runtime Cache
-   Schema 2.0

## 18. Acceptance Criteria

The feature is complete only when:

1.  ARCHITECTURE.md is preserved.
2.  Domain unchanged.
3.  Schema remains 2.0.
4.  Existing backend preserved.
5.  Neural backend optional.
6.  Lazy initialization implemented.
7.  Session reuse implemented.
8.  No runtime downloads.
9.  Metadata identifies backend.
10. Existing regression suite passes.

## 19. Out of Scope

-   Model training
-   Automatic downloads
-   Cloud inference
-   Photoshop integration
-   Colour decontamination
-   Schema redesign
-   Workflow redesign

## 20. Implementation Sequence

1.  Read ARCHITECTURE.md.
2.  Inspect MattingBackend.
3.  Inspect PrecisionExtractionPort.
4.  Inspect registry.
5.  Report API incompatibilities.
6.  Implement NeuralMattingBackend.
7.  Add runtime session abstraction.
8.  Add ONNX backend.
9.  Add availability probing.
10. Add tests.
11. Run regression suite.

## 21. Completion Report

Return:

1.  Files created
2.  Files modified
3.  Existing architecture discovered
4.  Backend architecture
5.  Runtime session
6.  Dependency policy
7.  Model resolution
8.  Availability
9.  Controller changes
10. UI changes
11. Persistence impact
12. Schema compatibility
13. Performance observations
14. Tests
15. Remaining limitations
16. Final readiness verdict

Do not implement unrelated features.
