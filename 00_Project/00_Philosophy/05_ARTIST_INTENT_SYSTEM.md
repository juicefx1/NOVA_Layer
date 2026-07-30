# NOVA Layer

# 05_ARTIST_INTENT_SYSTEM

Version : 2.0 Draft

Status : Internal

Author : Supernova Studios

---

# Overview

The Artist Intent System is the communication layer between the artist and the Core Inference Engine.

Its purpose is not to correct AI mistakes.

Its purpose is to communicate artistic intention in a structured and machine-readable form.

Every interaction teaches the system which object should be understood.

---

# Design Philosophy

Artists naturally understand objects.

Artificial Intelligence does not.

The Artist Intent System bridges this gap.

Instead of asking the AI to guess artistic intent, the artist communicates that intent directly.

The system transforms this information into evidence for object understanding.

Human intention becomes machine knowledge.

---

# Artist Intention

Every interaction answers a single question.

"What is the object the artist intends to isolate?"

The goal is not precision.

The goal is understanding.

Precision comes later.

---

# Intent Channels

The Artist Intent System supports multiple independent communication channels.

Each channel provides different knowledge about the object.

No channel is mandatory.

Artists choose only the information necessary for the current shot.

---

# Channel 01

## Rough Selection

Purpose

Identify the intended object.

The selection does not need to be accurate.

It only needs to communicate intention.

Possible tools

• Brush

• Lasso

• Freehand

Output

Object Identity Hint

---

# Channel 02

## Keyframes

Purpose

Teach how object identity changes over time.

Only meaningful frames require artist input.

The engine infers all remaining frames.

Output

Temporal Identity Hint

---

# Channel 03

## Appearance Guidance

Purpose

Teach consistent appearance.

Examples include

• Color

• Texture

• Material

• Surface continuity

Output

Appearance Evidence

---

# Channel 04

## Spatial Guidance

Purpose

Provide spatial understanding.

Examples include

• Foreground

• Background

• Depth

• Occlusion

Output

Spatial Evidence

---

# Channel 05

## Structural Guidance

Purpose

Describe how the object behaves.

Examples include

• Bones

• Joints

• Pivot points

• Rigid regions

• Flexible regions

Output

Structural Evidence

---

# Knowledge Integration

Every artist interaction increases understanding.

The engine combines all available evidence before generating an Object Hypothesis.

No single interaction determines the final result.

Confidence emerges from accumulated knowledge.

---

# Relationship With Object Hypothesis

The Artist Intent System never generates alpha channels.

Its responsibility ends after sufficient knowledge has been communicated.

The Core Inference Engine transforms this knowledge into an Object Hypothesis.

The artist confirms that hypothesis.

Only then does Fine Analysis begin.

---

# Design Summary

The Artist Intent System exists to communicate intention rather than precision.

Artists do not correct pixels.

Artists describe objects.

The system learns.

The engine understands.

The artist confirms.

The engine executes.

