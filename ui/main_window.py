"""
Main application window with the input form.
"""
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog
from datetime import datetime
from pathlib import Path

import config as cfg
import settings
import presets
import projects
import pricing
from llm_clients import make_client
from prompt_store import STORE as PROMPT_STORE
from pipeline import generate_script, expand_instructions
from ui.widgets import (
    LabeledEntry, LabeledCombobox, LabeledText, SectionFrame,
    Tooltip, HelpIcon, GearButton, ModelPicker, bind_autosave,
)
from ui.settings_dialog import SettingsDialog
from ui.progress_dialog import ProgressDialog
from ui.studio_tab import StudioShootTab
from ui.inserts_tab import BroadcastInsertsTab
from ui.editing_tab import EditingTab
from ui.debug_panel import DebugPanel
from debug_log import DEBUG_LOG


EXPAND_PLACEHOLDER = (
    "Optional. Brief idea — click 'Expand with AI' to develop. "
    "Examples: 'Make heroine a man', 'Add 1990s aesthetic', "
    "'Replace antagonist with government regulator'."
)


class MainWindow(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"{cfg.APP_NAME} v{cfg.APP_VERSION}")
        self.geometry("1000x880")
        self.minsize(900, 700)
        try:
            self.state("zoomed")  # Windows / most Linux WMs: start maximized
        except tk.TclError:
            self.attributes("-zoomed", True)  # fallback for some X11 WMs

        self.settings = settings.load_settings()
        self.current_project: Path | None = None
        self._project_log_listener = None
        # Auto-save plumbing. While True, ALL _schedule_*_autosave calls
        # silently drop. Set True during programmatic apply_* loads.
        self._autosave_paused = False
        self._project_autosave_after_id = None

        # ── Per-kind shared provider/model state ─────────────────────
        # Each ModelPicker binds to these. Persistence is per-(kind, provider)
        # so swapping providers preserves your previous choice on the other side.
        # One-time migration from legacy keys:
        if "openrouter_test_model" in self.settings:
            if self.settings.get("text_model_openrouter") == cfg.DEFAULT_CONFIG["text_model_openrouter"]:
                self.settings["text_model_openrouter"] = self.settings["openrouter_test_model"]
                settings.set_setting("text_model_openrouter",
                                      self.settings["openrouter_test_model"])
        if "openrouter_image_model" in self.settings:
            if self.settings.get("image_model_openrouter") == cfg.DEFAULT_CONFIG["image_model_openrouter"]:
                self.settings["image_model_openrouter"] = self.settings["openrouter_image_model"]
                settings.set_setting("image_model_openrouter",
                                      self.settings["openrouter_image_model"])

        self.text_provider_var = tk.StringVar(value=self.settings.get(
            "text_provider", cfg.DEFAULT_CONFIG["text_provider"]))
        self.text_model_slug_var = tk.StringVar(value=self.settings.get(
            f"text_model_{self.text_provider_var.get()}",
            cfg.DEFAULT_CONFIG.get(f"text_model_{self.text_provider_var.get()}", "")))
        self.image_provider_var = tk.StringVar(value=self.settings.get(
            "image_provider", cfg.DEFAULT_CONFIG["image_provider"]))
        self.image_model_slug_var = tk.StringVar(value=self.settings.get(
            f"image_model_{self._img_provider_key()}",
            cfg.DEFAULT_CONFIG.get(f"image_model_{self._img_provider_key()}", "")))

        def _persist_text_provider(*_):
            settings.set_setting("text_provider", self.text_provider_var.get())
            self._refresh_cost_estimate()
        def _persist_text_model(*_):
            prov = self.text_provider_var.get()
            settings.set_setting(f"text_model_{prov}", self.text_model_slug_var.get())
            self._refresh_cost_estimate()
        def _persist_image_provider(*_):
            settings.set_setting("image_provider", self.image_provider_var.get())
        def _persist_image_model(*_):
            prov_key = self._img_provider_key()
            settings.set_setting(f"image_model_{prov_key}",
                                  self.image_model_slug_var.get())
        self.text_provider_var.trace_add("write", _persist_text_provider)
        self.text_model_slug_var.trace_add("write", _persist_text_model)
        self.image_provider_var.trace_add("write", _persist_image_provider)
        self.image_model_slug_var.trace_add("write", _persist_image_model)
        # Legacy alias still used by _build_client / _refresh_cost_estimate.
        self.model_var = self.text_model_slug_var

        # Route tkinter callback exceptions into the debug log
        self.report_callback_exception = self._log_tk_exception
        # Make Ctrl+V/C/X/A work on non-Latin keyboard layouts (Russian etc.)
        self._install_layout_independent_clipboard_bindings()
        self._build_layout()
        self._refresh_cost_estimate()
        self._refresh_banner()
        # Wire auto-save AFTER the layout is built — needs the widgets to exist.
        self._attach_form_autosave()
        # Initial tab-marks paint
        self._refresh_all_tab_marks()
        # Offer to resume the project that was open at the previous shutdown.
        # Defer so the main window is fully visible before the dialog appears.
        self.after(250, self._maybe_resume_last_project)

    def _img_provider_key(self) -> str:
        """Map image_provider value to its settings key suffix."""
        p = self.image_provider_var.get() if hasattr(self, "image_provider_var") else "openrouter"
        return "kie" if p == "kie.ai" else p

    def _install_layout_independent_clipboard_bindings(self):
        """
        On Windows, Ctrl+V/C/X bind to the keysym 'v'/'c'/'x', which only
        fire on Latin keyboard layouts. On Cyrillic layout pressing Ctrl+М
        produces keysym 'Cyrillic_em' and paste silently fails.

        Workaround: listen to <Key> on Entry / TEntry / Text / TCombobox at
        the class level, gate by the Control modifier (event.state & 0x4),
        and route by physical keycode (86=V, 67=C, 88=X, 65=A) via the
        layout-independent virtual events <<Paste>>, <<Copy>>, <<Cut>>,
        <<SelectAll>>.
        """
        def handler(event):
            if not (event.state & 0x4):
                return None
            kc = event.keycode
            if kc == 86:   # V
                event.widget.event_generate("<<Paste>>")
                return "break"
            if kc == 67:   # C
                event.widget.event_generate("<<Copy>>")
                return "break"
            if kc == 88:   # X
                event.widget.event_generate("<<Cut>>")
                return "break"
            if kc == 65:   # A
                try:
                    event.widget.event_generate("<<SelectAll>>")
                except tk.TclError:
                    pass
                return "break"
            return None

        for cls in ("Entry", "TEntry", "Text", "TCombobox"):
            try:
                self.bind_class(cls, "<Key>", handler, add="+")
            except tk.TclError:
                pass

    def _log_tk_exception(self, exc_type, exc, tb):
        try:
            DEBUG_LOG.log_exception("tk.callback", exc)
        except Exception:
            pass
        import traceback as _tb
        _tb.print_exception(exc_type, exc, tb)

    # ── Auto-save (form fields → project.json) ──────────────────────
    def _attach_form_autosave(self):
        """Wire change-detection on every step-1 form widget. Any edit kicks
        the debounce timer; a project autosave fires 300ms after the user
        stops typing/changing dropdowns."""
        widgets_to_watch = [
            self.show_name, self.host1_name, self.host1_role,
            self.host2_name, self.host2_role, self.duration, self.tone,
            self.country_style, self.dramatic_curve, self.pacing_speed,
            self.language,
            self.niche, self.anchor,
            self.heroine_name, self.heroine_age, self.heroine_location,
            self.heroine_profession, self.heroine_result,
            self.antagonist_type, self.antagonist_arc,
            self.product_name, self.currency, self.anchor_price,
            self.offer_price, self.urgency, self.bonus, self.stock_limit,
            self.extra,
        ]
        widgets_to_watch.extend(self.ingredients)
        widgets_to_watch.extend(self.friend_results_entries)
        for w in widgets_to_watch:
            bind_autosave(w, self._schedule_project_autosave)
        # friend_count_var is a tk.IntVar — autosave on toggle
        bind_autosave(self.friend_count_var, self._schedule_project_autosave)

    def _schedule_project_autosave(self):
        """Debounced (~300ms) — coalesce bursts of keystrokes / combobox clicks
        into a single save."""
        if self._autosave_paused:
            return
        if self._project_autosave_after_id:
            try:
                self.after_cancel(self._project_autosave_after_id)
            except tk.TclError:
                pass
        self._project_autosave_after_id = self.after(300, self._project_autosave)

    def _project_autosave(self):
        """Silent save of the step-1 form into the open project. No popup, no
        version rotation. The banner gets a discreet 💾 indicator."""
        self._project_autosave_after_id = None
        if self._autosave_paused or not self.current_project:
            return
        try:
            projects.save_project(self.current_project, self._collect_form())
            self._mark_autosaved()
            self._refresh_all_tab_marks()
        except Exception as e:
            # Never let auto-save errors crash the UI.
            DEBUG_LOG.log_exception("autosave.project", e)

    def _mark_autosaved(self):
        """Update the discreet '💾 Auto-saved HH:MM:SS' label in the banner."""
        try:
            self.autosave_indicator_var.set(
                f"💾 Auto-saved {datetime.now().strftime('%H:%M:%S')}")
        except (AttributeError, tk.TclError):
            pass

    def _refresh_all_tab_marks(self):
        """Tri-state pipeline rollup: ✅ when ALL actions in a step are
        complete, ⚠ when SOME are complete (partial progress), no mark
        otherwise. Cheap to call — invoked after each save/generation."""
        if not hasattr(self, "_main_nb") or not hasattr(self, "_top_tabs"):
            return
        proj = self.current_project

        # Input data is a single artifact — script.txt — so all/any collapse.
        input_done = bool(proj) and (proj / "script.txt").exists()
        input_state = (input_done, input_done)

        # Sub-modules return (all_done, any_done).
        def _ask(tab_attr):
            tab = getattr(self, tab_attr, None)
            if tab is None:
                return (False, False)
            r = tab.refresh_sub_tab_marks()
            # Tolerate the old bool contract until every module is migrated.
            if isinstance(r, tuple):
                return r
            return (bool(r), bool(r))

        states = {
            "input":   input_state,
            "studio":  _ask("studio_tab"),
            "inserts": _ask("inserts_tab"),
            "edit":    _ask("editing_tab"),
        }
        for key, widget in self._top_tabs.items():
            original = self._top_tab_originals[key]
            all_done, any_done = states[key]
            if all_done:
                text = f"{original}  ✅"
            elif any_done:
                text = f"{original}  ⚠"
            else:
                text = original
            try:
                self._main_nb.tab(widget, text=text)
            except tk.TclError:
                pass

    # ── Project-bound debug log ────────────────────────────────────
    def _attach_project_debug_logger(self):
        """Mirror every DEBUG_LOG entry into <project>/debug.log as JSONL.
        Replaces any previously-registered project listener."""
        # Remove old listener (e.g., if user switches projects)
        if self._project_log_listener is not None:
            DEBUG_LOG.remove_listener(self._project_log_listener)
            self._project_log_listener = None
        if not self.current_project:
            return

        log_path = self.current_project / "debug.log"

        def _write(entry):
            if entry is None:
                return
            try:
                import json as _json
                row = {
                    "timestamp": entry.timestamp,
                    "time":      entry.time_str,
                    "kind":      entry.kind,
                    "name":      entry.name,
                    "details":   entry.details,
                }
                with open(log_path, "a", encoding="utf-8") as f:
                    f.write(_json.dumps(row, ensure_ascii=False, default=str) + "\n")
            except OSError:
                pass

        # Flush whatever is already in memory so the file is complete.
        for e in DEBUG_LOG.entries():
            _write(e)

        DEBUG_LOG.add_listener(_write)
        self._project_log_listener = _write

    # ── LAYOUT ──────────────────────────────────────────────────────
    def _build_layout(self):
        # Create Native Top Menu Bar
        self.menu_bar = tk.Menu(self)
        self.config(menu=self.menu_bar)

        # File Menu
        self.file_menu = tk.Menu(self.menu_bar, tearoff=0)
        self.menu_bar.add_cascade(label="File", menu=self.file_menu)
        self.file_menu.add_command(label="New Project", command=self._new_project)
        self.file_menu.add_command(label="Open Project...", command=self._open_project)
        self.file_menu.add_command(label="Save Project", command=self._save_project)
        self.file_menu.add_separator()
        self.file_menu.add_command(label="Export Project (ZIP)", command=self._export_project_zip)
        self.file_menu.add_separator()
        self.file_menu.add_command(label="Exit", command=self.quit)

        # Presets Menu
        self.presets_menu = tk.Menu(self.menu_bar, tearoff=0)
        self.menu_bar.add_cascade(label="Presets", menu=self.presets_menu)
        self.presets_menu.add_command(label="Load Preset...", command=self._load_preset)
        self.presets_menu.add_command(label="Save Preset...", command=self._save_preset)

        # Tools Menu
        self.tools_menu = tk.Menu(self.menu_bar, tearoff=0)
        self.menu_bar.add_cascade(label="Tools", menu=self.tools_menu)
        self.tools_menu.add_command(label="Settings...", command=self._open_settings)

        # Bottom panel first so it reserves space; tabs fill the rest
        self._build_bottom_panel()

        # Project banner pinned to the top
        self._build_project_banner()

        # Debug panel pinned to the right (collapsible)
        self.debug_panel = DebugPanel(self)
        self.debug_panel.pack(side="right", fill="y")
        ttk.Separator(self, orient="vertical").pack(side="right", fill="y")

        # Top-level pipeline notebook (4 steps)
        main_nb = ttk.Notebook(self, padding=6)
        main_nb.pack(fill="both", expand=True)
        self._main_nb = main_nb

        tab_input = ttk.Frame(main_nb)
        tab_studio = ttk.Frame(main_nb)
        tab_inserts = ttk.Frame(main_nb)
        tab_edit = ttk.Frame(main_nb)

        main_nb.add(tab_input, text="📺 1. Input data")
        main_nb.add(tab_studio, text="🎬 2. Studio shoot")
        main_nb.add(tab_inserts, text="🎞 3. Broadcast inserts")
        main_nb.add(tab_edit, text="✂ 4. Editing")

        # Track top-level tabs for ✅-on-complete marks
        self._top_tabs = {
            "input": tab_input, "studio": tab_studio,
            "inserts": tab_inserts, "edit": tab_edit,
        }
        self._top_tab_originals = {
            "input": "📺 1. Input data",
            "studio": "🎬 2. Studio shoot",
            "inserts": "🎞 3. Broadcast inserts",
            "edit": "✂ 4. Editing",
        }

        # Bottom action row — text-model picker + 🎬 Generate + ⚙
        # (placed first with side="bottom" so it reserves space; the inner
        # notebook then fills the rest above it).
        action_row = ttk.Frame(tab_input, padding=(8, 6, 8, 8))
        action_row.pack(side="bottom", fill="x")
        ModelPicker(action_row, kind="text", main_window=self,
                     label_text="Text model:").pack(side="left")
        gen_btn = ttk.Button(action_row, text="🎬 Generate",
                              command=self._on_generate)
        gen_btn.pack(side="left", padx=(8, 2))
        Tooltip(gen_btn,
            "Run the 4-act script generator. Auto-saves into the open project; "
            "otherwise prompts Save As.")
        ttk.Button(action_row, text="⚙", width=3,
                    command=self._open_generate_prompt_picker).pack(side="left")
        Tooltip(action_row.winfo_children()[-1],
            "Tune one of the prompts used by 🎬 Generate: base system persona, "
            "the shared context block, or any of the 4 act prompts.")

        # Step 1 contents: sub-notebook with the form sections
        sub_nb = ttk.Notebook(tab_input, padding=8)
        sub_nb.pack(fill="both", expand=True)

        tab_show = ttk.Frame(sub_nb, padding=14)
        tab_theme = ttk.Frame(sub_nb, padding=14)
        tab_cast = ttk.Frame(sub_nb, padding=14)
        tab_offer = ttk.Frame(sub_nb, padding=14)
        tab_extra = ttk.Frame(sub_nb, padding=14)

        sub_nb.add(tab_show, text="📺 Show")
        sub_nb.add(tab_theme, text="🎯 Theme")
        sub_nb.add(tab_cast, text="🎭 Cast")
        sub_nb.add(tab_offer, text="💰 Offer")
        sub_nb.add(tab_extra, text="📝 Instructions")

        self._build_show_block(tab_show)
        self._build_theme_block(tab_theme)
        self._build_heroine_block(tab_cast)
        self._build_antagonist_block(tab_cast)
        self._build_offer_block(tab_offer)
        self._build_extra_block(tab_extra)

        # Step 2 — Studio shoot (real sub-notebook; first sub-tab is Logo & Brand)
        self.studio_tab = StudioShootTab(tab_studio, self)
        self.studio_tab.pack(fill="both", expand=True)

        # Step 3 — Broadcast inserts (raw asset library)
        self.inserts_tab = BroadcastInsertsTab(tab_inserts, self)
        self.inserts_tab.pack(fill="both", expand=True)

        # Step 4 — Editing & Assembly (composition plan + layout + ffmpeg render)
        self.editing_tab = EditingTab(tab_edit, self)
        self.editing_tab.pack(fill="both", expand=True)

    # ── STUB TAB ────────────────────────────────────────────────────
    def _build_stub_tab(self, parent, title: str, subtitle: str, footer: str):
        wrap = ttk.Frame(parent, padding=40)
        wrap.pack(expand=True)
        ttk.Label(wrap, text=title, font=("", 20, "bold")).pack(pady=(40, 10))
        ttk.Label(wrap, text=subtitle, foreground="#333",
                  wraplength=640, justify="center",
                  font=("", 11)).pack(pady=(0, 28))
        ttk.Label(wrap, text="🚧  Under construction  🚧",
                  foreground="#a0660b",
                  font=("", 11, "bold")).pack(pady=(0, 12))
        ttk.Label(wrap, text=footer, foreground="grey",
                  wraplength=640, justify="center").pack()

    # ── PROJECT BANNER ──────────────────────────────────────────────
    def _build_project_banner(self):
        banner = ttk.Frame(self, padding=(14, 6, 14, 6))
        banner.pack(side="top", fill="x")

        self.banner_name_var = tk.StringVar()
        ttk.Label(banner, textvariable=self.banner_name_var,
                  font=("", 10, "bold")).pack(side="left")

        self.banner_status_var = tk.StringVar()
        ttk.Label(banner, textvariable=self.banner_status_var,
                  foreground="grey").pack(side="right")

        # Auto-save indicator (right side, between project name and step status)
        self.autosave_indicator_var = tk.StringVar(value="")
        ttk.Label(banner, textvariable=self.autosave_indicator_var,
                  foreground="#3a7d3a", font=("", 9)).pack(side="right", padx=(0, 12))

        ttk.Separator(self, orient="horizontal").pack(side="top", fill="x")

    def _refresh_banner(self):
        if self.current_project:
            self.banner_name_var.set(f"📁 {self.current_project.name}")
            st = projects.get_step_statuses(self.current_project)
            icons = {"pending": "⏸", "in_progress": "▶", "done": "✅", "failed": "❌"}
            self.banner_status_var.set(
                f"📺 {icons.get(st.get('script'), '⏸')} Script"
                f"   🎬 {icons.get(st.get('studio'), '⏸')} Studio"
                f"   🎞 {icons.get(st.get('inserts'), '⏸')} Inserts"
                f"   ✂ {icons.get(st.get('edit'), '⏸')} Edit"
            )
        else:
            self.banner_name_var.set("📁 No project loaded")
            self.banner_status_var.set("💾 Save project to track multi-step pipeline")
        self._update_title()

    def _update_title(self):
        base = f"{cfg.APP_NAME} v{cfg.APP_VERSION}"
        if self.current_project:
            self.title(f"{base} — {self.current_project.name}")
        else:
            self.title(base)

    # ── BLOCKS ──────────────────────────────────────────────────────
    def _build_show_block(self, parent):
        f = SectionFrame(parent, "📺 Show metadata")
        f.pack(fill="x", pady=(0, 10))
        grid = ttk.Frame(f); grid.pack(fill="x")
        for col in range(4):
            grid.columnconfigure(col, weight=1)

        self.show_name = LabeledEntry(grid, "Show name", "Open Talk",
            help_text="On-screen title of the talk show. Appears in intro graphics and lower thirds.")
        self.show_name.grid(row=0, column=0, sticky="ew", padx=(0, 8), pady=4)

        self.host1_name = LabeledEntry(grid, "Host 1 name", "Andrew Cornell",
            help_text="Full name of the first host. Two-host format pairs a skeptic with an empathetic anchor.")
        self.host1_name.grid(row=0, column=1, sticky="ew", padx=(0, 8), pady=4)

        self.host1_role = LabeledCombobox(grid, "Host 1 role",
                                          ["skeptic", "empathetic"], "skeptic",
            help_text="skeptic — challenges claims and pushes back. empathetic — supports guests and validates emotion.")
        self.host1_role.grid(row=0, column=2, sticky="ew", padx=(0, 8), pady=4)

        self.host2_name = LabeledEntry(grid, "Host 2 name", "Olivia Vance",
            help_text="Full name of the second host. Opposite role to Host 1 for on-air chemistry.")
        self.host2_name.grid(row=1, column=1, sticky="ew", padx=(0, 8), pady=4)

        self.host2_role = LabeledCombobox(grid, "Host 2 role",
                                          ["empathetic", "skeptic"], "empathetic",
            help_text="Counterpart to Host 1 role — keeps the conflict/balance dynamic.")
        self.host2_role.grid(row=1, column=2, sticky="ew", padx=(0, 8), pady=4)

        self.duration = LabeledCombobox(grid, "Duration (min)",
                                        [str(d) for d in cfg.DURATION_OPTIONS], "45",
            help_text="Target total runtime. Drives word count per act (≈150 words/minute of read dialogue).")
        self.duration.grid(row=2, column=0, sticky="ew", padx=(0, 8), pady=4)
        self.duration.combo.bind("<<ComboboxSelected>>", lambda e: self._refresh_cost_estimate())

        self.tone = LabeledCombobox(grid, "Tone", cfg.TONE_OPTIONS,
                                    cfg.TONE_OPTIONS[0],
            help_text="Stylistic register. Determines vocabulary, pacing, and the cliché set the LLM draws from.")
        self.tone.grid(row=2, column=1, columnspan=2, sticky="ew", padx=(0, 8), pady=4)

        self.language = LabeledCombobox(grid, "Language", cfg.LANGUAGE_OPTIONS, "English",
            help_text="Language of generated dialogue and stage directions.")
        self.language.grid(row=2, column=3, sticky="ew", pady=4)

        # Row 3 for Country style, Dramatic curve and Pacing speed
        self.country_style = LabeledCombobox(grid, "Country style preset",
            ["US (Daytime Oprah / Dr. Phil style)",
             "Russian (Malakhov / Pust Govoryat style)",
             "UK (Morning show style)",
             "Latin America (Sensational Soap-Opera style)"],
            "US (Daytime Oprah / Dr. Phil style)",
            help_text="Country style dictates regional show formatting, cultural cliches, and local naming/referencing patterns.")
        self.country_style.grid(row=3, column=0, sticky="ew", padx=(0, 8), pady=4)

        self.dramatic_curve = LabeledCombobox(grid, "Dramatic curve",
            ["Standard Infomercial (Pain -> Discovery -> Proof -> Close)",
             "High Drama (Scandal -> Confrontation -> Emotional Breakdown -> Hope)",
             "Scientific Expo (Skepticism -> Proof -> Mass Conversion -> Altruistic Gift)",
             "Conspiratorial Expose (Cover-up -> Whistleblower -> Threat -> Direct Offer)"],
            "Standard Infomercial (Pain -> Discovery -> Proof -> Close)",
            help_text="Selects the structural narrative template and emotional pacing trajectory of the script.")
        self.dramatic_curve.grid(row=3, column=1, columnspan=2, sticky="ew", padx=(0, 8), pady=4)

        self.pacing_speed = LabeledCombobox(grid, "Pacing / Intensity",
            ["Normal (conversational and standard TV cadence)",
             "Fast (highly editing-intensive, rapid dialogue transitions)",
             "Dramatic (extended pauses, heavy emotional beats)"],
            "Normal (conversational and standard TV cadence)",
            help_text="Controls conversational cadences, silence injection frequency, and edit densities.")
        self.pacing_speed.grid(row=3, column=3, sticky="ew", pady=4)

    def _build_theme_block(self, parent):
        f = SectionFrame(parent, "🎯 Theme")
        f.pack(fill="x", pady=(0, 10))
        grid = ttk.Frame(f); grid.pack(fill="x")
        for col in range(3):
            grid.columnconfigure(col, weight=1)

        self.niche = LabeledCombobox(grid, "Niche / pain point",
                                     cfg.NICHE_OPTIONS, "Weight loss", readonly=False,
            help_text="The problem area the show pretends to address. Drives heroine backstory, antagonist industry, and product positioning.")
        self.niche.grid(row=0, column=0, sticky="ew", padx=(0, 8), pady=4)

        self.anchor = LabeledCombobox(grid, "Scientific anchor (real term)",
                                      cfg.ANCHOR_SUGGESTIONS,
                                      cfg.ANCHOR_SUGGESTIONS[0], readonly=False, width=40,
            help_text="A real biological mechanism. The LLM riffs on it to invent pseudo-scientific claims and the product hook.")
        self.anchor.grid(row=0, column=1, columnspan=2, sticky="ew", pady=4)

        ing_label_row = ttk.Frame(f); ing_label_row.pack(anchor="w", fill="x", pady=(10, 4))
        ttk.Label(ing_label_row, text="Folk ingredients (recipe)").pack(side="left")
        HelpIcon(ing_label_row,
            "Folk / kitchen-table items the heroine claims worked in her supposed 'home recipe' that led to her transformation.").pack(side="left")

        ing_row = ttk.Frame(f); ing_row.pack(fill="x")
        defaults = ["apple cider vinegar", "lemon", "baking soda"]
        self.ingredients = []
        for i, d in enumerate(defaults):
            e = LabeledEntry(ing_row, f"Ingredient {i+1}", d, width=20,
                help_text=f"Recipe ingredient #{i+1}. Mundane / cheap items feel more authentic in testimonial framing.")
            e.pack(side="left", fill="x", expand=True, padx=(0, 8 if i < 2 else 0))
            self.ingredients.append(e)

    def _build_heroine_block(self, parent):
        f = SectionFrame(parent, "✨ Heroine")
        f.pack(fill="x", pady=(0, 10))

        grid = ttk.Frame(f); grid.pack(fill="x")
        for col in range(4):
            grid.columnconfigure(col, weight=1)

        self.heroine_name = LabeledEntry(grid, "Name", "Marina Kravchenko",
            help_text="Full name of the central testimonial guest. Specific names sell fake credibility.")
        self.heroine_name.grid(row=0, column=0, sticky="ew", padx=(0, 8), pady=4)

        self.heroine_age = LabeledEntry(grid, "Age", "46", width=6,
            help_text="Age displayed in lower thirds when she is introduced.")
        self.heroine_age.grid(row=0, column=1, sticky="ew", padx=(0, 8), pady=4)

        self.heroine_location = LabeledEntry(grid, "Location", "Cleveland, Ohio",
            help_text="City + state/country. Relatable hometown anchoring.")
        self.heroine_location.grid(row=0, column=2, sticky="ew", padx=(0, 8), pady=4)

        self.heroine_profession = LabeledEntry(grid, "Profession", "bookkeeper, mother of two",
            help_text="Day job + family role. Frames her as 'an ordinary person like you'.")
        self.heroine_profession.grid(row=0, column=3, sticky="ew", pady=4)

        self.heroine_result = LabeledEntry(grid, "Headline result",
                                           "lost 27 kg / 60 lbs in 5 months",
            help_text="Dramatic outcome stated as a one-liner. Repeated throughout the show.")
        self.heroine_result.grid(row=1, column=0, columnspan=4, sticky="ew", pady=4)

        # Friends
        friends_row = ttk.Frame(f); friends_row.pack(fill="x", pady=(10, 0))
        ttk.Label(friends_row, text="👯 Friends on stage:").pack(side="left", padx=(0, 4))
        HelpIcon(friends_row,
            "Supporting testimonials on stage. Each echoes the main result with variation. Choose 2 or 3.").pack(side="left", padx=(0, 10))
        self.friend_count_var = tk.IntVar(value=2)
        rb2 = ttk.Radiobutton(friends_row, text="2", variable=self.friend_count_var,
                              value=2, command=self._refresh_friend_fields)
        rb2.pack(side="left")
        Tooltip(rb2, "Two supporting testimonials on stage. Tighter pacing, more focus on the heroine.")
        rb3 = ttk.Radiobutton(friends_row, text="3", variable=self.friend_count_var,
                              value=3, command=self._refresh_friend_fields)
        rb3.pack(side="left", padx=(8, 0))
        Tooltip(rb3, "Three supporting testimonials. Adds variety but stretches Act 2.")

        self.friend_results_frame = ttk.Frame(f)
        self.friend_results_frame.pack(fill="x", pady=(8, 0))
        self.friend_results_entries = []
        self._refresh_friend_fields()

    def _refresh_friend_fields(self):
        for w in self.friend_results_frame.winfo_children():
            w.destroy()
        self.friend_results_entries = []
        count = self.friend_count_var.get()
        defaults = [
            "Svetlana, 41, banking — lost 18 kg / 40 lbs",
            "Elena, 39, marketing — lost 22 kg / 48 lbs",
            "Patricia, 52, teacher — lost 15 kg / 33 lbs",
        ]
        for i in range(count):
            e = LabeledEntry(self.friend_results_frame, f"Friend {i+1}",
                             defaults[i] if i < len(defaults) else "", width=50,
                help_text=f"Friend #{i+1}: name + age + profession + outcome, all on one line. Becomes a supporting testimonial.")
            e.pack(side="left", fill="x", expand=True, padx=(0, 8 if i < count - 1 else 0))
            self.friend_results_entries.append(e)
            # Auto-save on edit (works for entries added after _attach_form_autosave)
            if hasattr(self, "_project_autosave_after_id"):
                bind_autosave(e, self._schedule_project_autosave)

    def _build_antagonist_block(self, parent):
        f = SectionFrame(parent, "🦹 Antagonist")
        f.pack(fill="x", pady=(0, 10))
        grid = ttk.Frame(f); grid.pack(fill="x")
        grid.columnconfigure(0, weight=1); grid.columnconfigure(1, weight=1)

        self.antagonist_type = LabeledCombobox(grid, "Antagonist type",
                                               cfg.ANTAGONIST_TYPES,
                                               cfg.ANTAGONIST_TYPES[0],
            help_text="Industry foe the show frames as 'hiding the truth'. Drives the conflict arc in Act 3.")
        self.antagonist_type.grid(row=0, column=0, sticky="ew", padx=(0, 8), pady=4)

        self.antagonist_arc = LabeledCombobox(grid, "Emotional arc",
                                              cfg.ANTAGONIST_ARCS,
                                              cfg.ANTAGONIST_ARCS[0],
            help_text="Emotional trajectory of the antagonist through Act 3 — from composed to defeated.")
        self.antagonist_arc.grid(row=0, column=1, sticky="ew", pady=4)

    def _build_offer_block(self, parent):
        f = SectionFrame(parent, "💰 Product & offer")
        f.pack(fill="x", pady=(0, 10))
        grid = ttk.Frame(f); grid.pack(fill="x")
        for col in range(4):
            grid.columnconfigure(col, weight=1)

        prod_row = ttk.Frame(grid); prod_row.grid(row=0, column=0, columnspan=4, sticky="ew", pady=4)
        self.product_name = LabeledEntry(prod_row, "Product name", "GLP-Activ", width=30,
            help_text="Final retail name of the supplement / device. Often pseudo-scientific. Click '✨ Generate' to riff one off your scientific anchor.")
        self.product_name.pack(side="left", fill="x", expand=True)
        ai_name_btn = ttk.Button(prod_row, text="✨ Generate with AI", width=18,
                                  command=self._ai_generate_product_name)
        ai_name_btn.pack(side="left", padx=(8, 0), pady=(18, 0))
        Tooltip(ai_name_btn,
            "Generate a pseudo-scientific product name from the scientific anchor and niche. "
            "Requires a 'Scientific anchor' value above.")
        GearButton(prod_row, "product_name", main_window=self).pack(
            side="left", padx=(2, 0), pady=(18, 0))

        self.currency = LabeledCombobox(grid, "Currency", cfg.CURRENCY_OPTIONS, "$", width=5,
            help_text="Symbol shown in all on-screen price call-outs.")
        self.currency.grid(row=1, column=0, sticky="ew", padx=(0, 8), pady=4)

        self.anchor_price = LabeledEntry(grid, "Anchor price (retail)", "99", width=10,
            help_text="Inflated 'retail value' shown crossed-out. Makes the offer feel like a discount.")
        self.anchor_price.grid(row=1, column=1, sticky="ew", padx=(0, 8), pady=4)

        self.offer_price = LabeledEntry(grid, "Offer price (today)", "39", width=10,
            help_text="The 'today only' price actually pitched to viewers in Act 4.")
        self.offer_price.grid(row=1, column=2, sticky="ew", padx=(0, 8), pady=4)

        self.urgency = LabeledEntry(grid, "Urgency window", "48 hours", width=15,
            help_text="Time-limited claim (e.g., '48 hours', 'until midnight'). Drives the Act 4 close.")
        self.urgency.grid(row=1, column=3, sticky="ew", pady=4)

        self.bonus = LabeledCombobox(grid, "Bonus", cfg.BONUS_TYPES, cfg.BONUS_TYPES[0],
            help_text="Extra sweetener layered on the offer to inflate perceived value.")
        self.bonus.grid(row=2, column=0, columnspan=2, sticky="ew", padx=(0, 8), pady=4)

        self.stock_limit = LabeledEntry(grid, "Stock limit (counter cap)", "8000", width=10,
            help_text="Counter cap shown on screen for fake scarcity (e.g., 'only 247 left').")
        self.stock_limit.grid(row=2, column=2, sticky="ew", padx=(0, 8), pady=4)

    def _build_extra_block(self, parent):
        f = SectionFrame(parent, "📝 Additional instructions (optional)")
        f.pack(fill="x", pady=(0, 10))

        row = ttk.Frame(f); row.pack(fill="both", expand=True)
        self.extra = LabeledText(row, "", height=4, width=80,
                                 placeholder=EXPAND_PLACEHOLDER,
            help_text="Optional notes that override or extend the default direction (e.g., 'make heroine a man', 'add 1990s aesthetic'). Click ✨ Expand to develop into directives.")
        self.extra.pack(side="left", fill="both", expand=True)

        btn_col = ttk.Frame(row); btn_col.pack(side="left", padx=(8, 0))
        expand_row = ttk.Frame(btn_col); expand_row.pack(pady=(0, 4), fill="x")
        expand_btn = ttk.Button(expand_row, text="✨ Expand with AI", width=18,
                                 command=self._ai_expand_extra)
        expand_btn.pack(side="left")
        Tooltip(expand_btn,
            "Take your brief note and develop it into detailed creative directives the 4-act generator will follow. Costs a small extra LLM call.")
        GearButton(expand_row, "expand_system", main_window=self).pack(side="left", padx=(2, 0))

        reset_btn = ttk.Button(btn_col, text="↩ Reset", width=18,
                                command=self._reset_extra)
        reset_btn.pack(pady=(0, 4))
        Tooltip(reset_btn, "Reset additional instructions to empty (same as Clear, kept for parity).")

        clear_btn = ttk.Button(btn_col, text="🧹 Clear", width=18,
                                command=lambda: self.extra.set(""))
        clear_btn.pack()
        Tooltip(clear_btn, "Empty the additional instructions field immediately.")

    def _reset_extra(self):
        self.extra.set("")

    def _build_bottom_panel(self):
        panel = ttk.Frame(self, padding=(14, 10, 14, 14), relief="raised")
        panel.pack(side="bottom", fill="x")

        # The bottom panel keeps only the cost-estimate line
        self.cost_var = tk.StringVar(value="Estimated cost: ...")
        ttk.Label(panel, textvariable=self.cost_var, foreground="grey").pack(
            anchor="w")

    # ── COST ESTIMATE ───────────────────────────────────────────────
    def _refresh_cost_estimate(self):
        provider = self.text_provider_var.get()
        model = self.text_model_slug_var.get()
        try:
            duration = int(self.duration.get())
        except (ValueError, AttributeError):
            duration = 45
        if provider == "ollama":
            self.cost_var.set("Estimated cost: $0.00 (Ollama runs locally)")
            return
        est = pricing.estimate_script_cost(model, duration, include_expand=False)
        total_fmt = pricing.format_cost(est["total_usd"])
        unknown = pricing.get_pricing(model) == (0.0, 0.0)
        if unknown:
            self.cost_var.set(f"Estimated cost: unknown (model '{model}' not in price table)")
        else:
            self.cost_var.set(
                f"Estimated cost: ~{total_fmt} (4 act calls; expand step adds ~$0.01–$0.05)"
            )

    # ── AI HELPERS ──────────────────────────────────────────────────
    def _build_client(self):
        provider = self.text_provider_var.get()
        model = self.text_model_slug_var.get()
        self.settings = settings.load_settings()
        return make_client(provider, self.settings, model)

    def _ai_expand_extra(self):
        note = self.extra.get().strip()
        if not note:
            messagebox.showinfo("✨ Expand", "Type a brief idea first, then click Expand.")
            return

        def worker():
            try:
                client = self._build_client()
                expanded = expand_instructions(client, note)
                self.after(0, lambda: self._set_expanded(expanded))
            except Exception as e:
                err = str(e)
                self.after(0, lambda: messagebox.showerror("❌ Expand failed", err))

        threading.Thread(target=worker, daemon=True).start()
        self.cost_var.set("Calling AI to expand instructions...")

    def _set_expanded(self, text):
        if text:
            self.extra.set(text)
        self._refresh_cost_estimate()

    def _ai_generate_product_name(self):
        anchor = self.anchor.get().strip()
        niche = self.niche.get().strip()
        if not anchor:
            messagebox.showinfo("✨ Generate name",
                                "Fill in 'Scientific anchor' first so the name can riff on it.")
            return

        def worker():
            try:
                client = self._build_client()
                prompt = PROMPT_STORE.render("product_name",
                                              anchor=anchor, niche=niche)
                name = client.complete(
                    system="You generate semi-scientific product names. Output one short name only.",
                    user=prompt, max_tokens=30, temperature=0.9
                ).strip().split("\n")[0].strip(' "\'.,;:')
                self.after(0, lambda: self.product_name.set(name))
            except Exception as e:
                err = str(e)
                self.after(0, lambda: messagebox.showerror("❌ Generation failed", err))

        threading.Thread(target=worker, daemon=True).start()

    # ── PRESETS ─────────────────────────────────────────────────────
    def _collect_form(self) -> dict:
        return {
            "show_name": self.show_name.get(),
            "host1_name": self.host1_name.get(),
            "host1_role": self.host1_role.get(),
            "host2_name": self.host2_name.get(),
            "host2_role": self.host2_role.get(),
            "duration": int(self.duration.get()) if self.duration.get().isdigit() else 45,
            "tone": self.tone.get(),
            "country_style": self.country_style.get(),
            "dramatic_curve": self.dramatic_curve.get(),
            "pacing_speed": self.pacing_speed.get(),
            "language": self.language.get(),
            "niche": self.niche.get(),
            "anchor": self.anchor.get(),
            "ingredients": [e.get() for e in self.ingredients],
            "heroine_name": self.heroine_name.get(),
            "heroine_age": self.heroine_age.get(),
            "heroine_location": self.heroine_location.get(),
            "heroine_profession": self.heroine_profession.get(),
            "heroine_result": self.heroine_result.get(),
            "friend_count": self.friend_count_var.get(),
            "friend_results": [e.get() for e in self.friend_results_entries],
            "antagonist_type": self.antagonist_type.get(),
            "antagonist_arc": self.antagonist_arc.get(),
            "product_name": self.product_name.get(),
            "currency": self.currency.get(),
            "anchor_price": self.anchor_price.get(),
            "offer_price": self.offer_price.get(),
            "bonus": self.bonus.get(),
            "urgency": self.urgency.get(),
            "stock_limit": self.stock_limit.get(),
            "extra_instructions": self.extra.get(),
        }

    def _apply_form(self, data: dict):
        def s(widget, key, default=""):
            try:
                widget.set(data.get(key, default))
            except Exception:
                pass

        s(self.show_name, "show_name")
        s(self.host1_name, "host1_name")
        s(self.host1_role, "host1_role")
        s(self.host2_name, "host2_name")
        s(self.host2_role, "host2_role")
        s(self.duration, "duration", "45")
        s(self.tone, "tone")
        s(self.country_style, "country_style", "US (Daytime Oprah / Dr. Phil style)")
        s(self.dramatic_curve, "dramatic_curve", "Standard Infomercial (Pain -> Discovery -> Proof -> Close)")
        s(self.pacing_speed, "pacing_speed", "Normal (conversational and standard TV cadence)")
        s(self.language, "language")
        s(self.niche, "niche")
        s(self.anchor, "anchor")

        ings = data.get("ingredients", [])
        for i, w in enumerate(self.ingredients):
            w.set(ings[i] if i < len(ings) else "")

        s(self.heroine_name, "heroine_name")
        s(self.heroine_age, "heroine_age")
        s(self.heroine_location, "heroine_location")
        s(self.heroine_profession, "heroine_profession")
        s(self.heroine_result, "heroine_result")

        self.friend_count_var.set(data.get("friend_count", 2))
        self._refresh_friend_fields()
        frs = data.get("friend_results", [])
        for i, w in enumerate(self.friend_results_entries):
            w.set(frs[i] if i < len(frs) else "")

        s(self.antagonist_type, "antagonist_type")
        s(self.antagonist_arc, "antagonist_arc")
        s(self.product_name, "product_name")
        s(self.currency, "currency")
        s(self.anchor_price, "anchor_price")
        s(self.offer_price, "offer_price")
        s(self.bonus, "bonus")
        s(self.urgency, "urgency")
        s(self.stock_limit, "stock_limit")
        s(self.extra, "extra_instructions")
        self._refresh_cost_estimate()

    def _save_preset(self):
        name = simpledialog.askstring("💾 Save preset", "Preset name:", parent=self)
        if not name:
            return
        path = presets.save_preset(name, self._collect_form())
        messagebox.showinfo("✅ Saved", f"Preset saved to:\n{path}")

    def _load_preset(self):
        items = presets.list_presets()
        if not items:
            messagebox.showinfo("📂 Load preset", "No presets saved yet.")
            return
        dlg = _PresetPicker(self, items)
        self.wait_window(dlg)
        if dlg.chosen_path:
            form = presets.load_preset(dlg.chosen_path)
            self._autosave_paused = True
            try:
                self._apply_form(form)
            finally:
                self._autosave_paused = False

    # ── PROJECTS ────────────────────────────────────────────────────
    def _suggest_project_name(self, form: dict) -> str:
        """date - show - duration - niche - offer  (used as initial value
        in the Save project dialog)."""
        parts = [
            datetime.now().strftime("%Y-%m-%d"),
            (form.get("show_name") or "Open Talk").strip(),
            f"{form.get('duration', 45)}min",
            (form.get("niche") or "Weight loss").strip(),
            (form.get("product_name") or "GLP-Activ").strip(),
        ]
        return " - ".join(p for p in parts if p)

    def _save_project(self):
        form = self._collect_form()
        if self.current_project:
            projects.save_project(self.current_project, form)
            self._persist_last_project_path()
            messagebox.showinfo("✅ Saved",
                                f"Project updated:\n{self.current_project}")
            self._refresh_banner()
            return
        suggested = self._suggest_project_name(form)
        name = simpledialog.askstring("💾 Save project", "Project name:",
                                       parent=self, initialvalue=suggested)
        if not name:
            return
        path = projects.create_project(name, form)
        self.current_project = path
        self._attach_project_debug_logger()
        self._refresh_banner()
        self._refresh_all_tab_marks()
        self._persist_last_project_path()
        messagebox.showinfo("✅ Created", f"Project created:\n{path}")

    def _new_project(self):
        if self.current_project:
            if not messagebox.askyesno(
                "New Project",
                "Close the current project and start a new one?\n(Your changes are automatically saved to project.json)",
                parent=self
            ):
                return

        self._autosave_paused = True
        try:
            default_data = {
                "show_name": "Open Talk",
                "host1_name": "Andrew Cornell",
                "host1_role": "skeptic",
                "host2_name": "Olivia Vance",
                "host2_role": "empathetic",
                "duration": "45",
                "tone": cfg.TONE_OPTIONS[0] if cfg.TONE_OPTIONS else "Sensational",
                "country_style": "US (Daytime Oprah / Dr. Phil style)",
                "dramatic_curve": "Standard Infomercial (Pain -> Discovery -> Proof -> Close)",
                "pacing_speed": "Normal (conversational and standard TV cadence)",
                "language": "English",
                "niche": "Weight loss",
                "anchor": cfg.ANCHOR_SUGGESTIONS[0] if cfg.ANCHOR_SUGGESTIONS else "",
                "ingredients": ["apple cider vinegar", "lemon", "baking soda"],
                "heroine_name": "Marina Kravchenko",
                "heroine_age": "46",
                "heroine_location": "Cleveland, Ohio",
                "heroine_profession": "bookkeeper, mother of two",
                "heroine_result": "lost 27 kg / 60 lbs in 5 months",
                "friend_count": 2,
                "friend_results": [
                    "Svetlana, 41, banking — lost 18 kg / 40 lbs",
                    "Elena, 39, marketing — lost 22 kg / 48 lbs"
                ],
                "antagonist_type": cfg.ANTAGONIST_TYPES[0] if cfg.ANTAGONIST_TYPES else "Pharmaceutical Lobby",
                "antagonist_arc": cfg.ANTAGONIST_ARCS[0] if cfg.ANTAGONIST_ARCS else "Arrogant Skepticism to Tearful Confession",
                "product_name": "GLP-Activ",
                "currency": "$",
                "anchor_price": "99",
                "offer_price": "39",
                "bonus": cfg.BONUS_TYPES[0] if cfg.BONUS_TYPES else "Free Express Shipping",
                "urgency": "48 hours",
                "stock_limit": "8000",
                "extra_instructions": ""
            }
            self._apply_form(default_data)

            self.current_project = None
            if self._project_log_listener is not None:
                DEBUG_LOG.remove_listener(self._project_log_listener)
                self._project_log_listener = None

            if hasattr(self, "studio_tab"):
                self.studio_tab.apply_brand({})
                self.studio_tab.apply_studio({})
                self.studio_tab.apply_audience({})
                self.studio_tab.apply_characters(None)
                self.studio_tab.apply_voices(None)
                self.studio_tab.apply_storyboard(None)
                self.studio_tab.apply_camera_plan({})
                self.studio_tab.apply_talking_heads(None)
                self.studio_tab.apply_timeline(None)
            if hasattr(self, "inserts_tab"):
                self.inserts_tab.apply_inserts(None)
            if hasattr(self, "editing_tab"):
                self.editing_tab.apply_editing(None)
        finally:
            self._autosave_paused = False

        self._refresh_all_tab_marks()
        self._refresh_banner()

    def _export_project_zip(self):
        if not self.current_project:
            messagebox.showwarning("⚠ No project", "Please save or open a project first.")
            return

        suggested = f"{self.current_project.name}.zip"
        path = filedialog.asksaveasfilename(
            parent=self,
            title="Export Project (ZIP)",
            defaultextension=".zip",
            initialfile=suggested,
            filetypes=[("ZIP archives", "*.zip"), ("All files", "*.*")]
        )
        if not path:
            return

        def worker():
            try:
                self.cost_var.set("Exporting project to ZIP...")
                output_zip = Path(path)
                projects.export_project_zip(self.current_project, output_zip)
                self.after(0, lambda: messagebox.showinfo("✅ Exported", f"Project successfully exported to:\n{path}"))
            except Exception as e:
                self.after(0, lambda: messagebox.showerror("❌ Export failed", str(e)))
            finally:
                self.after(0, self._refresh_cost_estimate)

        threading.Thread(target=worker, daemon=True).start()

    def _open_project(self):
        items = projects.list_projects()
        if not items:
            messagebox.showinfo("📂 Open project",
                                "No projects yet. Use 💾 Save project to create one.")
            return
        dlg = _ProjectPicker(self, items)
        self.wait_window(dlg)
        if dlg.chosen_path:
            self._load_project_from_path(dlg.chosen_path)

    def _load_project_from_path(self, path: Path) -> bool:
        """Apply a project at `path` to all UI state. Shared by the
        ProjectPicker dialog (manual open) and the startup resume flow.
        Returns True on success, False if the path can't be loaded."""
        if not path:
            return False
        try:
            data = projects.load_project(path)
        except Exception as e:
            messagebox.showerror("❌ Load failed",
                f"Could not load project at:\n{path}\n\n{e}", parent=self)
            return False
        # Pause auto-save across the ENTIRE programmatic load so traces that
        # fire during apply_* don't echo back to disk.
        self._autosave_paused = True
        try:
            self._apply_form(data.get("form", {}))
            self.current_project = path
            self._attach_project_debug_logger()
            if hasattr(self, "studio_tab"):
                brand = projects.load_brand(path)
                if brand:
                    self.studio_tab.apply_brand(brand)
                studio = projects.load_studio(path)
                if studio:
                    self.studio_tab.apply_studio(studio)
                audience = projects.load_audience(path)
                if audience:
                    self.studio_tab.apply_audience(audience)
                self.studio_tab.apply_characters(path)
                self.studio_tab.apply_voices(path)
                self.studio_tab.apply_storyboard(path)
                cam_plan = projects.load_camera_plan(path)
                if cam_plan:
                    self.studio_tab.apply_camera_plan(cam_plan)
                self.studio_tab.apply_talking_heads(path)
                self.studio_tab.apply_timeline(path)
            if hasattr(self, "inserts_tab"):
                self.inserts_tab.apply_inserts(path)
            if hasattr(self, "editing_tab"):
                self.editing_tab.apply_editing(path)
        finally:
            self._autosave_paused = False
        self._refresh_all_tab_marks()
        self._refresh_banner()
        self._persist_last_project_path()
        # Kick off a silent background sweep — generate any missing project
        # thumbnails, drop orphans. Runs off the main thread so the user
        # doesn't see a hitch on project open.
        self._start_thumbnail_sweep(path)
        return True

    def _start_thumbnail_sweep(self, project_path: Path):
        def worker():
            try:
                import thumbnails
                thumbnails.regenerate_all_thumbnails(project_path)
                thumbnails.clean_orphan_thumbnails(project_path)
            except Exception as e:
                DEBUG_LOG.log_exception("thumbnails.sweep", e)
        threading.Thread(target=worker, daemon=True).start()

    def _persist_last_project_path(self):
        """Remember the open project so the next app launch can offer to
        resume it. No-op when no project is open."""
        if not self.current_project:
            return
        p = str(self.current_project)
        self.settings["last_project_path"] = p
        settings.set_setting("last_project_path", p)

    def _maybe_resume_last_project(self):
        """On startup, if a project was open last session, ask whether to
        resume it. Silently skips if the path is missing or no longer valid."""
        lp = (self.settings.get("last_project_path") or "").strip()
        if not lp:
            return
        path = Path(lp)
        if not path.exists() or not (path / "project.json").exists():
            return
        if messagebox.askyesno(
            "📁 Resume project",
            f"Load the project you were working on last time?\n\n"
            f"  📁 {path.name}\n"
            f"  {path}\n\n"
            f"Yes — resume that project.\n"
            f"No  — start with a blank form (the path stays remembered).",
            parent=self,
        ):
            self._load_project_from_path(path)

    # ── SETTINGS ────────────────────────────────────────────────────
    def _open_settings(self):
        dlg = SettingsDialog(self)
        self.wait_window(dlg)
        self.settings = settings.load_settings()
        self._refresh_cost_estimate()

    # ── PROMPT PICKER (for the multi-prompt Generate flow) ──────────
    def _open_generate_prompt_picker(self):
        from ui.prompt_editor import PromptEditor
        dlg = tk.Toplevel(self)
        dlg.title("⚙ Choose a prompt to tune")
        dlg.geometry("420x340")
        dlg.transient(self); dlg.grab_set()
        ttk.Label(dlg, text="The 🎬 Generate flow uses several prompts.\n"
                            "Pick one to edit:",
                  wraplength=380, justify="left").pack(anchor="w", padx=14, pady=(14, 8))
        options = [
            ("script_system", "🎬 Base system persona (sent with every act call)"),
            ("context",       "📋 Context block (all step-1 fields rendered)"),
            ("act1",          "🎬 Act 1 — Opening & pain agitation"),
            ("act2",          "🎬 Act 2 — Heroine + friends"),
            ("act3",          "🎬 Act 3 — Expert + antagonist"),
            ("act4",          "🎬 Act 4 — Offer & close"),
        ]
        for key, label in options:
            row = ttk.Frame(dlg); row.pack(fill="x", padx=14, pady=2)
            b = ttk.Button(row, text=label, width=44,
                            command=lambda k=key: (dlg.destroy(),
                                                    PromptEditor(self, k, main_window=self)))
            b.pack(side="left")
        ttk.Button(dlg, text="✖ Cancel", command=dlg.destroy).pack(pady=(10, 12))

    # ── GENERATE ────────────────────────────────────────────────────
    def _on_generate(self):
        form = self._collect_form()
        extra = form.pop("extra_instructions", "")

        # Sanity check API key
        provider = self.text_provider_var.get()
        if provider == "openrouter" and not self.settings.get("openrouter_api_key"):
            messagebox.showwarning("⚠ Missing API key",
                                    "OpenRouter API key is not set. Open Settings to add it.")
            return
        if provider == "anthropic" and not self.settings.get("anthropic_api_key"):
            messagebox.showwarning("⚠ Missing API key",
                                    "Anthropic API key is not set. Open Settings to add it.")
            return

        # If project already has a script, confirm overwrite
        if self.current_project and (self.current_project / "script.txt").exists():
            if not messagebox.askyesno(
                "⚠ Overwrite script",
                f"Project '{self.current_project.name}' already has a generated script. "
                "Generate a new one and overwrite?",
            ):
                return

        if self.current_project:
            projects.set_step_status(self.current_project, "script", "in_progress")
            self._refresh_banner()

        import time as _time
        from prompts import get_target_words
        from timing_history import HISTORY as _HISTORY

        duration = int(form.get("duration", 45))
        target_words_per_stage = get_target_words(duration)  # {"act1":..,"act2":..,...}
        model_slug = self.model_var.get()

        progress = ProgressDialog(self, "🎬 Generating talk show script",
                                    model_slug=model_slug,
                                    target_words=target_words_per_stage)

        result_holder = {"script": None, "error": None}
        # Track which stage is in flight so we can record a timing sample
        # when its act_complete callback fires.
        stage_state = {"key": None, "start": 0.0}
        stage_keys = ["act1", "act2", "act3", "act4"]

        def on_progress(name, cur, tot):
            stage_state["key"] = stage_keys[cur - 1] if 0 <= cur - 1 < len(stage_keys) else None
            stage_state["start"] = _time.time()
            self.after(0, lambda: progress.update_stage(name, cur, tot))

        def on_act_complete(label, text):
            key = stage_state["key"]
            if key:
                elapsed = _time.time() - stage_state["start"]
                _HISTORY.record(model_slug, key, elapsed,
                                target_words=target_words_per_stage.get(key, 0))
            self.after(0, lambda: progress.add_completed_part(label, text))

        def worker():
            try:
                client = self._build_client()
                script = generate_script(
                    client, form, extra_instructions=extra,
                    progress_callback=on_progress,
                    cancel_check=lambda: progress.cancelled,
                    act_complete_callback=on_act_complete,
                    pause_check=lambda: progress.paused,
                )
                result_holder["script"] = script
            except Exception as e:
                result_holder["error"] = str(e)
            finally:
                self.after(0, lambda: self._finish_generate(progress, result_holder, form))

        threading.Thread(target=worker, daemon=True).start()

    def _finish_generate(self, progress, result_holder, form):
        progress.finish()
        progress.destroy()
        if result_holder["error"]:
            if self.current_project:
                projects.set_step_status(self.current_project, "script", "failed")
                self._refresh_banner()
            messagebox.showerror("❌ Generation failed", result_holder["error"])
            return
        if not result_holder["script"]:
            if self.current_project:
                projects.set_step_status(self.current_project, "script", "pending")
                self._refresh_banner()
            return  # cancelled

        # Auto-save into the open project (skip Save As dialog)
        if self.current_project:
            projects.save_project(self.current_project, form,
                                  script=result_holder["script"])
            projects.set_step_status(self.current_project, "script", "done")
            self._refresh_banner()
            self._refresh_all_tab_marks()
            # Push the fresh script into the Storyboard tab's read-only preview
            # so the user sees it the moment they switch tabs.
            if hasattr(self, "studio_tab"):
                try:
                    self.studio_tab.reload_script_preview()
                except Exception as e:
                    DEBUG_LOG.log_exception("reload_script_preview", e)
            messagebox.showinfo(
                "✅ Saved",
                f"Script saved to project:\n{self.current_project / 'script.txt'}"
            )
            return

        # No project loaded — fall back to Save As dialog
        last_dir = self.settings.get("last_save_dir") or str(Path.home())
        suggested = self._suggest_filename(form)
        path = filedialog.asksaveasfilename(
            parent=self,
            title="Save script",
            defaultextension=".txt",
            initialdir=last_dir,
            initialfile=suggested,
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")],
        )
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(result_holder["script"])
            settings.set_setting("last_save_dir", str(Path(path).parent))
            messagebox.showinfo("✅ Saved", f"Script saved to:\n{path}")
        except IOError as e:
            messagebox.showerror("❌ Save failed", str(e))

    def _suggest_filename(self, form: dict) -> str:
        niche_slug = form.get("niche", "show").lower().replace(" ", "_")[:30]
        hero_slug = form.get("heroine_name", "hero").split()[0].lower()
        stamp = datetime.now().strftime("%Y-%m-%d_%H-%M")
        return f"{niche_slug}_{hero_slug}_{stamp}.txt"


