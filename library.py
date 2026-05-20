"""
Cross-project asset library. Lives in ~/.talkshow_generator/<kind>/ next to
prompts/ and projects/. Each saved entry is its own folder containing
params.json + media files.

Two kinds for now: 'characters' and 'studios'. The save/load/list/delete
primitives are kind-agnostic — UI layers build kind-specific params dicts
and pick file names. Each entry folder name is slugified-name + timestamp
to keep re-saves non-destructive (user's choice per the 4.1 / 5.3 answers).
"""
import json
import re
import shutil
import time
import uuid
from pathlib import Path

from config import APP_DIR

LIBRARY_ROOT = APP_DIR
LIBRARY_KINDS = ("characters", "studios", "audiences")


def library_dir(kind: str) -> Path:
    if kind not in LIBRARY_KINDS:
        raise ValueError(f"Unknown library kind: {kind!r}")
    d = LIBRARY_ROOT / kind
    d.mkdir(parents=True, exist_ok=True)
    return d


def slugify(name: str) -> str:
    """Lowercase, replace non-word chars with '_', collapse repeats, trim."""
    s = re.sub(r"[^\w]+", "_", (name or "").strip().lower()).strip("_")
    return s or "item"


def entry_dir(kind: str, slug: str) -> Path:
    return library_dir(kind) / slug


def list_entries(kind: str) -> list:
    """Return [{slug, params, dir}, ...] sorted by display name then slug."""
    out = []
    root = library_dir(kind)
    for d in root.iterdir():
        if not d.is_dir():
            continue
        pj = d / "params.json"
        if not pj.exists():
            continue
        try:
            params = json.loads(pj.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        out.append({"slug": d.name, "params": params, "dir": d})
    out.sort(key=lambda e: ((e["params"].get("name") or "").lower(), e["slug"]))
    return out


def save_entry(kind: str, name: str, params: dict, files: dict) -> Path:
    """Persist a new entry. Each save creates a NEW folder
    '<slug>_<timestamp>/' — non-destructive across re-saves (user choice 4.1).

    Args:
      kind:   'characters' | 'studios'
      name:   display name (used for slug + persisted in params.json)
      params: dict written to params.json (uuid + name auto-injected)
      files:  dict mapping target filename → bytes OR source Path/str.
              Source paths that don't exist are silently skipped.

    Returns the new entry directory path.
    """
    base_slug = slugify(name)
    stamp = time.strftime("%Y%m%d_%H%M%S", time.localtime())
    slug = f"{base_slug}_{stamp}"
    target = library_dir(kind) / slug
    n = 1
    while target.exists():
        slug = f"{base_slug}_{stamp}_{n}"
        target = library_dir(kind) / slug
        n += 1
    target.mkdir(parents=True, exist_ok=True)

    payload = dict(params)
    payload.setdefault("uuid", str(uuid.uuid4()))
    payload.setdefault("name", name)
    payload["saved_at"] = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
    (target / "params.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    for filename, content in files.items():
        dest = target / filename
        if isinstance(content, (bytes, bytearray)):
            dest.write_bytes(bytes(content))
        else:
            src = Path(content)
            if src.exists():
                shutil.copy2(src, dest)
    return target


def load_entry(kind: str, slug: str) -> dict:
    """Return {params, files: {filename → Path}, dir} or None if missing."""
    d = entry_dir(kind, slug)
    pj = d / "params.json"
    if not pj.exists():
        return None
    try:
        params = json.loads(pj.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    files = {p.name: p for p in d.iterdir()
             if p.is_file() and p.name != "params.json"}
    return {"params": params, "files": files, "dir": d}


def delete_entry(kind: str, slug: str) -> bool:
    d = entry_dir(kind, slug)
    if not d.exists():
        return False
    shutil.rmtree(d, ignore_errors=True)
    return not d.exists()
