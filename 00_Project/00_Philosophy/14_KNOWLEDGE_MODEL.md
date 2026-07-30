# NOVA Layer

# 14_KNOWLEDGE_MODEL

Version : 2.0 Draft

Status : Internal

Author : Supernova Studios

---

# Overview

The Knowledge Model defines how information is accumulated, preserved, and reused throughout the NOVA Layer workflow.

Unlike Evidence, which is directly observed from an image, Knowledge represents trusted information established during the workflow.

Knowledge improves consistency, stability, and production reliability.

---

# Philosophy

Evidence is observed.

Knowledge is established.

Understanding is built from both.

---

# Evidence vs Knowledge

Evidence comes directly from the current image.

Examples include:

- Appearance
- Motion
- Depth
- Structure

Evidence is uncertain.

It represents observations.

Knowledge represents information that has already been validated.

Examples include:

- Artist Intent
- Confirmed Object Identity
- Artist Corrections
- Smart Layer State

Knowledge is trusted.

---

# Knowledge Sources

Knowledge may originate from several sources.

## Artist

The artist provides intentional guidance.

Examples include:

- Rough Selection
- Scribble
- Confirmation
- Manual Refinement

---

## System

The system contributes validated information.

Examples include:

- Confirmed Object Identity
- Temporal Consistency
- Previous Smart Layer State

---

# Knowledge Lifecycle

Knowledge evolves throughout production.

Artist Intent

↓

Object Hypothesis

↓

Artist Confirmation

↓

Confirmed Knowledge

↓

Smart Layer

↓

Future Frames

Knowledge becomes more reliable as the workflow progresses.

---

# Persistence

Knowledge is persistent.

It survives:

- Frame changes
- Camera motion
- Temporary occlusion
- Lighting variation

Knowledge is reused whenever appropriate.

---

# Smart Layer

A Smart Layer is the primary container of production knowledge.

It stores:

- Artist Intent
- Object Identity
- Extraction Configuration
- Confirmed State

The Smart Layer preserves knowledge throughout the lifetime of the project.

---

# Design Principles

Knowledge is never guessed.

Knowledge is established through observation and confirmation.

Evidence proposes.

Knowledge preserves.

---

# Summary

Knowledge is the persistent foundation of NOVA Layer.

It connects artist intent, object understanding, and production assets into a continuous workflow.

Reliable extraction depends not only on better observation, but on better knowledge.

