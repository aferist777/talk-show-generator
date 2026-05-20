"""
Per-project thumbnail cache. Every preview thumbnail rendered in the UI
goes through here so we hold small JPEG-encoded copies (~20-30 KB each) in
RAM rather than the full-resolution PNGs / JPEGs / SVGs the rendering
pipeline produces.

Layout:
  <project>/thumbnails/<mirror of original path>.jpg

Example:
  <project>/keyframes/beat_0001_marina_p1.png
    ↓ thumbnail_path_for() ↓
  <project>/thumbnails/keyframes/beat_0001_marina_p1.jpg

API:
  ensure_thumbnail(project, original)        — return thumbnail path, generate
                                                or refresh if stale (mtime check)
  thumbnail_path_for(project, original)      — derived path, no I/O
  regenerate_all_thumbnails(project, on_p)   — background sweep on project open
  rotate_thumbnail(project, original, dest)  — keep thumbnails aligned with the
                                                versioned-rotation helpers
                                                ("foo.png" → "foo.v1.png")
  delete_thumbnail(project, original)        — explicit removal
  clean_orphan_thumbnails(project)           — drop thumbnails whose original
                                                disappeared (auto-pruned by the
                                                background sweep)

JPEG quality is adaptive: we step quality down from 78 until the resulting
file lands under MAX_THUMB_BYTES (~30 KB). Failing that, we accept the
smallest-quality output even if it's a bit over.
"""
import io
import re
from pathlib import Path

# Target ≤ 30 KB per thumbnail (user spec: 20-30 KB).
MAX_THUMB_BYTES = 30 * 1024
THUMB_MAX_DIM = 320

# Filename-only suffixes that count as image originals worth thumbing.
_IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".webp", ".svg")
# Files whose paths sit under the thumbnails dir itself (skip those).
_THUMBNAILS_DIRNAME = "thumbnails"


def thumbnails_dir(project_path: Path) -> Path:
    d = project_path / _THUMBNAILS_DIRNAME
    d.mkdir(parents=True, exist_ok=True)
    return d


def thumbnail_path_for(project_path: Path, original_path: Path) -> Path:
    """Mirror the original's project-relative path under the thumbnails dir,
    swapping its extension for .jpg. Originals outside the project fall back
    to a flat <thumbnails>/<filename>.jpg."""
    try:
        rel = original_path.relative_to(project_path)
    except ValueError:
        rel = Path(original_path.name)
    return thumbnails_dir(project_path) / rel.with_suffix(".jpg")


def _open_image(src: Path):
    """Open an image (PNG/JPEG/WebP via Pillow; SVG via svglib+reportlab)."""
    ext = src.suffix.lower()
    if ext == ".svg":
        from svglib.svglib import svg2rlg
        from reportlab.graphics import renderPM
        drawing = svg2rlg(str(src))
        png_buf = io.BytesIO()
        renderPM.drawToFile(drawing, png_buf, fmt="PNG")
        png_buf.seek(0)
        from PIL import Image
        return Image.open(png_buf)
    from PIL import Image
    return Image.open(src)


def _flatten_to_rgb(img):
    """Convert any mode that has alpha to RGB, pasting onto a white
    background. JPEG can't carry alpha so we have to flatten."""
    if img.mode in ("RGBA", "LA"):
        from PIL import Image
        bg = Image.new("RGB", img.size, (255, 255, 255))
        bg.paste(img, mask=img.split()[-1])
        return bg
    if img.mode == "P":
        return img.convert("RGB")
    if img.mode != "RGB":
        return img.convert("RGB")
    return img


def _save_adaptive_jpeg(img, dest: Path, max_bytes: int = MAX_THUMB_BYTES):
    """Save a JPEG, stepping quality down until the file fits in max_bytes.
    Always writes something (last attempt wins if all are too big)."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    last_bytes = b""
    for q in (78, 70, 62, 55, 48, 42, 36, 30):
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=q, optimize=True)
        data = buf.getvalue()
        last_bytes = data
        if len(data) <= max_bytes:
            dest.write_bytes(data)
            return
    # All passes exceeded the cap — write the smallest one anyway.
    dest.write_bytes(last_bytes)


def _generate_thumbnail(src: Path, dest: Path) -> bool:
    """Generate (or overwrite) the thumbnail at `dest` from `src`. Returns
    True on success, False if Pillow / svglib couldn't open the file."""
    try:
        img = _open_image(src)
    except Exception:
        return False
    try:
        img = _flatten_to_rgb(img)
        from PIL import Image
        img.thumbnail((THUMB_MAX_DIM, THUMB_MAX_DIM), Image.LANCZOS)
        _save_adaptive_jpeg(img, dest, MAX_THUMB_BYTES)
        return True
    except Exception:
        return False


