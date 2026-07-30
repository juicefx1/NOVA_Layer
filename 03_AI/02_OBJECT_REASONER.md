# NOVA Layer

# 02_OBJECT_REASONER

Version : 1.0 Draft

Status : Internal

Author : Supernova Studios

---

# Purpose

The Object Reasoner is the decision-making system of NOVA Layer.

Its purpose is to determine which object the artist intends to isolate by combining visual evidence, accumulated knowledge, and artist intent.

Unlike the Evidence Engine, the Object Reasoner interprets information rather than simply observing it.

---

# Philosophy

Observation does not produce understanding.

Understanding requires reasoning.

The Object Reasoner transforms observations into a coherent understanding of the intended subject.

---

# Inputs

The Object Reasoner receives information from multiple sources.

## Evidence

Current observations extracted from the input.

Examples include:

- Appearance
- Geometry
- Motion
- Temporal Evidence
- Segmentation Proposals

---

## Artist Intent

Information provided directly by the artist.

Examples include:

- Rough Selection
- Scribbles
- Manual Corrections
- Previous Smart Layer

Artist Intent has the highest priority.

---

## Knowledge

Trusted information accumulated during production.

Examples include:

- Confirmed Object Identity
- Previous Confirmations
- Smart Layer State
- Temporal History

Knowledge provides continuity and stability.

---

# Responsibilities

The Object Reasoner is responsible for:

- Interpreting evidence
- Resolving ambiguity
- Combining multiple information sources
- Maintaining object consistency
- Producing an Object Hypothesis

The Object Reasoner does not generate production-quality masks.

---

# Object Hypothesis

The primary output of the Object Reasoner is an Object Hypothesis.

An Object Hypothesis represents the system's current understanding of the artist's intended subject.

It is not considered final until confirmed.

---

# Artist Confirmation

The artist reviews the Object Hypothesis.

The artist may:

- Accept it
- Refine it
- Correct it

Once confirmed, the Object Hypothesis becomes a trusted Object Identity.

---

# Design Principles

Reasoning combines Evidence, Knowledge, and Artist Intent.

Evidence alone is insufficient.

Artist confirmation establishes trust.

Object understanding always precedes precision extraction.

---

# Output

The Object Reasoner produces:

- Object Hypothesis
- Confidence Information
- Object Relationships
- Object Identity (after confirmation)

These outputs are passed to the Precision Engine.

---

# Summary

The Object Reasoner is the cognitive core of NOVA Layer.

It transforms observation into understanding while keeping the artist in control of every final decision.

