# Product Feature 9 — Plugin SDK

## Status

Approved for implementation.

---

# Goal

Introduce an official Plugin SDK that allows third-party extensions to add new capabilities to NOVA Layer without modifying Core.

The Plugin SDK must extend the existing architecture rather than replace it.

---

# Architectural Authority

This feature must preserve:

- ARCHITECTURE.md
- Domain Model
- Schema 2.0
- Registry Architecture
- Runtime Architecture
- OperationExecutor
- ArtistIntent workflow
- Existing Providers

---

# Motivation

Current architecture:

Core

↓

Inference Provider

↓

Matting Provider

↓

Host Adapter

Target architecture:

Core

↓

Plugin Manager

↓

Registry

↓

Plugin

The Core must never depend on individual plugins.

Plugins depend on the SDK.

---

# Supported Plugin Types

Initial supported plugin categories:

- Inference Plugin
- Matting Plugin
- Host Adapter Plugin

Future plugin types are out of scope.

---

# Plugin Layout

Each plugin must have the following structure:

plugin/

    manifest.json

    plugin.py

    resources/

    models/

    README.md

The manifest is mandatory.

---

# Manifest

Each plugin manifest must include:

- Plugin ID
- Display Name
- Description
- Version
- Author
- SDK Version
- Plugin Type
- Capabilities
- Entry Module

Plugin IDs must be globally unique.

---

# SDK Version

Each plugin declares:

sdk_version

Core must refuse incompatible SDK versions.

No compatibility guessing.

---

# Discovery

Plugins are discovered from:

plugins/

No automatic downloading.

No online registry.

Discovery occurs during application startup.

---

# Validation

Before loading, validate:

- manifest exists
- unique plugin id
- supported sdk version
- valid plugin type
- entry module exists
- capability declaration

Invalid plugins are skipped.

---

# Loading

Plugins are imported using importlib.

Plugin import failure must never terminate the application.

Failures are isolated.

---

# Plugin Lifecycle

Lifecycle:

Discovered

↓

Validated

↓

Loaded

↓

Registered

↓

Available

↓

Shutdown

Plugin initialization must be lazy where possible.

---

# Registration

Plugins must never modify registries directly.

PluginManager performs all registry registration.

Example:

Registry.register(...)

---

# Capability Model

Plugins declare capabilities such as:

- sam2
- onnx
- gpu
- cpu
- alpha_matting
- photoshop_host

Capabilities are used for UI and provider selection.

---

# Runtime

Plugin instances are reused for the application lifetime.

Sessions remain plugin-owned.

Core never manages model sessions.

---

# Dependency Policy

Plugins may declare optional dependencies.

Core must not install dependencies.

Unavailable dependencies simply disable that plugin.

---

# Error Isolation

Plugin failures are translated into stable application errors.

Examples:

PluginLoadError

PluginValidationError

PluginRuntimeError

PluginDependencyError

Core exceptions remain unchanged.

---

# Configuration

Plugin configuration is stored as opaque dictionaries.

Examples:

- model_path
- device
- precision
- tile_size

Core stores configuration.

Plugin interprets configuration.

---

# UI Integration

Each plugin exposes:

- Name
- Version
- Description
- Availability
- Capability List
- Failure Reason

Unavailable plugins remain visible.

---

# Security

Plugins must never:

- download files automatically
- execute arbitrary installers
- delete user files
- perform network access without user consent

---

# Testing

Add tests for:

- Discovery
- Duplicate IDs
- Invalid Manifest
- Invalid SDK Version
- Missing Entry Module
- Registration
- Runtime Errors
- Capability Parsing
- Configuration
- Fake Plugin

---

# Regression

The following must remain unchanged:

- Feature 1
- Feature 2
- Feature 3
- Feature 4
- Feature 5
- Feature 6
- Feature 7
- Feature 8

---

# Out of Scope

This feature does not include:

- Plugin Store
- Marketplace
- Auto Update
- Cloud Plugins
- Licensing
- Package Signing

---

# Acceptance Criteria

The feature is complete only when:

- PluginManager implemented
- Manifest Loader implemented
- Discovery implemented
- Validation implemented
- Registry Integration completed
- Error Isolation completed
- Fake Plugin tests passing
- Regression suite passing

---

# Completion Report

Return:

1. Files Created
2. Files Modified
3. PluginManager Architecture
4. Manifest Format
5. Discovery Implementation
6. Validation Rules
7. Registry Integration
8. Runtime Behaviour
9. UI Changes
10. Dependency Handling
11. Tests Added
12. Regression Results
13. Remaining Limitations
14. Final Readiness Verdict

Do not implement any unrelated product feature.

