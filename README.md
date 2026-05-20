# TalkShow Generator

Local Python desktop app for generating infomercial / advertorial talk show scripts in the four-act structure (Opening → Heroine → Expert + Antagonist → Offer).

Designed for **media-literacy analysis and satirical deconstruction** — produce a worked example of the genre, then take it apart to teach how it works.

## Features

- **Three LLM providers**: OpenRouter (cloud, all major models), Anthropic Direct, Ollama (local, free)
- **Form-driven**: 30+ fields covering show, theme, heroine, antagonist, product, offer
- **AI helpers**: expand short brainstorm notes into detailed creative directives; generate pseudo-scientific product names
- **Four-act pipeline**: each act is generated as a separate LLM call with summary passing for continuity
- **Cost estimation** shown before generation (for OpenRouter / Anthropic)
- **Presets**: save and reload form configurations as JSON
- **Output**: plain `.txt` script with timecodes, stage directions, and dialogue

## Requirements

- **Python 3.9+** (uses only stdlib — `tkinter`, `urllib`, `json`)
- **API key** for OpenRouter (recommended) OR Anthropic OR a local Ollama install

No pip packages required.

## Quick start

```bash
cd talkshow_generator
python app.py
```

On first launch, click **Settings...** and paste your API key. Then test the connection.

## How the pipeline works

1. (Optional) **Expand**: if you typed a brief idea in "Additional instructions" and clicked "Expand with AI", a quick LLM call develops it into clear creative directives.
2. **Act 1** generated: opening, hosts, problem agitation.
3. **Act 2** generated: heroine arrives, friends testify. Receives Act 1 summary as context.
4. **Act 3** generated: expert + antagonist arc. Receives Acts 1–2 summaries.
5. **Act 4** generated: offer, urgency, close. Receives Acts 1–3 summaries.

Summaries are extracted from `<summary>...</summary>` tags the model produces at the end of each act. Total runtime: 1–4 minutes depending on model and provider.

## File structure

```
talkshow_generator/
├── app.py                  # entry point
├── config.py               # paths, constants, dropdown options
├── settings.py             # ~/.talkshow_generator/config.json I/O
├── presets.py              # ~/.talkshow_generator/presets/ I/O
├── pricing.py              # OpenRouter price table and cost estimation
├── llm_clients.py          # OpenRouter / Ollama / Anthropic / kie.ai clients
├── prompts.py              # all prompt templates
├── pipeline.py             # 4-act generation orchestration
└── ui/
    ├── main_window.py      # form
    ├── settings_dialog.py  # API keys & defaults
    ├── progress_dialog.py  # modal progress with cancel
    └── widgets.py          # LabeledEntry / LabeledCombobox / LabeledText
```

## Notes

- **kie.ai** is wired into settings for v2 (visual asset generation), but is not used in v1.
- Pricing table in `pricing.py` is approximate and may drift — update manually if needed.
- Settings and presets live in `~/.talkshow_generator/` (cross-platform: home directory).
- Scripts are saved as UTF-8 `.txt` files with timecodes inline (no DOCX in v1).

## What this is not for

This tool produces clearly-marked **creative artifacts for educational deconstruction**. The script header includes an explicit notice that the output is a worked example of an advertorial-style format intended for media-literacy analysis. Don't use the output as real advertising — fabricating product claims to sell goods to real customers is fraud in virtually every jurisdiction.
