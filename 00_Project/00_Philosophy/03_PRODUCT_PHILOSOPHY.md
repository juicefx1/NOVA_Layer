# NOVA Layer

# 03_PRODUCT_PHILOSOPHY

Version : 2.0 Draft

Status : Internal

Author : Supernova Studios

---

# Product Philosophy

NOVA Layer is built around a simple belief.

Object separation is fundamentally an object understanding problem rather than a pixel classification problem.

Professional artists identify objects first.

Only then do they refine boundaries.

NOVA Layer follows the same philosophy.

---

# From Segmentation To Understanding

Traditional AI segmentation attempts to predict object boundaries directly.

NOVA Layer follows a different process.

Instead of immediately generating an alpha channel, the system first attempts to understand the intended object.

Understanding becomes the foundation for every subsequent stage.

Without reliable understanding, precise edges have little value.

---

# The Two-Stage Workflow

NOVA Layer separates object extraction into two independent stages.

Stage One is Object Understanding.

The system gathers evidence from multiple independent sources.

Using this evidence, the system generates an Object Hypothesis.

This hypothesis represents the system's current understanding of the intended object.

Stage Two is Precision Extraction.

Only after the hypothesis has been confirmed does the system perform detailed analysis.

This includes edge refinement, hair extraction, transparency analysis, motion blur recovery, and production-quality alpha generation.

---

# Object Hypothesis

An Object Hypothesis is not a finished result.

It is a proposal.

The hypothesis answers one question.

"Is this the object the artist intends to isolate?"

The goal is understanding rather than precision.

The hypothesis should be generated quickly and efficiently.

It exists to support artistic decision-making.

---

# Artist Confirmation

Artists remain responsible for confirming object identity.

Confirmation transforms a hypothesis into trusted information.

Once confirmed, the system no longer spends computational resources deciding which object to isolate.

Instead, all processing focuses on extracting the confirmed object with maximum quality.

---

# Fine Analysis

Fine Analysis is intentionally separated from Object Understanding.

This stage performs computationally expensive processing.

Examples include:

• Hair refinement

• Motion blur reconstruction

• Semi-transparent materials

• Fur

• Smoke

• Glass

• Fine edge recovery

Because object identity has already been confirmed, these analyses can focus entirely on precision.

---

# Human Knowledge

Human input is not treated as correction.

It is treated as knowledge.

Every interaction provides additional information that improves object understanding.

The system continuously integrates this knowledge throughout the workflow.

---

# Evidence-Based Understanding

No single analysis module defines an object.

Visual appearance alone is insufficient.

Depth alone is insufficient.

Motion alone is insufficient.

Structure alone is insufficient.

Only when multiple independent evidence sources support the same interpretation does confidence increase.

Object understanding is therefore evidence-based rather than prediction-based.

---

# Reliable Production

The purpose of this workflow is not simply to improve AI accuracy.

The purpose is to improve production reliability.

Separating understanding from precision produces:

• More stable object identity

• Fewer unnecessary computations

• Higher artist confidence

• Better temporal consistency

• Higher quality alpha channels

---

# Philosophy Summary

NOVA Layer does not begin with precision.

It begins with understanding.

The artist defines intention.

The system gathers evidence.

The system proposes an Object Hypothesis.

The artist confirms.

The system performs Fine Analysis.

Precision becomes the consequence of understanding.

