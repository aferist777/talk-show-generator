"""
Save and load form presets as JSON files.
"""
import json
import re
from pathlib import Path
from datetime import datetime
from config import PRESETS_DIR


def _sanitize(name: str) -> str:
    """Make a filename-safe slug."""
    s = re.sub(r"[^\w\s-]", "", name).strip().replace(" ", "_")
    return s or f"preset_{datetime.now().strftime('%Y%m%d_%H%M%S')}"


def save_preset(name: str, form_data: dict) -> Path:
    """Save preset to ~/.talkshow_generator/presets/<name>.json. Returns path."""
    filename = _sanitize(name) + ".json"
    path = PRESETS_DIR / filename
    payload = {
        "name": name,
        "saved_at": datetime.now().isoformat(),
        "form": form_data,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
    return path


def load_preset(path: Path) -> dict:
    """Load a preset file. Returns the 'form' dict."""
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data.get("form", {})


def list_presets() -> list:
    """List all saved presets as (name, path) tuples, newest first."""
    items = []
    for p in PRESETS_DIR.glob("*.json"):
        try:
            with open(p, "r", encoding="utf-8") as f:
                d = json.load(f)
            items.append((d.get("name", p.stem), p, d.get("saved_at", "")))
        except (json.JSONDecodeError, IOError):
            continue
    items.sort(key=lambda x: x[2], reverse=True)
    return [(name, path) for name, path, _ in items]


def delete_preset(path: Path) -> None:
    """Delete a preset file."""
    path.unlink(missing_ok=True)