def ensure_thumbnail(project_path: Path, original_path: Path):
    """Return a Path that callers should feed to display widgets. If a fresh
    thumbnail exists it's reused; otherwise we generate it. On any failure
    we return the original path so the UI still shows something."""
    if not project_path or not original_path:
        return original_path
    try:
        if not original_path.exists() or not original_path.is_file():
            return original_path
    except OSError:
        return original_path
    if original_path.suffix.lower() not in _IMAGE_EXTS:
        return original_path
    tp = thumbnail_path_for(project_path, original_path)
    try:
        if tp.exists():
            if tp.stat().st_mtime >= original_path.stat().st_mtime:
                return tp
    except OSError:
        pass
    if _generate_thumbnail(original_path, tp):
        return tp
    return original_path


def rotate_thumbnail(project_path: Path,
                      original_old_path: Path,
                      original_new_path: Path) -> None:
    """Used by the versioned-save helpers: when an original file is renamed
    from <stem>.<ext> to <stem>.v<N>.<ext>, the corresponding thumbnail
    follows the same rename so per-version thumbnails are preserved."""
    if not project_path:
        return
    src_thumb = thumbnail_path_for(project_path, original_old_path)
    dst_thumb = thumbnail_path_for(project_path, original_new_path)
    if not src_thumb.exists():
        return
    try:
        dst_thumb.parent.mkdir(parents=True, exist_ok=True)
        if dst_thumb.exists():
            dst_thumb.unlink()
        src_thumb.rename(dst_thumb)
    except OSError:
        pass


def delete_thumbnail(project_path: Path, original_path: Path) -> None:
    if not project_path or not original_path:
        return
    tp = thumbnail_path_for(project_path, original_path)
    if tp.exists():
        try:
            tp.unlink()
        except OSError:
            pass


def _iter_originals(project_path: Path):
    """Yield every image-like file in the project (excluding files already
    under thumbnails/)."""
    if not project_path.exists():
        return
    for f in project_path.rglob("*"):
        if not f.is_file():
            continue
        if f.suffix.lower() not in _IMAGE_EXTS:
            continue
        try:
            rel = f.relative_to(project_path)
        except ValueError:
            continue
        if rel.parts and rel.parts[0] == _THUMBNAILS_DIRNAME:
            continue
        yield f


def regenerate_all_thumbnails(project_path: Path,
                                on_progress=None,
                                cancel=None) -> int:
    """Background sweep — generate any missing or stale thumbnails for every
    image-like file in the project. Idempotent (mtime check), so safe to
    call on every project open. Returns the number of files processed."""
    if not project_path:
        return 0
    originals = list(_iter_originals(project_path))
    total = len(originals)
    for i, src in enumerate(originals):
        if cancel is not None and cancel():
            break
        if on_progress is not None:
            try:
                on_progress(i + 1, total, src.name)
            except Exception:
                pass
        tp = thumbnail_path_for(project_path, src)
        try:
            if tp.exists() and tp.stat().st_mtime >= src.stat().st_mtime:
                continue
        except OSError:
            pass
        _generate_thumbnail(src, tp)
    return total


def clean_orphan_thumbnails(project_path: Path) -> int:
    """Walk the thumbnails directory and delete every .jpg whose original
    source file no longer exists. Returns the number of files removed."""
    if not project_path:
        return 0
    root = thumbnails_dir(project_path)
    if not root.exists():
        return 0
    removed = 0
    for tp in root.rglob("*.jpg"):
        if not tp.is_file():
            continue
        try:
            rel = tp.relative_to(root)
        except ValueError:
            continue
        # The original could have ANY of the recognised image extensions
        # because we always save the thumbnail as .jpg regardless of input
        # format. Check all candidates.
        stem_rel = rel.with_suffix("")
        original_exists = False
        for ext in _IMAGE_EXTS:
            cand = project_path / stem_rel.with_suffix(ext)
            try:
                if cand.is_file():
                    original_exists = True
                    break
            except OSError:
                continue
        if not original_exists:
            try:
                tp.unlink()
                removed += 1
            except OSError:
                pass
    return removed


# Convenience helper for the rotation paths used elsewhere in the codebase.
_VERSIONED_RE = re.compile(r"^(?P<stem>.+)\.v(?P<num>\d+)\.(?P<ext>[a-z0-9]+)$",
                            re.IGNORECASE)


def is_versioned_filename(name: str) -> bool:
    return bool(_VERSIONED_RE.match(name))
