"""
Modal progress dialog for script generation.

Features:
  • Smooth, dynamic progress bar (asymptotic curve inside each act) driven
    by per-(model, stage) timings from timing_history.HISTORY.
  • Real elapsed + estimated remaining (ETA).
  • Pause / Resume — defers the next act until the user un-pauses (the LLM
    call already in flight cannot be interrupted, only the next act).
  • Cancel with confirmation.
  • As each act finishes, a collapsed accordion section appears below — the
    user can expand any section to read finished parts while later acts run.
"""
import math
import time
import tkinter as tk
from tkinter import ttk, messagebox

from ui.widgets import Tooltip, HelpIcon, CollapsibleSection
from timing_history import HISTORY, format_eta


STAGE_KEYS = ["act1", "act2", "act3", "act4"]


class ProgressDialog(tk.Toplevel):
    def __init__(self, parent, title="🎬 Generating...", *,
                 model_slug: str = "",
                 target_words: dict | None = None):
        super().__init__(parent)
        self.title(title)
        self.geometry("960x760")
        self.minsize(820, 600)
        self.transient(parent)
        self.grab_set()
        self.protocol("WM_DELETE_WINDOW", self._on_cancel)

        self._cancelled = False
        self._paused = False
        self._start_time = time.time()
        self._stage_start_time = None
        self._current_stage_idx = -1   # -1 = preparing
        self._sections: dict = {}      # stage_key → CollapsibleSection

        self._model_slug = model_slug or "(unknown)"
        self._target_words = target_words or {}

        # Per-stage estimates pre-computed from HISTORY (seconds)
        self._stage_estimates = {
            sk: HISTORY.estimate(self._model_slug, sk,
                                  self._target_words.get(sk, 0))
            for sk in STAGE_KEYS
        }
        self._total_estimate = sum(self._stage_estimates.values()) or 1.0

        # ── Layout ────────────────────────────────────────────────
        frm = ttk.Frame(self, padding=16); frm.pack(fill="both", expand=True)

        self.title_var = tk.StringVar(value="⏳ Preparing...")
        ttk.Label(frm, textvariable=self.title_var,
                  font=("", 12, "bold")).pack(anchor="w")

        self.stage_var = tk.StringVar(value="")
        ttk.Label(frm, textvariable=self.stage_var,
                  foreground="grey", wraplength=900).pack(anchor="w", pady=(2, 8))

        self.progress = ttk.Progressbar(frm, mode="determinate", maximum=1000)
        self.progress.pack(fill="x")

        # Elapsed + ETA row
        time_row = ttk.Frame(frm); time_row.pack(fill="x", pady=(4, 10))
        self.elapsed_var = tk.StringVar(value="⏱ 0s elapsed")
        ttk.Label(time_row, textvariable=self.elapsed_var,
                  foreground="grey").pack(side="left")
        self.eta_var = tk.StringVar(value="estimating…")
        ttk.Label(time_row, textvariable=self.eta_var,
                  foreground="#3a7d3a", font=("", 9, "bold")).pack(side="left", padx=(12, 0))
        HelpIcon(time_row,
            "Estimate is based on the average time of previous generations for the SAME model "
            "(stored in timing_history.json). The progress bar slides asymptotically within each "
            "act so it never appears 'stuck at 100%' before the act actually finishes."
        ).pack(side="left", padx=(4, 0))

        # Button row: Pause/Resume + Cancel
        btn_row = ttk.Frame(frm); btn_row.pack(fill="x", pady=(0, 12))
        self.pause_btn = ttk.Button(btn_row, text="⏸ Pause",
                                     command=self._toggle_pause)
        self.pause_btn.pack(side="left")
        Tooltip(self.pause_btn,
            "Pause AFTER the current act finishes. The LLM call already in flight cannot be "
            "interrupted — the pipeline just waits before starting the next act.")

        cancel_btn = ttk.Button(btn_row, text="✖ Cancel",
                                 command=self._on_cancel)
        cancel_btn.pack(side="left", padx=(6, 0))
        Tooltip(cancel_btn,
            "Cancel generation with confirmation. Already-completed acts stay visible in this dialog.")

        # Accordion stack (scrollable) for completed acts
        ttk.Label(frm, text="📜 Completed parts (click to expand):",
                  font=("", 10, "bold")).pack(anchor="w")

        scroll_wrap = ttk.Frame(frm); scroll_wrap.pack(fill="both", expand=True,
                                                       pady=(4, 0))
        self._canvas = tk.Canvas(scroll_wrap, highlightthickness=0)
        self._canvas.pack(side="left", fill="both", expand=True)
        sb = ttk.Scrollbar(scroll_wrap, orient="vertical",
                            command=self._canvas.yview)
        sb.pack(side="right", fill="y")
        self._canvas.configure(yscrollcommand=sb.set)
        self._sections_holder = ttk.Frame(self._canvas)
        self._canvas_window = self._canvas.create_window(
            (0, 0), window=self._sections_holder, anchor="nw")
        self._sections_holder.bind("<Configure>",
            lambda _e: self._canvas.configure(scrollregion=self._canvas.bbox("all")))
        self._canvas.bind("<Configure>",
            lambda e: self._canvas.itemconfigure(self._canvas_window, width=e.width))
        # Mousewheel scroll
        self._canvas.bind_all("<MouseWheel>", self._on_mousewheel)

        self._tick_loop()

    # ── Pipeline callbacks ──────────────────────────────────────────
    def update_stage(self, name: str, current: int, total: int):
        """Called BEFORE each act starts."""
        self.title_var.set(f"🎬 Step {current} of {total}")
        self.stage_var.set(name)
        self._current_stage_idx = max(0, current - 1)
        self._stage_start_time = time.time()
        self.update_idletasks()

    def add_completed_part(self, name: str, text: str):
        """Called AFTER each act finishes."""
        # Each part gets its own collapsible section, collapsed by default.
        section = CollapsibleSection(self._sections_holder,
                                      title=name, content_text=text,
                                      expanded=False, text_height=12)
        section.pack(fill="x", pady=(0, 6))
        self._sections[name] = section
        self.update_idletasks()
        # Auto-scroll the canvas to show the newly-added section header
        self._canvas.update_idletasks()
        self._canvas.yview_moveto(1.0)

    def finish(self):
        self.progress["value"] = 1000
        self.title_var.set("✅ Done")
        self.stage_var.set("All acts generated.")
        self.eta_var.set(f"⏱ done in {format_eta(time.time() - self._start_time)}")
        self.update_idletasks()

    # ── Pause / Cancel ──────────────────────────────────────────────
    def _toggle_pause(self):
        self._paused = not self._paused
        if self._paused:
            self.pause_btn.config(text="▶ Resume")
            self.title_var.set("⏸ Paused — will continue after the current act finishes.")
        else:
            self.pause_btn.config(text="⏸ Pause")
            if self._current_stage_idx >= 0:
                self.title_var.set(
                    f"🎬 Step {self._current_stage_idx + 1} of {len(STAGE_KEYS)}")

    def _on_cancel(self):
        if self._cancelled:
            return
        if not messagebox.askyesno("⚠ Cancel generation",
                "Stop generation? Already-completed acts will stay in this dialog, "
                "but the in-flight LLM call (if any) will still bill for completed tokens.",
                parent=self):
            return
        self._cancelled = True
        self.title_var.set("⏸ Cancelling…")

    # ── State accessors used by main_window / pipeline ─────────────
    @property
    def cancelled(self) -> bool:
        return self._cancelled

    @property
    def paused(self) -> bool:
        return self._paused

    # ── Tick: elapsed + dynamic bar + ETA ───────────────────────────
    def _tick_loop(self):
        if self._cancelled:
            return
        try:
            elapsed = time.time() - self._start_time
            self.elapsed_var.set(f"⏱ {format_eta(elapsed)} elapsed")
            self._update_progress_and_eta()
            self.after(300, self._tick_loop)
        except tk.TclError:
            pass

    def _update_progress_and_eta(self):
        # No stage started yet → leave bar at 0, ETA at total estimate
        if self._current_stage_idx < 0 or self._stage_start_time is None:
            self.eta_var.set(f"~{format_eta(self._total_estimate)} remaining (estimate)")
            return

        stage_idx = self._current_stage_idx
        elapsed_in_stage = time.time() - self._stage_start_time
        avg_stage = self._stage_estimates[STAGE_KEYS[stage_idx]] or 1.0

        # Asymptotic per-stage progress: 1 - exp(-t/avg). Never reaches 1.
        per_stage_progress = 1.0 - math.exp(-elapsed_in_stage / avg_stage)
        # Map to overall: completed stages + this stage's partial.
        overall = (stage_idx + per_stage_progress) / len(STAGE_KEYS)
        # Cap at 0.99 so the bar never visually completes before finish().
        overall = min(overall, 0.99)
        self.progress["value"] = overall * 1000

        # ETA: time remaining in current stage + sum of avg of remaining stages.
        remaining_in_stage = max(avg_stage - elapsed_in_stage, 0.0)
        remaining_after = sum(self._stage_estimates[sk]
                              for sk in STAGE_KEYS[stage_idx + 1:])
        eta = remaining_in_stage + remaining_after
        if elapsed_in_stage > avg_stage * 1.3:
            self.eta_var.set(f"~taking longer than usual ({format_eta(elapsed_in_stage - avg_stage)} over avg)")
        else:
            self.eta_var.set(f"~{format_eta(eta)} remaining")

    # ── Misc ────────────────────────────────────────────────────────
    def _on_mousewheel(self, event):
        # Only scroll if cursor is over the canvas
        try:
            x, y = self.winfo_pointerxy()
            target = self.winfo_containing(x, y)
            if target is None:
                return
            # Walk up to see if cursor is inside our canvas
            w = target
            while w is not None:
                if w is self._canvas:
                    self._canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
                    return
                w = w.master
        except tk.TclError:
            pass