# ─────────────────────────────────────────────────────────────────────
# Preset picker dialog
# ─────────────────────────────────────────────────────────────────────
class _PresetPicker(tk.Toplevel):
    def __init__(self, parent, items):
        super().__init__(parent)
        self.title("📂 Load preset")
        self.geometry("420x320")
        self.transient(parent)
        self.grab_set()
        self.chosen_path = None

        ttk.Label(self, text="Select a preset:").pack(anchor="w", padx=12, pady=(12, 6))

        frame = ttk.Frame(self); frame.pack(fill="both", expand=True, padx=12)
        self.listbox = tk.Listbox(frame)
        self.listbox.pack(side="left", fill="both", expand=True)
        sb = ttk.Scrollbar(frame, command=self.listbox.yview)
        sb.pack(side="right", fill="y")
        self.listbox.config(yscrollcommand=sb.set)

        self._items = items
        for name, _ in items:
            self.listbox.insert("end", name)

        btn_row = ttk.Frame(self); btn_row.pack(fill="x", padx=12, pady=10)
        load_btn = ttk.Button(btn_row, text="📂 Load", command=self._load)
        load_btn.pack(side="right")
        Tooltip(load_btn, "Load the selected preset into the form.")
        del_btn = ttk.Button(btn_row, text="🗑 Delete", command=self._delete)
        del_btn.pack(side="right", padx=(0, 6))
        Tooltip(del_btn, "Permanently delete the selected preset file.")
        cancel_btn = ttk.Button(btn_row, text="✖ Cancel", command=self.destroy)
        cancel_btn.pack(side="right", padx=(0, 6))
        Tooltip(cancel_btn, "Close this dialog without loading anything.")

    def _load(self):
        sel = self.listbox.curselection()
        if not sel:
            return
        self.chosen_path = self._items[sel[0]][1]
        self.destroy()

    def _delete(self):
        sel = self.listbox.curselection()
        if not sel:
            return
        name, path = self._items[sel[0]]
        if messagebox.askyesno("🗑 Delete preset", f"Delete '{name}'?", parent=self):
            presets.delete_preset(path)
            self.listbox.delete(sel[0])
            del self._items[sel[0]]


