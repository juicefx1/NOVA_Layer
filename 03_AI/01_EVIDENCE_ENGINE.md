# NOVA Layer

# 01_EVIDENCE_ENGINE

Version : 1.0 Draft

Status : Internal

Author : Supernova Studios

---

# Purpose

The Evidence Engine is responsible for observing an image or video and extracting useful information for object understanding.

It does not identify objects.

It does not perform extraction.

Its only responsibility is observation.

---

# Philosophy

Observe first.

Understand later.

The Evidence Engine collects evidence without making artistic decisions.

---

# Responsibilities

The Evidence Engine converts raw visual input into multiple forms of evidence that can be used by later systems.

Its output is descriptive, not interpretive.

---

# Evidence Types

## Appearance

Visual appearance of the scene.

Examples include:

- Color
- Texture
- Material
- Local Features

---

## Geometry

Three-dimensional structural information.

Examples include:

- Surface Shape
- Relative Position
- Spatial Structure

---

## Motion

Temporal information extracted from video.

Examples include:

- Object Motion
- Camera Motion
- Optical Flow

---

## Segmentation Proposals

Candidate regions that may represent meaningful objects.

These proposals are not final object definitions.

---

## Edge and Boundary

Information describing possible object boundaries.

Examples include:

- Silhouettes
- Hair Boundaries
- Fine Structures

---

## Temporal Evidence

Information accumulated across multiple frames.

Examples include:

- Frame Correspondence
- Temporal Consistency
- Historical Observations

---

# Characteristics

Evidence may be:

- Incomplete
- Noisy
- Ambiguous
- Conflicting

The Evidence Engine never resolves these uncertainties.

---

# Output

The output of the Evidence Engine is an Evidence Set.

An Evidence Set contains multiple observations describing the same scene from different perspectives.

The Evidence Set becomes the input to the Object Reasoner.

---

# Design Principles

Evidence is observation.

Evidence is not knowledge.

Evidence is not object identity.

Evidence supports reasoning.

---

# Summary

The Evidence Engine transforms raw images into structured observations.

Its responsibility ends when reliable evidence has been collected for downstream reasoning.

