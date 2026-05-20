"""
Read and write application settings (API keys, defaults).
"""
import json
from pathlib import Path
from config import CONFIG_FILE, DEFAULT_CONFIG


def load_settings() -> dict:
    """Load settings from config.json. Create with defaults if not exists."""
    if not CONFIG_FILE.exists():
        save_settings(DEFAULT_CONFIG)
        return DEFAULT_CONFIG.copy()
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        # Merge with defaults so newly added keys appear
        merged = DEFAULT_CONFIG.copy()
        merged.update(data)
        return merged
    except (json.JSONDecodeError, IOError):
        return DEFAULT_CONFIG.copy()


def save_settings(settings: dict) -> None:
    """Save settings to config.json."""
    CONFIG_FILE.parent.mkdir(exist_ok=True)
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(settings, f, indent=2, ensure_ascii=False)


def get_setting(key: str, default=None):
    """Get a single setting value."""
    return load_settings().get(key, default)


def set_setting(key: str, value) -> None:
    """Set a single setting value."""
    settings = load_settings()
    settings[key] = value
    save_settings(settings)
