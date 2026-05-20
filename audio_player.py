"""
Audio playback helper. Wraps pygame.mixer so the rest of the app can stay
unaware of the backend. Lazy-initialises pygame so the import is cheap when
no audio is needed (e.g., during headless smoke tests).

If pygame isn't installed, raise a clear actionable error on first use
rather than failing at import time.
"""
import threading

_mixer = None
_lock = threading.Lock()


def _ensure_mixer():
    global _mixer
    if _mixer is not None:
        return _mixer
    with _lock:
        if _mixer is None:
            try:
                import pygame
                pygame.mixer.init()
                _mixer = pygame.mixer
            except Exception as e:
                raise RuntimeError(
                    "Audio playback requires the 'pygame' package.\n"
                    "Install it with:  pip install pygame\n"
                    f"\nOriginal error: {e}"
                ) from e
    return _mixer


def play(path) -> None:
    """Play an audio file (MP3 / WAV / OGG). Stops any currently-playing
    audio first. Raises RuntimeError if pygame is not installed or the file
    can't be loaded."""
    m = _ensure_mixer()
    try:
        m.music.stop()
        m.music.load(str(path))
        m.music.play()
    except Exception as e:
        raise RuntimeError(f"Could not play '{path}': {e}") from e


def stop() -> None:
    if _mixer is None:
        return
    try:
        _mixer.music.stop()
    except Exception:
        pass


def is_playing() -> bool:
    if _mixer is None:
        return False
    try:
        return bool(_mixer.music.get_busy())
    except Exception:
        return False
