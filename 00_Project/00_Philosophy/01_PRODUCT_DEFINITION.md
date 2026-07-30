# NOVA Layer

# 01_PRODUCT_DEFINITION

Version : 2.0 Draft

Status : Internal

Author : Supernova Studios

---

# Product Definition

NOVA Layer is an object understanding and separation system designed for professional visual effects production.

Unlike conventional AI segmentation tools, NOVA Layer does not attempt to automatically determine artistic intent.

Instead, it helps artists identify the intended object, confirms that understanding, and then performs high-precision object extraction.

The objective is not simply to generate alpha channels.

The objective is to create reliable object understanding that leads to production-quality foreground extraction.

---

# The Problem

Object separation remains one of the most repetitive and expensive tasks in visual effects production.

Traditional workflows generally rely on one of three approaches.

• Manual rotoscoping

• AI segmentation

• Tracking-based propagation

Each approach has advantages, but all ultimately require artists to spend significant time correcting object boundaries across many frames.

Most existing systems focus on pixels.

Artists focus on objects.

This difference creates the fundamental limitation of current workflows.

---

# Our Observation

Professional artists do not think in pixels.

They identify complete physical objects.

Even when an object becomes partially hidden, blurred, transparent, or deformed, artists continue to understand it as the same object.

Current AI systems often lose this understanding because they rely primarily on pixel appearance.

NOVA Layer is built around object understanding rather than pixel classification.

---

# Our Solution

NOVA Layer introduces a two-stage workflow.

Stage One focuses on understanding the intended object.

The system gathers evidence from multiple sources and generates an Object Hypothesis.

The artist reviews and confirms this hypothesis.

Stage Two begins only after confirmation.

The system performs detailed object analysis and generates production-quality alpha channels with maximum precision.

This workflow separates artistic decision-making from computational precision.

---

# Core Concept

The artist defines intention.

The system gathers evidence.

The system proposes an object hypothesis.

The artist confirms the hypothesis.

The system performs high-precision analysis.

The final alpha is generated only after object identity has been established.

---

# Product Goal

The purpose of NOVA Layer is not maximum automation.

The purpose is maximum production reliability.

By combining human knowledge with machine inference, NOVA Layer reduces repetitive work while preserving artistic control.

---

# Success Criteria

A successful result is not measured by benchmark accuracy.

Success means:

• Reliable object understanding

• Stable object identity across time

• High-quality alpha generation

• Reduced manual corrections

• Production-ready results

---

# Product Vision

NOVA Layer introduces a new workflow for object separation.

Rather than asking AI to replace artists, it allows artists and AI to work together.

The artist provides intention.

The system provides understanding.

The artist confirms.

The system executes.

Together they produce reliable, production-quality object separation.