# ─────────────────────────────────────────────────────────────────────
# Project picker dialog
# ─────────────────────────────────────────────────────────────────────
class _ProjectPicker(tk.Toplevel):
    def __init__(self, parent, items):
        super().__init__(parent)
        self.title("📂 Open project")
        self.geometry("480x360")
        self.transient(parent)
        self.grab_set()
        self.chosen_path = None

        ttk.Label(self, text="Select a project:").pack(anchor="w", padx=12, pady=(12, 6))

        frame = ttk.Frame(self); frame.pack(fill="both", expand=True, padx=12)
        self.listbox = tk.Listbox(frame)
        self.listbox.pack(side="left", fill="both", expand=True)
        sb = ttk.Scrollbar(frame, command=self.listbox.yview)
        sb.pack(side="right", fill="y")
        self.listbox.config(yscrollcommand=sb.set)

        self._items = items  # list of (name, path, updated_at)
        for name, _, updated in items:
            label = f"📁 {name}   ·   {updated}" if updated else f"📁 {name}"
            self.listbox.insert("end", label)

        btn_row = ttk.Frame(self); btn_row.pack(fill="x", padx=12, pady=10)
        open_btn = ttk.Button(btn_row, text="📂 Open", command=self._open)
        open_btn.pack(side="right")
        Tooltip(open_btn, "Open the selected project — loads form and any saved script back into the workspace.")
        del_btn = ttk.Button(btn_row, text="🗑 Delete", command=self._delete)
        del_btn.pack(side="right", padx=(0, 6))
        Tooltip(del_btn, "Permanently delete the project folder and all its files (script, audio, video, everything).")
        cancel_btn = ttk.Button(btn_row, text="✖ Cancel", command=self.destroy)
        cancel_btn.pack(side="right", padx=(0, 6))
        Tooltip(cancel_btn, "Close this dialog without opening anything.")

    def _open(self):
        sel = self.listbox.curselection()
        if not sel:
            return
        self.chosen_path = self._items[sel[0]][1]
        self.destroy()

    def _delete(self):
        sel = self.listbox.curselection()
        if not sel:
            return
        name, path, _ = self._items[sel[0]]
        if messagebox.askyesno("🗑 Delete project",
                               f"Delete project '{name}' and all its files?",
                               parent=self):
            projects.delete_project(path)
            self.listbox.delete(sel[0])
            del self._items[sel[0]]
