"""
Project I/O. A project is a folder holding all artifacts of a talk show production:
script (step 1), studio renders + audio + video (step 2), broadcast inserts
(step 3), and the final edit (step 4).
"""
import json
import re
import shutil
from datetime import datetime
from pathlib import Path

from config import PROJECTS_DIR

PROJECT_SUBDIRS = [
    "brand",        # logo, palette, typography
    "studio",       # multi-angle studio renders
    "characters",   # per-character images + idle motion
    "audience",     # audience composition renders
    "audio",        # TTS per-line mp3 + crowd SFX
    "keyframes",    # per-beat still images for speaking beats
    "video",        # speaking clips + reaction clips
    "inserts",      # b-rolls + graphic inserts (step 3)
    "final",        # final assembled mp4 (step 4)
]

STEPS = ["script", "studio", "inserts", "edit"]
STATUS_PENDING = "pending"
STATUS_IN_PROGRESS = "in_progress"
STATUS_DONE = "done"
STATUS_FAILED = "failed"


def _sanitize(name: str) -> str:
    s = re.sub(r"[^\w\s-]", "", name).strip().replace(" ", "_")
    return s or f"project_{datetime.now().strftime('%Y%m%d_%H%M%S')}"


def _ensure_thumb(project_path: Path, original_path: Path) -> None:
    """Generate (or refresh) a thumbnail for an image originality just written
    to disk by the versioned-save helpers. Swallows all errors — thumbnails
    are a UI nicety, not a correctness requirement."""
    try:
        import thumbnails as _th
        _th.ensure_thumbnail(project_path, original_path)
    except Exception:
        pass


def _rotate_thumb(project_path: Path,
                   original_old_path: Path,
                   original_new_path: Path) -> None:
    """Mirror the rotation of an original (foo.png → foo.v1.png) on the
    cached thumbnail (foo.jpg → foo.v1.jpg). Swallows all errors."""
    try:
        import thumbnails as _th
        _th.rotate_thumbnail(project_path, original_old_path,
                              original_new_path)
    except Exception:
        pass


