"""
Per-(model, stage) timing history for ETA estimation.

Persisted to ~/.talkshow_generator/timing_history.json. Each sample stores
(seconds, target_words) so the same data point can be normalized for
different show durations.
"""
import json
from pathlib import Path

from config import APP_DIR

TIMING_FILE = APP_DIR / "timing_history.json"
MAX_SAMPLES = 15

# Stages we record. expand is optional (only when user clicked Expand with AI).
STAGES = ["expand", "act1", "act2", "act3", "act4"]

# Bootstrap: seconds per 1000 target words, used when no history exists.
# Tuned to roughly match a ~50–80 tokens/sec premium provider.
BOOTSTRAP_SEC_PER_1000_WORDS = 12.0
# Floor in case target_words is 0 / unknown.
BOOTSTRAP_FLOOR_SEC = 25.0


class TimingHistory:
    def __init__(self):
        self._data: dict = {}
        self._load()

    # ── disk ──────────────────────────────────────────────────────
    def _load(self):
        if TIMING_FILE.exists():
            try:
                self._data = json.loads(TIMING_FILE.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                self._data = {}

    def _save(self):
        try:
            TIMING_FILE.parent.mkdir(parents=True, exist_ok=True)
            TIMING_FILE.write_text(json.dumps(self._data, indent=2),
                                    encoding="utf-8")
        except OSError:
            pass

    # ── public ────────────────────────────────────────────────────
    def record(self, model: str, stage: str, seconds: float,
               target_words: int = 0):
        if stage not in STAGES:
            return
        bucket = self._data.setdefault(model, {}).setdefault(stage, [])
        bucket.append({"sec": round(float(seconds), 2),
                       "words": int(target_words)})
        if len(bucket) > MAX_SAMPLES:
            del bucket[:-MAX_SAMPLES]
        self._save()

    def estimate(self, model: str, stage: str, target_words: int = 0) -> float:
        """Return seconds. Uses trimmed mean of recorded samples; falls back
        to a bootstrap based on target_words."""
        samples = (self._data.get(model, {}) or {}).get(stage) or []
        if samples:
            # Normalize each sample by its target_words (sec per 1000 words) to
            # be robust to shows of different duration.
            rates = []
            absolutes = []
            for s in samples:
                sec = float(s.get("sec", 0)) or 0
                w = int(s.get("words", 0) or 0)
                if sec > 0:
                    absolutes.append(sec)
                    if w > 0:
                        rates.append(sec / (w / 1000.0))
            if rates and target_words > 0:
                # Trimmed mean of rates → multiplied by current target_words
                rates.sort()
                if len(rates) >= 4:
                    rates = rates[1:-1]
                rate = sum(rates) / len(rates)
                return rate * (target_words / 1000.0)
            if absolutes:
                absolutes.sort()
                if len(absolutes) >= 4:
                    absolutes = absolutes[1:-1]
                return sum(absolutes) / len(absolutes)
        # No samples — bootstrap from words, with a floor.
        if target_words > 0:
            return max(BOOTSTRAP_FLOOR_SEC,
                       BOOTSTRAP_SEC_PER_1000_WORDS * (target_words / 1000.0))
        return BOOTSTRAP_FLOOR_SEC

    def total_estimate(self, model: str, stage_words: dict) -> float:
        """Sum of per-stage estimates. stage_words maps stage -> target_words."""
        return sum(self.estimate(model, st, stage_words.get(st, 0))
                   for st in STAGES if st in stage_words)


# Singleton
HISTORY = TimingHistory()


def format_eta(seconds: float) -> str:
    """Human-readable mm:ss / hh:mm:ss."""
    if seconds < 0:
        seconds = 0
    s = int(seconds)
    if s < 60:
        return f"{s}s"
    m, s = divmod(s, 60)
    if m < 60:
        return f"{m}m{s:02d}s"
    h, m = divmod(m, 60)
    return f"{h}h{m:02d}m"
