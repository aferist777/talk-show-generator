"""
Step 4 — Editing & Assembly.

Final ffmpeg pipeline that stitches together:
  • the studio timeline from step 2 (speaking + reaction + audience + entrance clips)
  • the raw assets from step 3 (b-rolls, graphic overlays, SFX)
  • brand colors / typography from step 2's Logo & Brand sub-tab

Produces preview.mp4 (proxy) and final.mp4 (broadcast).

Sub-tabs:
  📋 Composition plan  — per-clip overlay decisions (LLM-generated, user-editable)
  🎨 Layout settings   — PiP position, lower-third style, audio mix
  ▶ Render & output    — staged ffmpeg render pipeline with cost tally
"""
import json
import threading
import time
import tkinter as tk
from tkinter import ttk, messagebox

import config as cfg
import projects
from ui.widgets import (
    LabeledCombobox, LabeledSlider, SectionFrame, Tooltip, HelpIcon,
    ModelPicker, bind_autosave,
)


class EditingTab(ttk.Frame):
    """Step 4 outer container with the sub-notebook."""

    def __init__(self, parent, main_window):
        super().__init__(parent)
        self.main = main_window

        # State
        self._composition: dict | None = None
        self._render_stage_statuses: dict = {
            key: "pending" for key, _ in cfg.EDITING_PIPELINE_STAGES
        }
        self._render_stage_costs: dict = {
            key: 0.0 for key, _ in cfg.EDITING_PIPELINE_STAGES
        }
        self._render_cancel = threading.Event()
        self._render_thread = None

        nb = ttk.Notebook(self, padding=6)
        nb.pack(fill="both", expand=True)
        self._sub_nb = nb

        tab_plan = ttk.Frame(nb, padding=14)
        tab_layout = ttk.Frame(nb, padding=14)
        tab_render = ttk.Frame(nb, padding=14)

        nb.add(tab_plan, text="📋 Composition plan")
        nb.add(tab_layout, text="🎨 Layout settings")
        nb.add(tab_render, text="▶ Render & output")
        self._sub_tabs = {"plan": tab_plan, "layout": tab_layout,
                           "render": tab_render}
        self._sub_tab_originals = {"plan": "📋 Composition plan",
                                    "layout": "🎨 Layout settings",
                                    "render": "▶ Render & output"}

        self._build_plan_tab(tab_plan)
        self._build_layout_tab(tab_layout)
        self._build_render_tab(tab_render)

    # ── 📋 Composition plan ─────────────────────────────────────────
    def _build_plan_tab(self, parent):
        # Actions
        af = SectionFrame(parent, "▶ Actions")
        af.pack(fill="x", pady=(0, 10))
        ModelPicker(af, kind="text", main_window=self.main,
                     label_text="Text model:").pack(anchor="w", pady=(0, 6))

        btn_row = ttk.Frame(af); btn_row.pack(fill="x")
        plan_btn = ttk.Button(btn_row, text="🤖 Auto-plan with LLM",
                               command=self._auto_plan)
        plan_btn.pack(side="left")
        Tooltip(plan_btn,
            "Send the timeline + asset library + script to the LLM. For each speaking clip "
            "it proposes overlays: which b-roll to play, which graphic to flash, where to place "
            "the speaker PiP, when to drop a lower-third, when to fire SFX.")

        reload_btn = ttk.Button(btn_row, text="🔄 Reload from timeline",
                                 command=self._reload_from_timeline)
        reload_btn.pack(side="left", padx=(6, 0))
        Tooltip(reload_btn,
            "Re-import clip rows from <project>/timeline.json. "
            "Erases any unsaved composition decisions for clips that no longer exist.")

        save_btn = ttk.Button(btn_row, text="💾 Save composition plan",
                               command=self._save_composition)
        save_btn.pack(side="left", padx=(6, 0))
        Tooltip(save_btn,
            "Persist the composition plan to <project>/final/composition.json. "
            "This is what the render pipeline reads in step 4.3 & 4.4.")

        self._plan_status_var = tk.StringVar(value="(no plan generated yet)")
        ttk.Label(af, textvariable=self._plan_status_var,
                  foreground="grey", wraplength=900).pack(anchor="w", pady=(8, 0))

        # Composition decisions table
        tf = SectionFrame(parent, "📋 Per-clip overlay decisions")
        tf.pack(fill="both", expand=True)

        cols = ("idx", "time", "speaker", "overlay_type", "asset", "position", "duration", "notes")
        self.plan_tree = ttk.Treeview(tf, columns=cols, show="headings",
                                       height=16, selectmode="browse")
        headings = {
            "idx": "#", "time": "Time", "speaker": "Speaker",
            "overlay_type": "Overlay type", "asset": "Asset",
            "position": "Position", "duration": "Dur", "notes": "Notes",
        }
        widths = {
            "idx": 40, "time": 70, "speaker": 130,
            "overlay_type": 140, "asset": 200, "position": 100,
            "duration": 60, "notes": 280,
        }
        for c in cols:
            self.plan_tree.heading(c, text=headings[c])
            self.plan_tree.column(c, width=widths[c],
                anchor="w" if c in ("speaker", "overlay_type", "asset", "position", "notes")
                       else "center")
        scroll = ttk.Scrollbar(tf, orient="vertical", command=self.plan_tree.yview)
        self.plan_tree.configure(yscrollcommand=scroll.set)
        self.plan_tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

        # Help footer
        help_row = ttk.Frame(parent); help_row.pack(fill="x", pady=(8, 0))
        ttk.Label(help_row,
            text=("ℹ Overlay types: full-screen b-roll (replace speaker), "
                  "PiP b-roll (over speaker), graphic flash (over speaker), "
                  "lower-third (speaker name/role), SFX cue."),
            foreground="grey", wraplength=900,
            font=("", 9, "italic")).pack(anchor="w")

    # ── 🎨 Layout settings ──────────────────────────────────────────
    def _build_layout_tab(self, parent):
        # Picture-in-picture
        pf = SectionFrame(parent, "📺 Speaker PiP (during b-roll / graphics)")
        pf.pack(fill="x", pady=(0, 10))
        grid = ttk.Frame(pf); grid.pack(fill="x")
        for c in range(2):
            grid.columnconfigure(c, weight=1)

        self.layout_pip_pos = LabeledCombobox(grid, "PiP position",
            cfg.PIP_POSITIONS, cfg.DEFAULT_LAYOUT_SETTINGS["pip_position"],
            help_text="Corner where the speaker's lip-sync clip sits when a full-screen b-roll or graphic is playing.")
        self.layout_pip_pos.grid(row=0, column=0, sticky="ew", padx=(0, 8), pady=4)

        self.layout_pip_size = LabeledCombobox(grid, "PiP size",
            cfg.PIP_SIZES, cfg.DEFAULT_LAYOUT_SETTINGS["pip_size"],
            help_text="How large the speaker PiP appears. Medium reads as classic infomercial; large is rare and editorial.")
        self.layout_pip_size.grid(row=0, column=1, sticky="ew", pady=4)

        # Lower thirds / branding
        lf = SectionFrame(parent, "🏷 Lower thirds & branding")
        lf.pack(fill="x", pady=(0, 10))
        lgrid = ttk.Frame(lf); lgrid.pack(fill="x")
        for c in range(2):
            lgrid.columnconfigure(c, weight=1)

        self.layout_lt_style = LabeledCombobox(lgrid, "Lower-third style",
            cfg.LOWER_THIRD_STYLES, cfg.DEFAULT_LAYOUT_SETTINGS["lower_third_style"],
            help_text="Visual style of name/role plates that appear under each speaker. Uses brand colors from step 2.")
        self.layout_lt_style.grid(row=0, column=0, sticky="ew", padx=(0, 8), pady=4)

        self.layout_logo_freq = LabeledCombobox(lgrid, "Show-logo bumper frequency",
            cfg.LOGO_BUMPER_FREQUENCIES, cfg.DEFAULT_LAYOUT_SETTINGS["logo_bumper_freq"],
            help_text="How often a 1-second show-logo bumper is inserted between clips. 'Act transitions only' is the classic choice.")
        self.layout_logo_freq.grid(row=0, column=1, sticky="ew", pady=4)

        # Render quality
        rf = SectionFrame(parent, "🎬 Render quality")
        rf.pack(fill="x", pady=(0, 10))
        self.layout_quality = LabeledCombobox(rf, "Output quality",
            cfg.RENDER_QUALITIES, cfg.DEFAULT_LAYOUT_SETTINGS["render_quality"],
            help_text="ffmpeg encoding preset. Preview = fast, draft-quality. Broadcast = standard 1080p. High = slow encode, best quality.")
        self.layout_quality.pack(fill="x")

        # Audio mix
        af = SectionFrame(parent, "🔊 Audio mix")
        af.pack(fill="x", pady=(0, 10))

        self.layout_tts_db = LabeledSlider(af, "TTS dialogue volume",
            from_=-20.0, to=6.0, default=cfg.DEFAULT_LAYOUT_SETTINGS["tts_volume_db"],
            resolution=1.0, fmt="{:+.0f} dB",
            help_text="Volume of character speech relative to 0 dB. 0 is the reference level; negative ducks dialogue under SFX.")
        self.layout_tts_db.pack(fill="x", pady=(4, 0))

        self.layout_sfx_db = LabeledSlider(af, "SFX volume",
            from_=-20.0, to=6.0, default=cfg.DEFAULT_LAYOUT_SETTINGS["sfx_volume_db"],
            resolution=1.0, fmt="{:+.0f} dB",
            help_text="Volume of stings/whooshes/transition SFX. Typically -6 dB below dialogue.")
        self.layout_sfx_db.pack(fill="x", pady=(4, 0))

        self.layout_aud_db = LabeledSlider(af, "Audience reactions volume",
            from_=-20.0, to=6.0, default=cfg.DEFAULT_LAYOUT_SETTINGS["audience_volume_db"],
            resolution=1.0, fmt="{:+.0f} dB",
            help_text="Volume of applause / boos / laughter / room tone. Typically -8 dB so they support but don't compete with dialogue.")
        self.layout_aud_db.pack(fill="x", pady=(4, 0))

        # Save / reset
        save_row = ttk.Frame(parent); save_row.pack(fill="x")
        save_btn = ttk.Button(save_row, text="💾 Save layout settings",
                               command=self._save_layout)
        save_btn.pack(side="left")
        Tooltip(save_btn,
            "Persist layout settings to <project>/final/layout.json. "
            "Read by the ffmpeg renderer when composing overlays.")

        reset_btn = ttk.Button(save_row, text="↩ Reset to defaults",
                                command=self._reset_layout)
        reset_btn.pack(side="left", padx=(6, 0))
        Tooltip(reset_btn, "Restore all layout fields to defaults (bottom-right PiP, network-bar lower thirds, etc.).")

        self._layout_status_var = tk.StringVar(value="")
        ttk.Label(parent, textvariable=self._layout_status_var,
                  foreground="grey", wraplength=900).pack(anchor="w", pady=(8, 0))

        # Auto-save bindings for Layout settings
        for w in (self.layout_pip_pos, self.layout_pip_size,
                   self.layout_lt_style, self.layout_logo_freq,
                   self.layout_quality, self.layout_tts_db,
                   self.layout_sfx_db, self.layout_aud_db):
            bind_autosave(w, lambda: self._schedule_silent_save("layout"))

    # ── ▶ Render & output ───────────────────────────────────────────
    def _build_render_tab(self, parent):
        # Master controls
        mc = SectionFrame(parent, "▶ ffmpeg render pipeline")
        mc.pack(fill="x", pady=(0, 10))

        btn_row = ttk.Frame(mc); btn_row.pack(fill="x")
        run_all = ttk.Button(btn_row, text="▶ Run full render pipeline",
                              command=self._run_full_render)
        run_all.pack(side="left")
        Tooltip(run_all,
            "Run all 4 render stages sequentially. Stages already 'done' are skipped. "
            "The full pipeline outputs preview.mp4 and final.mp4.")

        cancel_btn = ttk.Button(btn_row, text="⏸ Cancel",
                                 command=self._cancel_render)
        cancel_btn.pack(side="left", padx=(6, 0))
        Tooltip(cancel_btn,
            "Stop the current stage at its next checkpoint. Already-rendered preview keeps existing.")

        reset_btn = ttk.Button(btn_row, text="🗑 Reset statuses",
                                command=self._reset_render)
        reset_btn.pack(side="left", padx=(6, 0))
        Tooltip(reset_btn,
            "Mark all stages as pending and clear cost tracking. Does NOT delete the rendered mp4 files.")

        clear_log_btn = ttk.Button(btn_row, text="🧹 Clear log",
                                    command=self._clear_render_log)
        clear_log_btn.pack(side="left", padx=(20, 0))
        Tooltip(clear_log_btn, "Clear the log view.")

        # Stages grid
        sg = SectionFrame(parent, "📋 Render stages")
        sg.pack(fill="x", pady=(0, 10))

        grid = ttk.Frame(sg); grid.pack(fill="x")
        grid.columnconfigure(1, weight=1)

        for c, h in enumerate(["", "Stage", "Status", "Progress", "Cost", ""]):
            ttk.Label(grid, text=h, font=("", 9, "bold")).grid(
                row=0, column=c, sticky="w",
                padx=(0 if c == 0 else 6, 0), pady=(0, 4))

        self._render_stage_widgets: dict = {}
        for i, (key, label) in enumerate(cfg.EDITING_PIPELINE_STAGES):
            r = i + 1
            icon_lbl = ttk.Label(grid, text="⏸", width=2, foreground="grey")
            icon_lbl.grid(row=r, column=0, sticky="w", pady=2)
            ttk.Label(grid, text=label).grid(row=r, column=1, sticky="w", padx=(0, 6))
            status_lbl = ttk.Label(grid, text="pending", foreground="grey")
            status_lbl.grid(row=r, column=2, sticky="w", padx=(0, 6))
            progress_lbl = ttk.Label(grid, text="—", foreground="grey")
            progress_lbl.grid(row=r, column=3, sticky="w", padx=(0, 6))
            cost_lbl = ttk.Label(grid, text="—", foreground="grey")
            cost_lbl.grid(row=r, column=4, sticky="w", padx=(0, 12))
            run_btn = ttk.Button(grid, text="▶ Run", width=8,
                                  command=lambda k=key: self._run_render_stage(k))
            run_btn.grid(row=r, column=5, sticky="w")
            Tooltip(run_btn, f"Run only the '{label}' stage.")
            self._render_stage_widgets[key] = {
                "icon": icon_lbl, "status": status_lbl,
                "progress": progress_lbl, "cost": cost_lbl, "run": run_btn,
            }

        # Total cost with hover tooltip
        total_frame = ttk.Frame(sg); total_frame.pack(fill="x", pady=(12, 0))
        ttk.Label(total_frame, text="Running total:",
                  font=("", 10, "bold")).pack(side="left")
        self._render_total_var = tk.StringVar(value="$0.00")
        total_lbl = ttk.Label(total_frame, textvariable=self._render_total_var,
                               foreground="#3a7d3a", font=("", 10, "bold"),
                               cursor="question_arrow")
        total_lbl.pack(side="left", padx=(6, 0))
        self._render_total_tooltip = Tooltip(total_lbl,
            "(no costs accrued yet)", wraplength=420)

        # Output paths
        of = SectionFrame(parent, "📁 Output files")
        of.pack(fill="x", pady=(0, 10))
        out_row = ttk.Frame(of); out_row.pack(fill="x")
        self._preview_path_var = tk.StringVar(value="(not yet rendered)")
        self._final_path_var = tk.StringVar(value="(not yet rendered)")
        ttk.Label(out_row, text="Preview:", font=("", 9, "bold")).grid(row=0, column=0, sticky="w", padx=(0, 6), pady=2)
        ttk.Label(out_row, textvariable=self._preview_path_var, foreground="#444").grid(row=0, column=1, sticky="w", pady=2)
        open_prev_btn = ttk.Button(out_row, text="📂 Open", width=8,
                                    command=self._open_preview)
        open_prev_btn.grid(row=0, column=2, padx=(8, 0), pady=2)
        Tooltip(open_prev_btn, "Open the preview mp4 in the system default video player.")

        ttk.Label(out_row, text="Final:", font=("", 9, "bold")).grid(row=1, column=0, sticky="w", padx=(0, 6), pady=2)
        ttk.Label(out_row, textvariable=self._final_path_var, foreground="#444").grid(row=1, column=1, sticky="w", pady=2)
        open_final_btn = ttk.Button(out_row, text="📂 Open", width=8,
                                     command=self._open_final)
        open_final_btn.grid(row=1, column=2, padx=(8, 0), pady=2)
        Tooltip(open_final_btn, "Open the final mp4 in the system default video player.")

        # Log
        lf = SectionFrame(parent, "📜 Log")
        lf.pack(fill="both", expand=True)
        log_box = ttk.Frame(lf); log_box.pack(fill="both", expand=True)
        self._render_log = tk.Text(log_box, height=10, wrap="word",
                                    state="disabled",
                                    background="#1a1a1a", foreground="#dddddd",
                                    font=("Consolas", 9), padx=8, pady=6)
        self._render_log.pack(side="left", fill="both", expand=True)
        log_scroll = ttk.Scrollbar(log_box, orient="vertical",
                                    command=self._render_log.yview)
        self._render_log.configure(yscrollcommand=log_scroll.set)
        log_scroll.pack(side="right", fill="y")

        # Initial paint
        for key in self._render_stage_statuses:
            self._refresh_render_stage(key)
        self._refresh_render_total()

    # ── HELPERS ─────────────────────────────────────────────────────
    def _require_project(self) -> bool:
        if not self.main.current_project:
            messagebox.showwarning(
                "⚠ No project",
                "Open or save a project first — editing artifacts live inside the project folder.",
                parent=self,
            )
            return False
        return True

    def _log_render(self, line: str):
        stamp = time.strftime("%H:%M:%S")
        self._render_log.config(state="normal")
        self._render_log.insert("end", f"[{stamp}] {line}\n")
        self._render_log.see("end")
        self._render_log.config(state="disabled")

    def _clear_render_log(self):
        self._render_log.config(state="normal")
        self._render_log.delete("1.0", "end")
        self._render_log.config(state="disabled")

    _STATUS_ICONS = {
        "pending":     ("⏸", "grey"),
        "in_progress": ("▶", "#1d4e89"),
        "done":        ("✅", "#3a7d3a"),
        "failed":      ("❌", "#c84141"),
        "skipped":     ("⏭", "#888"),
    }

    def _refresh_render_stage(self, key: str):
        w = self._render_stage_widgets.get(key)
        if not w:
            return
        st = self._render_stage_statuses.get(key, "pending")
        icon, color = self._STATUS_ICONS.get(st, ("⏸", "grey"))
        w["icon"].config(text=icon, foreground=color)
        w["status"].config(text=st, foreground=color)
        cost = self._render_stage_costs.get(key, 0.0)
        w["cost"].config(text=(f"${cost:.4f}" if cost > 0 else "—"),
                         foreground="#3a7d3a" if cost > 0 else "grey")

    def _set_render_stage(self, key, status=None, progress=None, cost_delta=None):
        if status is not None:
            self._render_stage_statuses[key] = status
        if cost_delta:
            self._render_stage_costs[key] += cost_delta
        if progress is not None:
            w = self._render_stage_widgets.get(key)
            if w:
                w["progress"].config(text=progress)
        self._refresh_render_stage(key)
        self._refresh_render_total()

    def _refresh_render_total(self):
        total = sum(self._render_stage_costs.values())
        self._render_total_var.set(f"${total:.4f}")
        if total <= 0:
            self._render_total_tooltip.text = "(no costs accrued yet)"
            return
        lines = []
        for key, label in cfg.EDITING_PIPELINE_STAGES:
            cost = self._render_stage_costs.get(key, 0.0)
            if cost > 0:
                lines.append(f"  {label}: ${cost:.4f}")
        self._render_total_tooltip.text = "Cost breakdown:\n" + "\n".join(lines)

    # ── PLAN ACTIONS ────────────────────────────────────────────────
    def _reload_from_timeline(self):
        if not self._require_project():
            return
        data = projects.load_timeline(self.main.current_project)
        clips = data.get("clips", []) if data else []
        if not clips:
            self._plan_status_var.set(
                "⚠ No timeline found. Build and save the timeline in step 2 first.")
            return
        # Initialize composition rows from clips with empty overlay decisions
        rows = []
        for c in clips:
            rows.append({
                "clip_id":   c.get("id"),
                "time":      c.get("start", 0),
                "speaker":   c.get("speaker", ""),
                "overlay_type": "—",
                "asset":     "—",
                "position":  "—",
                "duration":  0.0,
                "notes":     "",
            })
        self._composition = {"version": 1, "rows": rows}
        self._refresh_plan_tree()
        self._plan_status_var.set(
            f"✅ Loaded {len(rows)} clips from timeline. "
            f"Click 🤖 Auto-plan with LLM to populate overlays.")
        self._schedule_silent_save("composition")

    def _refresh_plan_tree(self):
        for iid in self.plan_tree.get_children():
            self.plan_tree.delete(iid)
        if not self._composition:
            return
        for i, row in enumerate(self._composition.get("rows", [])):
            t = row.get("time", 0)
            m, s = int(t // 60), t - int(t // 60) * 60
            self.plan_tree.insert("", "end", iid=str(i), values=(
                i + 1,
                f"{m:02d}:{s:05.2f}",
                row.get("speaker") or "—",
                row.get("overlay_type") or "—",
                row.get("asset") or "—",
                row.get("position") or "—",
                f"{row.get('duration', 0):.1f}",
                (row.get("notes") or "")[:60],
            ))

    def _auto_plan(self):
        if not self._require_project():
            return
        if not self._composition:
            self._reload_from_timeline()
            if not self._composition:
                return
        self._plan_status_var.set("🚧 Auto-plan via LLM not yet wired — coming next iteration. "
            "Will analyse each clip's context against the inserts library and propose overlays.")

    def _save_composition(self):
        if not self._require_project():
            return
        if not self._composition:
            messagebox.showinfo("⚠ No plan",
                "Click 🔄 Reload from timeline to initialize the composition first.",
                parent=self)
            return
        path = projects.save_composition(self.main.current_project, self._composition)
        self._plan_status_var.set(f"✅ Composition plan saved: {path}")

    # ── LAYOUT ACTIONS ──────────────────────────────────────────────
    def _collect_layout(self) -> dict:
        return {
            "pip_position":       self.layout_pip_pos.get(),
            "pip_size":           self.layout_pip_size.get(),
            "lower_third_style":  self.layout_lt_style.get(),
            "logo_bumper_freq":   self.layout_logo_freq.get(),
            "render_quality":     self.layout_quality.get(),
            "tts_volume_db":      self.layout_tts_db.get(),
            "sfx_volume_db":      self.layout_sfx_db.get(),
            "audience_volume_db": self.layout_aud_db.get(),
        }

    def _apply_layout_data(self, data: dict):
        if not data:
            return
        if data.get("pip_position"):      self.layout_pip_pos.set(data["pip_position"])
        if data.get("pip_size"):          self.layout_pip_size.set(data["pip_size"])
        if data.get("lower_third_style"): self.layout_lt_style.set(data["lower_third_style"])
        if data.get("logo_bumper_freq"):  self.layout_logo_freq.set(data["logo_bumper_freq"])
        if data.get("render_quality"):    self.layout_quality.set(data["render_quality"])
        if "tts_volume_db" in data:       self.layout_tts_db.set(data["tts_volume_db"])
        if "sfx_volume_db" in data:       self.layout_sfx_db.set(data["sfx_volume_db"])
        if "audience_volume_db" in data:  self.layout_aud_db.set(data["audience_volume_db"])

    def _save_layout(self):
        if not self._require_project():
            return
        path = projects.save_layout_settings(self.main.current_project,
                                              self._collect_layout())
        self._layout_status_var.set(f"✅ Layout settings saved: {path}")

    def refresh_sub_tab_marks(self) -> tuple:
        """Update ✅ marks on each editing sub-tab. Returns (all_done, any_done)
        for MainWindow's tri-state rollup (✅ / ⚠ / nothing)."""
        proj = self.main.current_project
        states = {"plan": False, "layout": False, "render": False}
        if proj:
            cp = projects.composition_path(proj)
            if cp.exists():
                try:
                    data = json.loads(cp.read_text(encoding="utf-8"))
                    states["plan"] = bool(data.get("rows"))
                except (json.JSONDecodeError, OSError):
                    pass
            states["layout"] = projects.layout_settings_path(proj).exists()
            states["render"] = projects.final_mp4_path(proj).exists()
        all_done = bool(states) and all(states.values())
        any_done = any(states.values())
        for key, widget in self._sub_tabs.items():
            original = self._sub_tab_originals[key]
            done = states.get(key, False)
            try:
                self._sub_nb.tab(widget,
                    text=(f"{original}  ✅" if done else original))
            except tk.TclError:
                pass
        return (all_done, any_done)

    # ── Auto-save dispatcher ────────────────────────────────────────
    def _schedule_silent_save(self, kind: str):
        if self.main._autosave_paused:
            return
        attr = f"_autosave_after_{kind}"
        prev = getattr(self, attr, None)
        if prev:
            try:
                self.after_cancel(prev)
            except tk.TclError:
                pass
        setattr(self, attr,
                self.after(300, lambda k=kind: self._do_silent_save(k)))

    def _do_silent_save(self, kind: str):
        setattr(self, f"_autosave_after_{kind}", None)
        if self.main._autosave_paused or not self.main.current_project:
            return
        try:
            if kind == "layout":
                projects.save_layout_settings(self.main.current_project,
                                               self._collect_layout())
            elif kind == "composition":
                if self._composition:
                    projects.save_composition(self.main.current_project,
                                               self._composition)
            self.main._mark_autosaved()
            self.main._refresh_all_tab_marks()
        except Exception as e:
            from debug_log import DEBUG_LOG
            DEBUG_LOG.log_exception(f"autosave.editing_{kind}", e)

    def _reset_layout(self):
        self._apply_layout_data(cfg.DEFAULT_LAYOUT_SETTINGS)
        self._layout_status_var.set("↩ Layout reset to defaults (not yet saved).")

    # ── RENDER ACTIONS ──────────────────────────────────────────────
    def _cancel_render(self):
        if self._render_thread and self._render_thread.is_alive():
            self._render_cancel.set()
            self._log_render("⏸ Cancel requested.")
        else:
            self._log_render("(nothing running)")

    def _reset_render(self):
        for key in self._render_stage_statuses:
            self._render_stage_statuses[key] = "pending"
            self._render_stage_costs[key] = 0.0
            w = self._render_stage_widgets.get(key)
            if w:
                w["progress"].config(text="—")
            self._refresh_render_stage(key)
        self._refresh_render_total()
        self._log_render("🗑 Statuses reset.")

    def _run_full_render(self):
        if self._render_thread and self._render_thread.is_alive():
            self._log_render("⚠ Pipeline already running.")
            return
        self._render_cancel.clear()
        self._log_render("▶ Starting full render pipeline.")

        def worker():
            for key, _label in cfg.EDITING_PIPELINE_STAGES:
                if self._render_cancel.is_set():
                    self.after(0, lambda: self._log_render("⏸ Cancelled."))
                    return
                if self._render_stage_statuses.get(key) == "done":
                    self.after(0, lambda k=key: self._log_render(f"⏭ {k}: skipped (done)"))
                    self.after(0, lambda k=key: self._set_render_stage(k, status="skipped"))
                    continue
                self._run_render_stage_sync(key)
            self.after(0, lambda: self._log_render("✅ Full render pipeline done."))

        self._render_thread = threading.Thread(target=worker, daemon=True)
        self._render_thread.start()

    def _run_render_stage(self, key: str):
        if self._render_thread and self._render_thread.is_alive():
            self._log_render(f"⚠ Pipeline busy — can't start '{key}'.")
            return
        self._render_cancel.clear()
        self._render_thread = threading.Thread(
            target=lambda: self._run_render_stage_sync(key), daemon=True)
        self._render_thread.start()

    def _run_render_stage_sync(self, key: str):
        try:
            self.after(0, lambda: self._set_render_stage(key, status="in_progress",
                                                          progress="starting…"))
            self.after(0, lambda k=key: self._log_render(f"▶ {k}: starting"))

            # Stub implementations
            if key == "plan":
                for i in range(1, 5):
                    if self._render_cancel.is_set(): raise _RenderCancelled()
                    self.after(0, lambda i=i: self._set_render_stage("plan",
                        progress=f"analysing act {i}/4"))
                    time.sleep(0.35)
                self.after(0, lambda: self._set_render_stage("plan", cost_delta=0.08))
            elif key == "overlays":
                # Cost depends on number of overlay graphics
                total = 12  # placeholder
                for i in range(total):
                    if self._render_cancel.is_set(): raise _RenderCancelled()
                    self.after(0, lambda i=i, t=total: self._set_render_stage("overlays",
                        progress=f"{i+1}/{t}"))
                    time.sleep(0.18)
                    self.after(0, lambda: self._set_render_stage("overlays", cost_delta=0.03))
            elif key == "preview":
                total = 30  # placeholder
                for i in range(total):
                    if self._render_cancel.is_set(): raise _RenderCancelled()
                    self.after(0, lambda i=i, t=total: self._set_render_stage("preview",
                        progress=f"encoding {i+1}/{t}"))
                    time.sleep(0.10)
                if self.main.current_project:
                    p = projects.preview_mp4_path(self.main.current_project)
                    self.after(0, lambda p=p: self._preview_path_var.set(str(p)))
            elif key == "final":
                total = 60  # placeholder
                for i in range(total):
                    if self._render_cancel.is_set(): raise _RenderCancelled()
                    self.after(0, lambda i=i, t=total: self._set_render_stage("final",
                        progress=f"encoding {i+1}/{t}"))
                    time.sleep(0.06)
                if self.main.current_project:
                    p = projects.final_mp4_path(self.main.current_project)
                    self.after(0, lambda p=p: self._final_path_var.set(str(p)))
            else:
                raise ValueError(f"Unknown render stage: {key}")

            self.after(0, lambda k=key: self._set_render_stage(k, status="done",
                                                                 progress="done"))
            self.after(0, lambda k=key: self._log_render(f"✅ {k}: done"))
        except _RenderCancelled:
            self.after(0, lambda k=key: self._set_render_stage(k, status="pending",
                                                                 progress="cancelled"))
            self.after(0, lambda k=key: self._log_render(f"⏸ {k}: cancelled"))
        except Exception as e:
            err = str(e)
            self.after(0, lambda k=key, m=err: self._set_render_stage(k, status="failed",
                                                                       progress="failed"))
            self.after(0, lambda k=key, m=err: self._log_render(f"❌ {k}: {m}"))

    def _open_preview(self):
        if not self.main.current_project:
            return
        path = projects.preview_mp4_path(self.main.current_project)
        if not path.exists():
            messagebox.showinfo("⚠ Not rendered",
                "Preview mp4 hasn't been rendered yet.\n\n"
                "Run stages 1–3 of the render pipeline first.",
                parent=self)
            return
        self._open_with_default_app(path)

    def _open_final(self):
        if not self.main.current_project:
            return
        path = projects.final_mp4_path(self.main.current_project)
        if not path.exists():
            messagebox.showinfo("⚠ Not rendered",
                "Final mp4 hasn't been rendered yet.\n\n"
                "Run the full pipeline first.",
                parent=self)
            return
        self._open_with_default_app(path)

    def _open_with_default_app(self, path):
        import os, sys, subprocess
        try:
            if sys.platform == "win32":
                os.startfile(str(path))
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(path)])
            else:
                subprocess.Popen(["xdg-open", str(path)])
        except Exception as e:
            messagebox.showerror("❌ Open failed", str(e), parent=self)

    # ── EXTERNAL HOOK ───────────────────────────────────────────────
    def apply_editing(self, project_path):
        """Load layout settings + composition plan from disk. Called by MainWindow on project open."""
        # Layout
        layout = projects.load_layout_settings(project_path) if project_path else {}
        if layout and hasattr(self, "layout_pip_pos"):
            self._apply_layout_data(layout)
        # Composition
        self._composition = None
        if project_path:
            data = projects.load_composition(project_path)
            if data:
                self._composition = data
        if hasattr(self, "plan_tree"):
            self._refresh_plan_tree()
        # Render output paths
        if project_path and hasattr(self, "_preview_path_var"):
            preview = projects.preview_mp4_path(project_path)
            final = projects.final_mp4_path(project_path)
            self._preview_path_var.set(str(preview) if preview.exists() else "(not yet rendered)")
            self._final_path_var.set(str(final) if final.exists() else "(not yet rendered)")


class _RenderCancelled(Exception):
    """Raised inside a render stage when Cancel is requested."""
