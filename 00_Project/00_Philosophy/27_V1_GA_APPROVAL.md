# General Availability Approval

## Status

Approved.

This document defines the General Availability (GA) approval process for
NOVA Layer.

Its purpose is to provide the formal release decision after successful
engineering validation, Closed Beta, and Product Acceptance.

This document is the final stage of the Release Track.

---

# Goal

Determine whether the current Release Candidate is ready to become the official
General Availability (GA) release.

GA approval is a release decision.

It does not redefine architecture, implementation, or product requirements.

---

# Release Lifecycle

Development

↓

Engineering Acceptance

↓

Release Candidate

↓

Closed Beta

↓

Product Acceptance

↓

GA Review

↓

GA Approval

↓

Public Release

---

# Approval Authority

GA approval shall be performed jointly by:

- Development
- QA
- Product Owner

No single role may approve GA unilaterally.

---

# Required Evidence

GA approval requires the following evidence:

- Release Integrity Report
- Engineering Acceptance Report
- Product Acceptance Report
- Release CI Report
- Closed Beta Report
- Risk Assessment
- Release Notes

All evidence shall refer to the same release version and release identity.

---

# Release Review

The GA review shall evaluate:

- Architecture stability
- Feature completeness
- Product usability
- Stability
- Performance
- Security
- Documentation
- Outstanding risks

---

# Release Decision

Possible decisions are:

- APPROVED
- APPROVED WITH KNOWN LIMITATIONS
- REJECTED

The decision shall include supporting rationale.

---

# Known Limitations

Known limitations may remain only if:

- They are documented.
- They do not compromise core workflows.
- Product Owner accepts the remaining risk.

Known limitations shall not be hidden.

---

# Release Risks

Outstanding risks shall be classified as:

- Critical
- High
- Medium
- Low

Critical risks block GA.

High risks require explicit acceptance.

---

# Approval Record

Every GA release shall record:

- Release version
- Git commit
- Git tag
- Approval date
- Development approval
- QA approval
- Product Owner approval
- Final decision

This record becomes the official release record.

---

# Publication

After approval the following may be published:

- Release package
- Release Notes
- Documentation
- Checksums

Publication shall not occur before GA approval.

---

# Post Release

Following GA:

- Archive release evidence.
- Archive approval records.
- Create the next development milestone.
- Begin post-release maintenance.

---

# Expected GA Review Report

The GA review shall report:

1. Release Identity
2. Engineering Evidence
3. Product Evidence
4. Closed Beta Summary
5. Outstanding Risks
6. Known Limitations
7. Approval Record
8. Final GA Decision

Possible decisions:

- APPROVED
- APPROVED WITH KNOWN LIMITATIONS
- REJECTED

