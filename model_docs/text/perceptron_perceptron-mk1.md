---
slug: perceptron/perceptron-mk1
url: https://openrouter.ai/perceptron/perceptron-mk1
fetched_at: 2026-05-17
---

# Perceptron Mk1

## Model Overview

**Full Title:** Perceptron Mk1 (Mark One)

**API Slug:** `perceptron/perceptron-mk1`

**Publication Date:** May 12, 2026

## Pricing

| Metric | Cost |
|--------|------|
| Input Tokens | $0.15 per 1M tokens |
| Output Tokens | $1.50 per 1M tokens |

## Technical Specifications

**Context Window:** 33K tokens

**Weekly Token Allocation:** 130M tokens

**Modalities:** Vision-language (image and video inputs with natural language)

## Capabilities & Strengths

Perceptron Mk1 is designed as "Perceptron's highest-quality vision-language model for video and embodied reasoning." The system excels at:

- Video understanding tasks including QA, summarization, and event detection
- Point-by-example grounding from multimodal prompts on images
- OCR and document parsing for real-world inputs
- Open vocabulary object detection and counting
- Hand pose estimation

## Key Features

**Reasoning Mode:** "Reasoning can be enabled per request to trade latency for deeper analysis on harder tasks."

**Structured Output:** The model supports spatial and temporal annotations when explicitly requested via the `annotation_format` parameter, accepting values like `"point"`, `"box"`, `"polygon"` for images, or `"clip"` for video timestamps. Without this parameter, responses return natural language text only.

## Known Limitations

Narrow vision/video focus — not ideal for long-form text-only generation tasks like scriptwriting.
