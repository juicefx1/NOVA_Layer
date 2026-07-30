# NOVA Layer

# 06_OBJECT_UNDERSTANDING_MODEL

Version : 2.0 Draft

Status : Internal

Author : Supernova Studios

---

# Overview

The Object Understanding Model defines how NOVA Layer represents a physical object.

Unlike conventional segmentation systems, NOVA Layer does not treat an object as a collection of pixels.

Instead, it represents an object as a combination of multiple forms of evidence that together describe the same physical entity.

Object understanding is therefore a process of evidence integration rather than pixel classification.

---

# Object Identity

Every object inside NOVA Layer has a single identity.

This identity exists independently of appearance.

An object remains the same object even when:

• Lighting changes

• Motion blur appears

• Hair moves

• Parts become occluded

• Texture changes

• Color changes

The purpose of the Object Understanding Model is to preserve identity despite these visual changes.

---

# Evidence Representation

Every object is described through multiple evidence sources.

Examples include:

• Appearance

• Motion

• Depth

• Structure

• Temporal Continuity

• Artist Intent

Each evidence source contributes partial knowledge.

None of them alone define the object.

---

# Evidence Agreement

Evidence may agree.

Evidence may disagree.

When multiple evidence sources support the same object, confidence increases.

When evidence conflicts, the system searches for additional explanations rather than immediately changing object identity.

Object identity should remain stable whenever possible.

---

# Object Hypothesis

The system combines all available evidence into an Object Hypothesis.

The hypothesis is not considered final.

It represents the current best explanation supported by available evidence.

The artist reviews this hypothesis before precision extraction begins.

---

# Confirmation

Confirmation transforms a hypothesis into trusted object identity.

Once confirmed, object identity no longer changes during precision extraction.

Every subsequent analysis assumes that the confirmed object is correct.

---

# Object Lifetime

An object exists throughout an entire shot.

It does not disappear simply because some evidence becomes temporarily unavailable.

Temporary occlusion.

Motion blur.

Camera shake.

Transparency.

These events reduce visible evidence.

They do not remove object identity.

---

# Confidence

Confidence measures the quality of understanding.

It does not measure artistic correctness.

Low confidence suggests additional evidence may be required.

High confidence indicates that multiple independent evidence sources describe the same object.

---

# Relationship With Other Systems

Artist Intent System

↓

Provides knowledge.

↓

Core Inference Engine

↓

Builds Object Hypothesis.

↓

Object Understanding Model

↓

Maintains Object Identity.

↓

Precision Extraction Engine

↓

Generates production-quality alpha.

---

# Design Summary

NOVA Layer does not understand pixels.

NOVA Layer understands objects.

Pixels describe appearance.

Evidence describes identity.

Identity enables precision.

This philosophy defines every stage of object understanding within NOVA Layer.

