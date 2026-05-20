---
slug: nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free
url: https://openrouter.ai/nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free
fetched_at: 2026-05-17
---

# NVIDIA Nemotron 3 Nano Omni

## Overview

**Full Title:** NVIDIA Nemotron™ 3 Nano Omni (free)

**API Slug:** `nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free`

**Release Date:** April 28, 2026

## Model Specifications

### Architecture
This 30B-A3B parameter model employs "a hybrid MoE Transformer-Mamba architecture with Conv3D video layers" and incorporates Efficient Video Sampling technology for optimized processing.

### Context & Processing
- **Context Window:** 256,000 tokens
- **Reasoning Budget:** 16,384 tokens (extended thinking available via `reasoning.enabled`)

### Modalities Supported
- Text input/output
- Image input
- Video input
- Audio input

## Pricing

**Cost:** Free

**Weekly Token Allocation:** 17.4B tokens

*Note: Per-million token rates not specified — the model is offered free.*

## Capabilities & Intended Use

The model functions as "a perception and context sub-agent in enterprise agent systems," enabling agents to process multimodal inputs within a single inference pass. It delivers approximately 2× higher throughput and 2.5× lower computational requirements for video reasoning compared to separate vision and speech pipelines.
