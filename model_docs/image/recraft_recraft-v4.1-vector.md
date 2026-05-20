---
slug: recraft/recraft-v4.1-vector
url: https://openrouter.ai/recraft/recraft-v4.1-vector
fetched_at: 2026-05-17
capability: t2i+i2i
---

# Recraft V4.1 Vector

## Model Information
- **Full Title:** Recraft V4.1 Vector
- **API Slug:** `recraft/recraft-v4.1-vector`
- **Release Date:** May 13, 2026

## Pricing
- **Cost:** $0.08 per image generated

## Capabilities

### Supported Modalities
- Text input
- Image input
- SVG image output

### Input/Output Support
- **Text-to-Image (t2i):** Yes
- **Image-to-Image (i2i):** Yes (single input image only)

### Output Specifications
- **Format:** SVG (vector graphics)
- **Aspect Ratios:** Multiple supported
- **Typical Generation Time:** ~13 seconds
- **Scaling:** "Output scales cleanly, making it suitable for icons, logos, and other graphics"

## Technical Details
- **Context Window:** 66K tokens
- **Weekly Token Volume:** 5.35M
- **Image Configuration Parameters:**
  - `strength` — adjusts deviation from source image
  - `rgb_colors` — defines color palette
  - `background_rgb_color` — sets background color

## Use Cases & Strengths
Designed for "everyday illustration work where output should be designed rather
than photographed." V4.1 enhancements include enhanced personality in text
rendering, smoother gradients, and improved adherence to brief prompts compared
to previous versions.

Perfect for: show logos, lower-third backgrounds, brand mark assets — anything
that should scale to broadcast resolution without pixellation.

## Limitations
- Only one input image supported for I2I operations
