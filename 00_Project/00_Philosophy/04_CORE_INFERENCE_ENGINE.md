# NOVA Layer

# 04_CORE_INFERENCE_ENGINE

Version : 2.0 Draft

Status : Internal

Author : Supernova Studios

---

# Overview

The Core Inference Engine is the central intelligence of NOVA Layer.

Its responsibility is not simply to generate alpha channels.

Its responsibility is to understand the intended object, verify that understanding with the artist, and perform high-precision extraction after object identity has been confirmed.

Unlike conventional segmentation systems, the NOVA Layer inference engine separates object understanding from precision extraction.

This separation improves reliability, computational efficiency, and production quality.

---

# Core Workflow

Every object passes through five independent stages.

Image Input

↓

Evidence Collection

↓

Object Hypothesis

↓

Artist Confirmation

↓

Fine Object Analysis

↓

Production Output

Each stage has a unique responsibility.

No stage replaces another.

---

# Stage 01

## Evidence Collection

The first stage gathers every available source of information.

Examples include:

• Visual Appearance

• Color

• Texture

• Surface Continuity

• Motion

• Optical Flow

• Depth

• Occlusion

• Structural Guides

• Artist Input

Each evidence source is analyzed independently.

No evidence source is trusted by itself.

---

# Stage 02

## Object Hypothesis

The system combines all available evidence to generate a proposed object.

This proposal is called the Object Hypothesis.

The purpose of this stage is understanding.

The purpose is not pixel accuracy.

The hypothesis should answer one question.

"Which physical object does the available evidence most strongly support?"

The result is presented to the artist.

---

# Stage 03

## Artist Confirmation

The artist evaluates the Object Hypothesis.

Possible actions include:

• Accept

• Reject

• Expand

• Reduce

• Add Guidance

Once accepted, object identity becomes trusted information.

The engine no longer attempts to determine artistic intent.

Instead, every remaining computation focuses exclusively on the confirmed object.

---

# Stage 04

## Fine Object Analysis

Fine Analysis performs computationally expensive processing.

Examples include:

• Hair Extraction

• Motion Blur Analysis

• Transparency

• Fur

• Glass

• Smoke

• Soft Edge Recovery

• Fine Boundary Refinement

Since object identity has already been confirmed, all processing concentrates on precision instead of object discovery.

---

# Stage 05

## Production Output

The engine produces production-ready assets.

Examples include:

• High Precision Alpha

• Foreground RGB

• Composite Preview

Future versions may additionally generate:

• Clean Plate

• Object Metadata

• Motion Metadata

• Layer Relationships

---

# Evidence Fusion

Evidence is never evaluated independently.

Every source contributes confidence.

Agreement increases confidence.

Disagreement reduces confidence.

The inference engine evaluates relationships between evidence sources before generating an Object Hypothesis.

This process produces a more reliable understanding than any individual model alone.

---

# Confidence Model

Every stage produces confidence rather than certainty.

Confidence determines whether the system has sufficient understanding to propose an Object Hypothesis.

After artist confirmation, confidence no longer represents object identity.

Instead, confidence represents extraction quality.

This distinction separates understanding from execution.

---

# Computational Strategy

NOVA Layer intentionally delays expensive computation.

The system first performs lightweight analysis to understand the object.

Only after confirmation does the engine execute high-resolution analysis.

This strategy reduces unnecessary computation while improving overall production quality.

---

# Design Summary

The Core Inference Engine is not an alpha generator.

It is an object understanding engine.

Its workflow follows a simple sequence.

Gather evidence.

Understand the object.

Ask the artist.

Receive confirmation.

Execute with maximum precision.

This workflow defines every inference process inside NOVA Layer.

