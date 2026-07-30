# Product Feature 13 — Automation API

## Status

Approved for implementation.

---

# Goal

Introduce an Automation API that allows external scripts and internal plugins to control the existing NOVA Layer workflow.

Automation is an orchestration layer.

It never bypasses Domain rules.

---

# Architectural Authority

Must preserve:

- ARCHITECTURE.md
- Domain
- Schema 2.0
- Workspace
- Plugin SDK
- Batch Workflow
- OperationExecutor

Automation must reuse existing services.

Never create a second workflow implementation.

---

# Philosophy

Automation performs exactly the same operations as the UI.

Every API call must be equivalent to an existing user action.

Automation cannot access internal Domain state directly.

---

# AutomationService

Introduce:

AutomationService

Responsibilities:

- Execute commands
- Queue operations
- Return progress
- Report failures
- Reuse OperationExecutor

Automation never owns business logic.

---

# Automation Session

AutomationSession represents one client.

Properties:

- Session ID
- Active operations
- Workspace reference
- User context
- Permissions

---

# Command Model

Supported commands:

Open Project

Load Image

Create ArtistIntent

Generate Candidates

Select Candidate

Confirm Candidate

Generate Extraction

Export Layer

Save Project

Close Project

Batch Execute

---

# Execution

Every command:

Validate

↓

Dispatch

↓

OperationExecutor

↓

Result

---

# Progress

Expose:

Queued

Running

Completed

Failed

Cancelled

Progress events must be observable.

---

# Event System

Publish events:

OperationStarted

OperationProgress

OperationCompleted

OperationFailed

WorkspaceChanged

ProjectChanged

BatchChanged

PluginChanged

---

# Plugin Integration

Plugins may:

Register commands

Subscribe to events

Provide automation helpers

Automation never bypasses Plugin validation.

---

# Workspace Integration

Automation uses the current Workspace.

No hidden projects.

No hidden sessions.

---

# Security

Permissions:

Read

Write

Execute

Plugin commands inherit plugin permissions.

---

# Error Model

Standard errors:

InvalidCommand

InvalidState

PermissionDenied

OperationFailed

Timeout

Cancelled

---

# Threading

Automation is asynchronous.

No command may block the UI thread.

---

# Out of Scope

HTTP server

REST API

WebSocket server

Remote execution

Cloud execution

Authentication

These are future transport layers.

Automation API is transport-independent.

---

# Testing

Add tests:

Command dispatch

Event ordering

Batch execution

Workspace integration

Permission checks

Cancellation

Regression

---

# Acceptance Criteria

Complete when:

- AutomationService implemented
- AutomationSession implemented
- Command dispatcher implemented
- Event bus integrated
- Plugin integration completed
- Workspace integration completed
- Regression suite passes

---

# Completion Report

Return:

1. Public API Compatibility
2. Files Created
3. Files Modified
4. Automation Architecture
5. Command Dispatcher
6. Event System
7. Workspace Integration
8. Plugin Integration
9. Runtime Behaviour
10. Tests Added
11. Regression Results
12. Remaining Limitations
13. Final Readiness Verdict