def _initial_statuses() -> dict:
    return {step: STATUS_PENDING for step in STEPS}


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def create_project(name: str, form_data: dict) -> Path:
    """Create a new project folder with subdirs. Auto-suffixes if slug exists."""
    base = _sanitize(name)
    path = PROJECTS_DIR / base
    i = 2
    while path.exists():
        path = PROJECTS_DIR / f"{base}_{i}"
        i += 1
    path.mkdir(parents=True)
    for sub in PROJECT_SUBDIRS:
        (path / sub).mkdir()

    payload = {
        "name": name,
        "created_at": _now(),
        "updated_at": _now(),
        "form": form_data,
        "step_statuses": _initial_statuses(),
    }
    (path / "project.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return path


def save_project(path: Path, form_data: dict,
                 script: str | None = None,
                 step_statuses: dict | None = None) -> Path:
    """Update project.json (and optionally script.txt) for an existing project."""
    pj = path / "project.json"
    existing = {}
    if pj.exists():
        try:
            existing = json.loads(pj.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            existing = {}
    payload = {
        "name": existing.get("name", path.name),
        "created_at": existing.get("created_at", _now()),
        "updated_at": _now(),
        "form": form_data,
        "step_statuses": step_statuses or existing.get("step_statuses", _initial_statuses()),
    }
    pj.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    if script is not None:
        (path / "script.txt").write_text(script, encoding="utf-8")
    return path


def load_project(path: Path) -> dict:
    """Return project metadata; includes 'script' key if script.txt exists."""
    data = json.loads((path / "project.json").read_text(encoding="utf-8"))
    sc = path / "script.txt"
    if sc.exists():
        data["script"] = sc.read_text(encoding="utf-8")
    return data


def list_projects() -> list:
    """Return list of (name, path, updated_at) tuples, newest first."""
    items = []
    for d in PROJECTS_DIR.iterdir():
        if not d.is_dir():
            continue
        pj = d / "project.json"
        if not pj.exists():
            continue
        try:
            data = json.loads(pj.read_text(encoding="utf-8"))
            items.append((data.get("name", d.name), d, data.get("updated_at", "")))
        except (json.JSONDecodeError, OSError):
            continue
    items.sort(key=lambda t: t[2], reverse=True)
    return items


def delete_project(path: Path) -> None:
    shutil.rmtree(path, ignore_errors=True)


def set_step_status(path: Path, step: str, status: str) -> None:
    """Update one step status. Silently no-ops if project.json is missing."""
    pj = path / "project.json"
    if not pj.exists():
        return
    try:
        data = json.loads(pj.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return
    data.setdefault("step_statuses", _initial_statuses())[step] = status
    data["updated_at"] = _now()
    pj.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def brand_path(path: Path) -> Path:
    return path / "brand" / "brand.json"


def logo_path(path: Path) -> Path:
    return path / "brand" / "logo.png"


def save_logo_versioned(path: Path, image_bytes: bytes, ext: str):
    """Save logo to <project>/brand/logo.<ext>. If a previous logo of any
    extension exists, rotate it to logo.v<N>.<old_ext> first.
    Returns (new_path, archived_path_or_None)."""
    import re as _re
    brand_dir = path / "brand"
    brand_dir.mkdir(parents=True, exist_ok=True)

    archived = None
    versioned_re = _re.compile(r"^logo\.v\d+\.")
    existing = [p for p in brand_dir.glob("logo.*")
                if p.is_file() and not versioned_re.match(p.name)]
    for old in existing:
        n = 1
        while (brand_dir / f"logo.v{n}{old.suffix}").exists():
            n += 1
        candidate = brand_dir / f"logo.v{n}{old.suffix}"
        try:
            old.rename(candidate)
            archived = candidate
            _rotate_thumb(path, old, candidate)
        except OSError:
            pass

    dest = brand_dir / f"logo.{ext.lstrip('.')}"
    dest.write_bytes(image_bytes)
    _ensure_thumb(path, dest)
    return dest, archived


def studio_path(path: Path) -> Path:
    return path / "studio" / "studio.json"


def studio_angle_path(path: Path, angle_key: str) -> Path:
    return path / "studio" / f"{angle_key}.png"


def save_studio_angle_versioned(path: Path, angle_key: str,
                                  image_bytes: bytes, ext: str):
    """Save <project>/studio/<angle>.<ext>. If any existing render of this
    angle is present (any extension), rotate it to <angle>.v<N>.<old_ext>
    first. Returns (new_path, archived_path_or_None)."""
    import re as _re
    sd = path / "studio"
    sd.mkdir(parents=True, exist_ok=True)
    archived = None
    versioned_re = _re.compile(rf"^{_re.escape(angle_key)}\.v\d+\.")
    existing = [p for p in sd.glob(f"{angle_key}.*")
                if p.is_file() and not versioned_re.match(p.name)]
    for old in existing:
        n = 1
        while (sd / f"{angle_key}.v{n}{old.suffix}").exists():
            n += 1
        candidate = sd / f"{angle_key}.v{n}{old.suffix}"
        try:
            old.rename(candidate)
            archived = candidate
            _rotate_thumb(path, old, candidate)
        except OSError:
            pass
    dest = sd / f"{angle_key}.{ext.lstrip('.')}"
    dest.write_bytes(image_bytes)
    _ensure_thumb(path, dest)
    return dest, archived


def camera_plan_path(path: Path) -> Path:
    return path / "camera_plan.json"


def save_camera_plan(path: Path, data: dict) -> Path:
    cp = camera_plan_path(path)
    cp.parent.mkdir(parents=True, exist_ok=True)
    cp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return cp


def load_camera_plan(path: Path) -> dict:
    cp = camera_plan_path(path)
    if not cp.exists():
        return {}
    try:
        return json.loads(cp.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def inserts_library_path(path: Path, kind: str) -> Path:
    """kind ∈ {'brolls', 'graphics', 'sfx'}."""
    return path / "inserts" / f"{kind}.json"


def inserts_asset_path(path: Path, kind: str, asset_id: str, ext: str) -> Path:
    """Generated asset file: <project>/inserts/<kind>/<asset_id>.<ext>."""
    return path / "inserts" / kind / f"{asset_id}{ext}"


def save_inserts_library(path: Path, kind: str, data: dict) -> Path:
    lp = inserts_library_path(path, kind)
    lp.parent.mkdir(parents=True, exist_ok=True)
    lp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return lp


def load_inserts_library(path: Path, kind: str) -> dict:
    lp = inserts_library_path(path, kind)
    if not lp.exists():
        return {}
    try:
        return json.loads(lp.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def composition_path(path: Path) -> Path:
    return path / "final" / "composition.json"


def layout_settings_path(path: Path) -> Path:
    return path / "final" / "layout.json"


def preview_mp4_path(path: Path) -> Path:
    return path / "final" / "preview.mp4"


def final_mp4_path(path: Path) -> Path:
    return path / "final" / "final.mp4"


def save_composition(path: Path, data: dict) -> Path:
    cp = composition_path(path)
    cp.parent.mkdir(parents=True, exist_ok=True)
    cp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return cp


def load_composition(path: Path) -> dict:
    cp = composition_path(path)
    if not cp.exists():
        return {}
    try:
        return json.loads(cp.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def save_layout_settings(path: Path, data: dict) -> Path:
    lp = layout_settings_path(path)
    lp.parent.mkdir(parents=True, exist_ok=True)
    lp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return lp


def load_layout_settings(path: Path) -> dict:
    lp = layout_settings_path(path)
    if not lp.exists():
        return {}
    try:
        return json.loads(lp.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def timeline_path(path: Path) -> Path:
    return path / "timeline.json"


def save_timeline(path: Path, data: dict) -> Path:
    tp = timeline_path(path)
    tp.parent.mkdir(parents=True, exist_ok=True)
    tp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return tp


def load_timeline(path: Path) -> dict:
    tp = timeline_path(path)
    if not tp.exists():
        return {}
    try:
        return json.loads(tp.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def storyboard_path(path: Path) -> Path:
    return path / "storyboard.json"


def save_storyboard(path: Path, data: dict) -> Path:
    sp = storyboard_path(path)
    sp.parent.mkdir(parents=True, exist_ok=True)
    sp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return sp


def save_storyboard_versioned(path: Path, data: dict):
    """Persist storyboard.json — if one already exists, rotate it to
    storyboard.v<N>.json first. Returns (new_path, archived_path_or_None)."""
    sp = storyboard_path(path)
    sp.parent.mkdir(parents=True, exist_ok=True)
    archived = None
    if sp.exists():
        n = 1
        while (sp.parent / f"storyboard.v{n}.json").exists():
            n += 1
        archived = sp.parent / f"storyboard.v{n}.json"
        try:
            sp.rename(archived)
        except OSError:
            archived = None  # could not rotate; we'll overwrite
    sp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return sp, archived


def load_storyboard(path: Path) -> dict:
    sp = storyboard_path(path)
    if not sp.exists():
        return {}
    try:
        return json.loads(sp.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def voices_path(path: Path) -> Path:
    return path / "audio" / "voices.json"


def voice_sample_path(path: Path, char_id: str) -> Path:
    return path / "audio" / f"sample_{char_id}.mp3"


def speaker_slugify(name: str) -> str:
    """Slugify a speaker display name for safe filenames."""
    import re as _re
    s = _re.sub(r"[^\w]+", "_", (name or "").strip().lower())
    return s.strip("_") or "unknown"


def audio_beat_path(path: Path, beat_idx: int, speaker_slug: str,
                     part_idx: int = 1) -> Path:
    """TTS audio per beat-part. Uniform `_p<N>` suffix even for single-part
    beats so callers don't need to special-case the no-split case."""
    return path / "audio" / f"beat_{beat_idx:04}_{speaker_slug}_p{part_idx}.mp3"


def keyframe_dir(path: Path) -> Path:
    return path / "keyframes"


def keyframe_path(path: Path, beat_idx: int, speaker_slug: str,
                   ext: str = "png", part_idx: int = 1) -> Path:
    return keyframe_dir(path) / (
        f"beat_{beat_idx:04}_{speaker_slug}_p{part_idx}.{ext.lstrip('.')}")


def video_beat_path(path: Path, beat_idx: int, speaker_slug: str,
                     part_idx: int = 1, ext: str = "mp4") -> Path:
    """Lipsync video per beat-part. Used by the Talking heads thumbnail
    cascade (first frame + ▶ overlay when present). Lipsync rendering is
    not yet wired — this helper just returns the future path."""
    return path / "video" / (
        f"beat_{beat_idx:04}_{speaker_slug}_p{part_idx}.{ext.lstrip('.')}")


def ensemble_shot_path(path: Path, ext: str = "png") -> Path:
    """Wide ensemble shot — all cast members seated together on the sofa.
    Reference / establishing image rendered on the Talking heads tab."""
    return keyframe_dir(path) / f"ensemble_seated.{ext.lstrip('.')}"


def talking_heads_state_path(path: Path) -> Path:
    """Persisted head orientation + free-form text per beat for the
    Talking heads tab. JSON: {<beat_idx>: {orientation, custom_text}}."""
    return path / "talking_heads.json"


def save_talking_heads_state(path: Path, data: dict) -> Path:
    psp = talking_heads_state_path(path)
    psp.parent.mkdir(parents=True, exist_ok=True)
    psp.write_text(json.dumps(data, indent=2, ensure_ascii=False),
                    encoding="utf-8")
    return psp


def load_talking_heads_state(path: Path) -> dict:
    psp = talking_heads_state_path(path)
    if not psp.exists():
        return {}
    try:
        return json.loads(psp.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def pipeline_state_path(path: Path) -> Path:
    return path / "pipeline_state.json"


def save_pipeline_state(path: Path, statuses: dict, costs: dict) -> Path:
    """Persist Generate sub-tab's 7-stage statuses + cost tracking so a
    re-opened project remembers what's already done."""
    psp = pipeline_state_path(path)
    psp.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "stage_statuses": statuses,
        "stage_costs": costs,
        "updated_at": _now(),
    }
    psp.write_text(json.dumps(payload, indent=2, ensure_ascii=False),
                    encoding="utf-8")
    return psp


def load_pipeline_state(path: Path) -> dict:
    psp = pipeline_state_path(path)
    if not psp.exists():
        return {}
    try:
        return json.loads(psp.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def save_voices(path: Path, data: dict) -> Path:
    vp = voices_path(path)
    vp.parent.mkdir(parents=True, exist_ok=True)
    vp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return vp


def load_voices(path: Path) -> dict:
    vp = voices_path(path)
    if not vp.exists():
        return {}
    try:
        return json.loads(vp.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def audience_path(path: Path) -> Path:
    return path / "audience" / "audience.json"


def audience_pose_path(path: Path, pose_key: str) -> Path:
    return path / "audience" / f"{pose_key}.png"


def save_audience_pose_versioned(path: Path, pose_key: str,
                                   image_bytes: bytes, ext: str):
    """Save <project>/audience/<pose>.<ext>. Rotates any existing file of
    this pose (any extension) to <pose>.v<N>.<old_ext> first.
    Returns (new_path, archived_path_or_None)."""
    import re as _re
    ad = path / "audience"
    ad.mkdir(parents=True, exist_ok=True)
    archived = None
    versioned_re = _re.compile(rf"^{_re.escape(pose_key)}\.v\d+\.")
    existing = [p for p in ad.glob(f"{pose_key}.*")
                if p.is_file() and not versioned_re.match(p.name)
                and p.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp")]
    for old in existing:
        n = 1
        while (ad / f"{pose_key}.v{n}{old.suffix}").exists():
            n += 1
        candidate = ad / f"{pose_key}.v{n}{old.suffix}"
        try:
            old.rename(candidate)
            archived = candidate
            _rotate_thumb(path, old, candidate)
        except OSError:
            pass
    dest = ad / f"{pose_key}.{ext.lstrip('.')}"
    dest.write_bytes(image_bytes)
    _ensure_thumb(path, dest)
    return dest, archived


def save_audience(path: Path, data: dict) -> Path:
    ap = audience_path(path)
    ap.parent.mkdir(parents=True, exist_ok=True)
    ap.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return ap


def load_audience(path: Path) -> dict:
    ap = audience_path(path)
    if not ap.exists():
        return {}
    try:
        return json.loads(ap.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def character_dir(path: Path, char_id: str) -> Path:
    return path / "characters" / char_id


def character_face_path(path: Path, char_id: str) -> Path:
    return character_dir(path, char_id) / "face_seed.jpg"


def character_pose_path(path: Path, char_id: str, pose_key: str) -> Path:
    return character_dir(path, char_id) / f"{pose_key}.png"


def save_character_pose_versioned(path: Path, char_id: str, pose_key: str,
                                    image_bytes: bytes, ext: str):
    """Save <project>/characters/<char_id>/<pose>.<ext>. Rotates any existing
    file of this pose (any extension) to <pose>.v<N>.<old_ext> first.
    Returns (new_path, archived_path_or_None)."""
    import re as _re
    cd = character_dir(path, char_id)
    cd.mkdir(parents=True, exist_ok=True)
    archived = None
    versioned_re = _re.compile(rf"^{_re.escape(pose_key)}\.v\d+\.")
    existing = [p for p in cd.glob(f"{pose_key}.*")
                if p.is_file() and not versioned_re.match(p.name)]
    for old in existing:
        n = 1
        while (cd / f"{pose_key}.v{n}{old.suffix}").exists():
            n += 1
        candidate = cd / f"{pose_key}.v{n}{old.suffix}"
        try:
            old.rename(candidate)
            archived = candidate
            _rotate_thumb(path, old, candidate)
        except OSError:
            pass
    dest = cd / f"{pose_key}.{ext.lstrip('.')}"
    dest.write_bytes(image_bytes)
    _ensure_thumb(path, dest)
    return dest, archived


def save_character_params(path: Path, char_id: str, data: dict) -> Path:
    cd = character_dir(path, char_id)
    cd.mkdir(parents=True, exist_ok=True)
    pj = cd / "params.json"
    pj.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return pj


def load_character_params(path: Path, char_id: str) -> dict:
    pj = character_dir(path, char_id) / "params.json"
    if not pj.exists():
        return {}
    try:
        return json.loads(pj.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def list_characters_with_params(path: Path) -> list:
    """Return char_ids that already have params.json on disk."""
    chars_root = path / "characters"
    if not chars_root.exists():
        return []
    return sorted(
        d.name for d in chars_root.iterdir()
        if d.is_dir() and (d / "params.json").exists()
    )


def save_studio(path: Path, data: dict) -> Path:
    sp = studio_path(path)
    sp.parent.mkdir(parents=True, exist_ok=True)
    sp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return sp


def load_studio(path: Path) -> dict:
    sp = studio_path(path)
    if not sp.exists():
        return {}
    try:
        return json.loads(sp.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def save_brand(path: Path, data: dict) -> Path:
    """Persist brand config (palette, typography, era, logo style, etc.) to brand.json."""
    bp = brand_path(path)
    bp.parent.mkdir(parents=True, exist_ok=True)
    bp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return bp


def load_brand(path: Path) -> dict:
    """Read brand.json or return empty dict if missing/unreadable."""
    bp = brand_path(path)
    if not bp.exists():
        return {}
    try:
        return json.loads(bp.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def get_step_statuses(path: Path) -> dict:
    """Return step_statuses dict, or fresh pending set if unreadable."""
    pj = path / "project.json"
    if not pj.exists():
        return _initial_statuses()
    try:
        data = json.loads(pj.read_text(encoding="utf-8"))
        return data.get("step_statuses", _initial_statuses())
    except (json.JSONDecodeError, OSError):
        return _initial_statuses()


def export_project_zip(path: Path, output_zip_path: Path) -> Path:
    """Zip the entire project folder at path and save to output_zip_path."""
    import shutil
    base_name = str(output_zip_path.with_suffix(''))
    shutil.make_archive(base_name, 'zip', root_dir=str(path))
    return output_zip_path.with_suffix('.zip')
