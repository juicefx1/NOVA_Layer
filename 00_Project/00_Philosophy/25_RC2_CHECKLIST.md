# Release Candidate 2 Checklist

## Status

Approved.

This document defines the Release Candidate 2 (RC2) gate for NOVA Layer.

Its purpose is to determine whether the current build is ready to enter
Closed Beta.

RC2 is an engineering milestone.
It is not the General Availability (GA) release.

---

# Goal

Ensure that the release is:

- technically stable
- internally consistent
- suitable for external evaluation

RC2 represents Engineering Readiness.

---

# Scope

This checklist applies to:

- Release Candidate 2
- Closed Beta preparation

It does not approve General Availability.

---

# Release Gate

RC2 approval requires successful completion of:

- Release Integrity
- Release Acceptance (Engineering)
- Release CI
- Release UX (Engineering)

Failure of any mandatory gate blocks RC2.

---

# Mandatory Requirements

## Integrity

- Release version defined
- Release identity established
- Artifacts identified
- Release notes prepared

Status:

☐ PASS

---

## Engineering Acceptance

- Feature 08 accepted
- Feature 09 accepted
- Feature 10 accepted
- Feature 11 accepted
- Feature 12 accepted

Feature 13:

☐ Released

or

☐ Deferred

---

## Continuous Integration

- Required CI pipeline completed
- Required tests passed
- Regression passed
- Package validated
- Version validated

Status:

☐ PASS

---

## Engineering UX

Verify:

- Object Workflow discoverable
- Workspace usable
- Progress visible
- Error recovery functional
- No critical UI blockers

Status:

☐ PASS

---

# Known Limitations

Document every intentional limitation.

Examples:

- Plugin GUI deferred
- Advanced Automation deferred
- Marketplace deferred

Limitations shall not be hidden.

---

# Release Risks

Every remaining issue shall be classified as:

Critical

High

Medium

Low

Critical issues block RC2.

---

# Outstanding Issues

List unresolved issues.

Each issue shall include:

- Description
- Severity
- Owner
- Planned Resolution

---

# RC2 Decision

Possible outcomes:

☐ Approved

☐ Approved with Warnings

☐ Rejected

---

# Required Deliverables

Before RC2 approval:

- Release Notes
- Engineering Acceptance Report
- CI Report
- Known Limitations
- Risk Assessment

---

# Exit Criteria

RC2 is complete when:

- Engineering gates pass
- No Critical issues remain
- Release documentation is complete
- Closed Beta may begin

---

# Expected RC2 Audit Report

An RC2 audit shall report:

1. Integrity Status
2. Engineering Acceptance
3. CI Status
4. Engineering UX
5. Known Limitations
6. Open Risks
7. Outstanding Issues
8. RC2 Decision

Possible decisions:

- APPROVED
- APPROVED WITH WARNINGS
- REJECTED

