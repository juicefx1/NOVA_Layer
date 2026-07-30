# Product Feature 10 — Workspace & Session

## Status

Approved for implementation.

---

# Goal

Introduce a Workspace layer that restores the user's working environment across application launches without changing the Project model.

Workspace stores application state, not project data.

---

# Architectural Authority

This feature must preserve:

- ARCHITECTURE.md
- Domain
- Schema 2.0
- Plugin SDK
- Runtime Architecture
- Registry Architecture
- OperationExecutor
- ArtistIntent workflow

Workspace extends the application layer only.

---

# Design Philosophy

Current:

Application

↓

Project

↓

Workflow

Application shutdown loses UI state.

Target:

Application

↓

Workspace

↓

Project

↓

Workflow

Workspace restores the application environment without modifying Projects.

---

# Workspace Responsibilities

Workspace manages:

- Open Projects
- Active Project
- Recent Projects
- Window Layout
- Dock Layout
- Selected Tool
- Active Plugin
- Recent Export Paths
- User Preferences
- Session Metadata

Workspace is independent of Project persistence.

---

# Workspace Lifetime

Workspace is loaded:

Application Startup

Workspace is saved:

Application Shutdown

Workspace may also be saved periodically.

---

# Persistence

Workspace is stored separately from Project files.

Example:

workspace.json

Projects remain unchanged.

---

# Stored State

Workspace persists:

- Recently opened projects
- Currently opened projects
- Active project
- Selected tool
- Selected provider
- Selected plugin
- Window geometry
- Dock layout
- Sidebar visibility
- Recent export directory
- UI preferences

---

# Runtime Objects

Workspace must never persist:

- Runtime Cache
- Loaded Images
- GPU Memory
- ONNX Sessions
- Neural Runtime Sessions
- Plugin Runtime Objects
- Candidate Runtime Objects
- OperationExecutor state

These are reconstructed at runtime.

---

# Project Independence

Deleting a Workspace must never modify Projects.

Deleting a Project removes only its Workspace reference.

Workspace and Project remain independent.

---

# Plugin Integration

Workspace restores:

- Selected Plugin
- Plugin Configuration

Plugin runtime state is not restored.

Plugins initialize normally during startup.

---

# Runtime Restore Sequence

Restore order:

Workspace

↓

Plugin Manager

↓

Registries

↓

Projects

↓

Controllers

↓

UI

↓

Ready

This order must remain deterministic.

---

# Failure Recovery

If Workspace cannot be restored:

- Log the error
- Create a new Workspace
- Preserve all Projects

Workspace corruption must never corrupt Project data.

---

# Preferences

Workspace stores application preferences such as:

- Theme
- Window state
- Sidebar width
- Inspector visibility
- Default provider
- Default export location

Preferences remain separate from Project settings.

---

# UI Integration

Add:

- Recent Projects
- Reopen Last Workspace
- Restore Layout
- Reset Workspace
- Workspace Preferences

Existing Project workflow remains unchanged.

---

# Runtime Behaviour

Workspace is loaded once.

WorkspaceManager remains alive for the application lifetime.

Workspace is shared by all controllers.

---

# Testing

Add tests for:

- Workspace save
- Workspace restore
- Missing project
- Corrupt workspace
- Missing plugin
- Layout restore
- Preference restore
- Recent projects
- Plugin configuration restore
- Regression

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
- Feature 9

---

# Out of Scope

This feature does not include:

- Cloud Sync
- Team Workspace
- Multi-user Sessions
- Live Collaboration
- Workspace Version History

---

# Acceptance Criteria

The feature is complete only when:

- WorkspaceManager implemented
- Save/Restore implemented
- Preferences restored
- Layout restored
- Plugin configuration restored
- Corrupt Workspace recovery implemented
- Regression suite passing

---

# Completion Report

Return:

1. Public API Compatibility Assessment
2. Files Created
3. Files Modified
4. WorkspaceManager Architecture
5. Persistence Design
6. Restore Sequence
7. Plugin Integration
8. UI Changes
9. Runtime Behaviour
10. Tests Added
11. Regression Results
12. Remaining Limitations
13. Final Readiness Verdict

Do not implement any unrelated product feature.

