"""
Step 2 — Studio shoot.

Sub-notebook with 9 sub-tabs:
  🎨 Logo & Brand     (this turn — full UI + AI palette suggest)
  🏛 Studio design    (stub)
  🎭 Characters       (stub)
  👥 Audience         (stub)
  🔊 Voices           (stub)
  📋 Storyboard       (stub)
  🎥 Camera plan      (stub)
  ▶ Generate          (stub)
  🎞 Timeline         (stub)
"""
import json
import re
import threading
import time
import tkinter as tk
from tkinter import ttk, messagebox

import config as cfg
import projects
from prompt_store import STORE as PROMPT_STORE


# ──────────────────────────────────────────────────────────────────────
# Storyboard pipeline helpers (module-level for testability)
# ──────────────────────────────────────────────────────────────────────
_ACT_HEADER_RE = re.compile(r"^# ACT (\d+) —[^\n]*\n", re.MULTILINE)
_BEATS_BLOCK_RE = re.compile(r"<beats>\s*(.*?)\s*</beats>", re.DOTALL | re.IGNORECASE)
_FENCED_JSON_RE = re.compile(r"```(?:json)?\s*(\[.*?\])\s*```", re.DOTALL)


def _split_script_into_acts(script_text: str) -> dict:
    """Return {1: '<act 1 text>', 2: ..., 3: ..., 4: ...}.
    Raises RuntimeError if no '# ACT N — ...' headers are found."""
    matches = list(_ACT_HEADER_RE.finditer(script_text))
    if not matches:
        raise RuntimeError(
            "Could not split the script — no '# ACT N — TITLE' headers found. "
            "Re-run step 1 (🎬 Generate) to produce a properly-formatted script.")
    out: dict = {}
    for i, m in enumerate(matches):
        act_num = int(m.group(1))
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(script_text)
        out[act_num] = script_text[start:end].strip()
    return out


def _estimate_part_duration(text: str) -> float:
    """Rough word-count → spoken-duration estimate (~150 wpm = 2.5 wps)."""
    words = len((text or "").split())
    return round(max(words / 2.5, 0.5), 1)


_PART_WORD_MIN = 10
_PART_WORD_MAX = 25


def _sub_split_long_sentence(sentence: str) -> list:
    """Split a single sentence whose word count exceeds _PART_WORD_MAX by
    clause boundaries (commas / semicolons / em-dashes), falling back to a
    hard word-count split when no clause break helps."""
    clauses = re.split(r"(?<=[,;:—])\s+", sentence)
    raw: list = []
    cur: list = []
    cur_count = 0
    for c in clauses:
        cw = c.split()
        cc = len(cw)
        if cc == 0:
            continue
        if cc > _PART_WORD_MAX:
            if cur:
                raw.append(" ".join(cur))
                cur = []
                cur_count = 0
            for i in range(0, cc, _PART_WORD_MAX):
                raw.append(" ".join(cw[i : i + _PART_WORD_MAX]))
            continue
        if cur and cur_count + cc > _PART_WORD_MAX:
            raw.append(" ".join(cur))
            cur = [c]
            cur_count = cc
        else:
            cur.append(c)
            cur_count += cc
    if cur:
        raw.append(" ".join(cur))
    return raw


def _merge_tiny_parts(parts: list) -> list:
    """Pass over the parts list once and fold sub-_PART_WORD_MIN parts into
    the previous part as long as the union stays within _PART_WORD_MAX."""
    if len(parts) <= 1:
        return list(parts)
    out: list = []
    for p in parts:
        if out:
            prev_count = len(out[-1].split())
            cur_count = len(p.split())
            if cur_count < _PART_WORD_MIN and prev_count + cur_count <= _PART_WORD_MAX:
                out[-1] = out[-1] + " " + p
                continue
        out.append(p)
    return out


def split_text_into_parts(text: str) -> list:
    """Heuristic splitter for long beat text.

    Returns [{"text", "duration"}] of length 1 if the text fits within
    _PART_WORD_MAX words, otherwise multiple parts of 10-25 words each.

    Algorithm:
      1. Sentence-split on `.?!`.
      2. Greedily concatenate sentences while the running word count is
         under _PART_WORD_MAX.
      3. If a single sentence exceeds _PART_WORD_MAX, fall back to
         _sub_split_long_sentence (clauses → hard word-split).
      4. Merge tiny tail parts (< _PART_WORD_MIN words) into the previous
         part to avoid 2-word fragments.
    """
    text = (text or "").strip()
    if not text:
        return [{"text": "", "duration": 0.0}]
    if len(text.split()) <= _PART_WORD_MAX:
        return [{"text": text, "duration": _estimate_part_duration(text)}]

    sentences = re.split(r"(?<=[.!?])\s+", text)
    raw: list = []
    cur: list = []
    cur_count = 0
    for s in sentences:
        sw = s.split()
        sc = len(sw)
        if sc == 0:
            continue
        if sc > _PART_WORD_MAX:
            if cur:
                raw.append(" ".join(cur))
                cur = []
                cur_count = 0
            raw.extend(_sub_split_long_sentence(s))
            continue
        if cur and cur_count + sc > _PART_WORD_MAX:
            raw.append(" ".join(cur))
            cur = [s]
            cur_count = sc
        else:
            cur.append(s)
            cur_count += sc
    if cur:
        raw.append(" ".join(cur))

    merged = _merge_tiny_parts(raw)
    return [{"text": p, "duration": _estimate_part_duration(p)} for p in merged]


def _extract_beats_json(raw: str) -> list:
    """Parse the LLM's reply and return the beats list.
    Tolerates: <beats>…</beats> wrapper, ```json fences, or bare JSON arrays.
    Raises RuntimeError on unparseable output."""
    candidates: list = []
    m = _BEATS_BLOCK_RE.search(raw)
    if m:
        candidates.append(m.group(1).strip())
    m = _FENCED_JSON_RE.search(raw)
    if m:
        candidates.append(m.group(1).strip())
    # Last resort: first '[' to last ']'
    s, e = raw.find("["), raw.rfind("]")
    if s >= 0 and e > s:
        candidates.append(raw[s : e + 1])

    for cand in candidates:
        try:
            data = json.loads(cand)
            if isinstance(data, list):
                return data
        except json.JSONDecodeError:
            continue
    raise RuntimeError(
        f"Could not extract <beats>...</beats> JSON from LLM output. "
        f"First 300 chars: {raw[:300]}…")
from ui.widgets import (
    LabeledEntry, LabeledCombobox, LabeledText, SectionFrame,
    Tooltip, HelpIcon, ColorSwatch, LabeledSlider, GearButton,
    ModelPicker, display_image_path_on_canvas, bind_autosave,
    show_image_popup,
)


class StudioShootTab(ttk.Frame):
    """Holds the inner notebook for all step-2 sub-tabs."""

    def __init__(self, parent, main_window):
        super().__init__(parent)
        self.main = main_window  # weak ref to MainWindow for client + project access

        # Characters state
        self._characters: list = []          # list of (char_id, label, name)
        self._character_form_state: dict = {} # char_id -> latest form values
        self.current_char_id: str | None = None
        # Keep a reference to the current face PhotoImage so Tk doesn't
        # garbage-collect it and blank the canvas.
        self._face_photo_ref = None

        # Voices state
        self._voice_form_state: dict = {}    # char_id -> voice form values
        self.current_voice_char_id: str | None = None

        # Storyboard state
        self._beats: list = []
        self._selected_beat_idx: int | None = None
        self._pass_statuses: dict = {"parse": "pending",
                                     "atmospherize": "pending",
                                     "camera": "pending"}

        # Timeline state
        self._timeline: dict | None = None

        nb = ttk.Notebook(self, padding=6)
        nb.pack(fill="both", expand=True)
        self._sub_nb = nb

        # Camera plan settings live in StringVars/IntVars on self — they are
        # edited through a popup launched from the Storyboard tab's ⚙ button
        # rather than a dedicated sub-tab. Initialised from DEFAULT_CAMERA_PLAN
        # and overridden by camera_plan.json when a project is opened.
        self._cam_preset_var = tk.StringVar(value=cfg.DEFAULT_CAMERA_PLAN["preset"])
        self._cam_reaction_pct_var = tk.IntVar(value=cfg.DEFAULT_CAMERA_PLAN["reaction_pct"])
        self._cam_audience_pct_var = tk.IntVar(value=cfg.DEFAULT_CAMERA_PLAN["audience_pct"])
        self._cam_avg_duration_var = tk.DoubleVar(value=cfg.DEFAULT_CAMERA_PLAN["avg_shot_duration"])
        self._cam_transition_var = tk.StringVar(value=cfg.DEFAULT_CAMERA_PLAN["default_transition"])
        self._cam_wide_freq_var = tk.StringVar(value=cfg.DEFAULT_CAMERA_PLAN["wide_frequency"])
        self._cam_custom_rules = cfg.DEFAULT_CAMERA_PLAN["custom_rules"]

        tab_brand = ttk.Frame(nb, padding=14)
        tab_studio_design = ttk.Frame(nb, padding=14)
        tab_characters = ttk.Frame(nb, padding=14)
        tab_audience = ttk.Frame(nb, padding=14)
        tab_voices = ttk.Frame(nb, padding=14)
        tab_storyboard = ttk.Frame(nb, padding=14)
        tab_talking_heads = ttk.Frame(nb, padding=14)
        tab_timeline = ttk.Frame(nb, padding=14)

        nb.add(tab_brand, text="🎨 Logo & Brand")
        nb.add(tab_studio_design, text="🏛 Studio design")
        nb.add(tab_characters, text="🎭 Characters")
        nb.add(tab_audience, text="👥 Audience")
        nb.add(tab_voices, text="🔊 Voices")
        nb.add(tab_storyboard, text="📋 Storyboard")
        nb.add(tab_talking_heads, text="🗣 Talking heads")
        nb.add(tab_timeline, text="🎞 Timeline")

        # Track sub-tabs for ✅-on-complete refresh
        self._sub_tabs = {
            "brand":         tab_brand,
            "studio":        tab_studio_design,
            "characters":    tab_characters,
            "audience":      tab_audience,
            "voices":        tab_voices,
            "storyboard":    tab_storyboard,
            "talking_heads": tab_talking_heads,
            "timeline":      tab_timeline,
        }
        self._sub_tab_originals = {
            "brand":         "🎨 Logo & Brand",
            "studio":        "🏛 Studio design",
            "characters":    "🎭 Characters",
            "audience":      "👥 Audience",
            "voices":        "🔊 Voices",
            "storyboard":    "📋 Storyboard",
            "talking_heads": "🗣 Talking heads",
            "timeline":      "🎞 Timeline",
        }

        # Sub-tab builders
        self._build_brand_tab(tab_brand)
        self._build_studio_design_tab(tab_studio_design)
        self._build_characters_tab(tab_characters)
        self._build_audience_tab(tab_audience)
        self._build_voices_tab(tab_voices)
        self._build_storyboard_tab(tab_storyboard)
        self._build_talking_heads_tab(tab_talking_heads)
        self._build_timeline_tab(tab_timeline)

    # ── 🎨 Logo & Brand sub-tab ─────────────────────────────────────
    def _build_brand_tab(self, parent):
        # Two-column layout: form on the left, preview on the right
        cols = ttk.Frame(parent); cols.pack(fill="both", expand=True)
        cols.columnconfigure(0, weight=1)
        cols.columnconfigure(1, weight=1)

        left = ttk.Frame(cols); left.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        right = ttk.Frame(cols); right.grid(row=0, column=1, sticky="nsew")

        # ── LEFT: identity + typography ────────────────────────────
        idf = SectionFrame(left, "🎨 Identity")
        idf.pack(fill="x", pady=(0, 10))
        grid = ttk.Frame(idf); grid.pack(fill="x")
        for c in range(2):
            grid.columnconfigure(c, weight=1)

        self.brand_era = LabeledCombobox(grid, "Era preset",
            cfg.ERA_PRESETS, cfg.ERA_PRESETS[2],
            help_text="Shared with Studio design. Drives logo style, color saturation, and graphics treatment.")
        self.brand_era.grid(row=0, column=0, sticky="ew", padx=(0, 8), pady=4)

        self.brand_logo_style = LabeledCombobox(grid, "Logo style",
            cfg.LOGO_STYLES, cfg.LOGO_STYLES[0],
            help_text="Visual approach for the logo. 'bubble' is classic 90s/2000s daytime talk style; wordmarks suit modern HD.")
        self.brand_logo_style.grid(row=0, column=1, sticky="ew", pady=4)

        self.brand_typography = LabeledCombobox(grid, "Typography preset",
            cfg.TYPOGRAPHY_PRESETS, cfg.TYPOGRAPHY_PRESETS[0],
            help_text="Headline/lower-third font family used in graphics overlays in step 3.")
        self.brand_typography.grid(row=1, column=0, columnspan=2, sticky="ew", pady=4)

        self.brand_extra = LabeledText(idf, "Logo description (optional)",
            height=3, width=40,
            placeholder="Extra notes for AI: 'with a microphone icon', 'gold trim', 'inside a TV frame'…",
            help_text="Free-form additions to the logo prompt. Optional — defaults work fine without it.")
        self.brand_extra.pack(fill="x", pady=(8, 0))

        # ── LEFT: palette ──────────────────────────────────────────
        pf = SectionFrame(left, "🎨 Brand palette")
        pf.pack(fill="x", pady=(0, 10))
        pcols = ttk.Frame(pf); pcols.pack(fill="x")
        for c in range(3):
            pcols.columnconfigure(c, weight=1)

        self.color_primary = ColorSwatch(pcols, "Primary",
            cfg.DEFAULT_BRAND_PALETTE["primary"],
            help_text="Main brand color — backdrop accents, host name plates, dominant logo color.")
        self.color_primary.grid(row=0, column=0, sticky="ew", padx=(0, 8))

        self.color_secondary = ColorSwatch(pcols, "Secondary",
            cfg.DEFAULT_BRAND_PALETTE["secondary"],
            help_text="Support color — lower-third backgrounds, secondary text, alternating bars.")
        self.color_secondary.grid(row=0, column=1, sticky="ew", padx=(0, 8))

        self.color_accent = ColorSwatch(pcols, "Accent",
            cfg.DEFAULT_BRAND_PALETTE["accent"],
            help_text="Highlight color — price flash, urgency timer, 'CALL NOW' callouts in step 3.")
        self.color_accent.grid(row=0, column=2, sticky="ew")

        ai_row = ttk.Frame(pf); ai_row.pack(anchor="e", pady=(8, 0))
        ai_btn = ttk.Button(ai_row, text="✨ AI suggest palette",
                            command=self._ai_suggest_palette)
        ai_btn.pack(side="left")
        Tooltip(ai_btn,
            "Ask the configured LLM to propose a 3-color palette based on show name, era, and tone. "
            "Overwrites the three swatches above. Costs ~$0.01.")
        GearButton(ai_row, "suggest_palette", main_window=self.main).pack(side="left", padx=(2, 0))

        # ── LEFT: generate ─────────────────────────────────────────
        gf = SectionFrame(left, "🖼 Logo image")
        gf.pack(fill="x")
        ttk.Label(gf,
            text="ℹ Logo generation is locked to recraft/recraft-v4.1-vector "
                 "($0.08/image, SVG vector output). Other image models live "
                 "in the per-tab Engine pickers for non-logo tasks.",
            foreground="grey", font=("", 9, "italic"),
            wraplength=460, justify="left").pack(anchor="w", pady=(0, 6))
        row = ttk.Frame(gf); row.pack(fill="x")

        gen_btn = ttk.Button(row, text="🎨 Generate logo with AI",
                              command=self._generate_logo)
        gen_btn.pack(side="left")
        Tooltip(gen_btn,
            "Generate the logo via Recraft V4.1 Vector ($0.08/image, SVG). "
            "Saves to <project>/brand/logo.svg with version rotation.")

        save_btn = ttk.Button(row, text="💾 Save brand",
                               command=self._save_brand)
        save_btn.pack(side="left", padx=(8, 0))
        Tooltip(save_btn,
            "Persist current brand parameters (palette, typography, era, style) to <project>/brand/brand.json. "
            "Required to make this available to later steps.")

        self.brand_status_var = tk.StringVar(value="")
        ttk.Label(gf, textvariable=self.brand_status_var,
                  foreground="grey", wraplength=460).pack(anchor="w", pady=(8, 0))

        # ── RIGHT: preview ─────────────────────────────────────────
        prev = SectionFrame(right, "👁 Preview")
        prev.pack(fill="both", expand=True)

        self.brand_preview_canvas = tk.Canvas(prev, height=240,
                                              background="#f4f4f4",
                                              highlightthickness=1,
                                              highlightbackground="#ddd")
        self.brand_preview_canvas.pack(fill="x")
        self._draw_preview_placeholder()
        self.brand_preview_canvas.bind("<Button-1>",
            lambda _e: self._show_logo_popup())
        self.brand_preview_canvas.configure(cursor="hand2")

        sw_row = ttk.Frame(prev); sw_row.pack(fill="x", pady=(10, 0))
        self.preview_swatches = []
        for i in range(3):
            sw = tk.Label(sw_row, background="#888888",
                          width=8, height=2, relief="solid", borderwidth=1)
            sw.pack(side="left", padx=(0, 6) if i < 2 else 0, fill="x", expand=True)
            self.preview_swatches.append(sw)

        # Sync preview swatches with color entries
        for src, idx in [
            (self.color_primary, 0),
            (self.color_secondary, 1),
            (self.color_accent, 2),
        ]:
            src.var.trace_add("write", lambda *_a, s=src, i=idx: self._update_preview_swatch(s, i))
        self._refresh_preview_swatches()

        # Auto-save bindings for Brand
        for w in (self.brand_era, self.brand_logo_style, self.brand_typography,
                   self.brand_extra, self.color_primary, self.color_secondary,
                   self.color_accent):
            bind_autosave(w, lambda: self._schedule_silent_save("brand"))

    # ── PREVIEW HELPERS ─────────────────────────────────────────────
    def _draw_preview_placeholder(self):
        self.brand_preview_canvas.delete("all")
        self.brand_preview_canvas.create_text(
            230, 120, text="🚧  Logo preview will appear here\nafter generation",
            fill="#999", font=("", 11), justify="center",
        )

    def _refresh_preview_swatches(self):
        for src, sw in zip(
            [self.color_primary, self.color_secondary, self.color_accent],
            self.preview_swatches,
        ):
            self._update_preview_swatch(src, self.preview_swatches.index(sw))

    def _update_preview_swatch(self, src, idx):
        val = src.get().strip()
        if val and (val.startswith("#") or len(val) == 6):
            if not val.startswith("#"):
                val = "#" + val
            try:
                self.preview_swatches[idx].config(background=val)
            except tk.TclError:
                pass

    # ── ACTIONS ─────────────────────────────────────────────────────
    def _collect_brand(self) -> dict:
        return {
            "era": self.brand_era.get(),
            "logo_style": self.brand_logo_style.get(),
            "typography": self.brand_typography.get(),
            "extra_description": self.brand_extra.get(),
            "palette": {
                "primary": self.color_primary.get(),
                "secondary": self.color_secondary.get(),
                "accent": self.color_accent.get(),
            },
        }

    def apply_brand(self, data: dict):
        """Load brand.json contents into the form + show the saved logo if it
        exists. Caller sets main._autosave_paused = True for the load."""
        # Find existing logo file (any extension)
        if self.main.current_project:
            brand_dir = self.main.current_project / "brand"
            if brand_dir.exists():
                versioned_re = re.compile(r"^logo\.v\d+\.")
                current_logo = next((p for p in brand_dir.glob("logo.*")
                                      if p.is_file() and not versioned_re.match(p.name)),
                                     None)
                if current_logo:
                    try:
                        cw = max(self.brand_preview_canvas.winfo_width(), 460)
                        ch = max(self.brand_preview_canvas.winfo_height(), 240)
                        self._brand_logo_photo_ref = display_image_path_on_canvas(
                            self.brand_preview_canvas, current_logo,
                            self.main.current_project, cw, ch)
                    except tk.TclError:
                        pass

        if not data:
            return
        if "era" in data:
            self.brand_era.set(data["era"])
        if "logo_style" in data:
            self.brand_logo_style.set(data["logo_style"])
        if "typography" in data:
            self.brand_typography.set(data["typography"])
        if "extra_description" in data:
            self.brand_extra.set(data["extra_description"])
        pal = data.get("palette", {})
        if pal.get("primary"):
            self.color_primary.set(pal["primary"])
        if pal.get("secondary"):
            self.color_secondary.set(pal["secondary"])
        if pal.get("accent"):
            self.color_accent.set(pal["accent"])

    def _require_project(self) -> bool:
        if not self.main.current_project:
            messagebox.showwarning(
                "⚠ No project",
                "Open or save a project first — brand data is stored inside the project folder.",
                parent=self,
            )
            return False
        return True

    def _save_brand(self):
        if not self._require_project():
            return
        path = projects.save_brand(self.main.current_project, self._collect_brand())
        self.brand_status_var.set(f"✅ Brand saved: {path}")

    def _ai_suggest_palette(self):
        # Pull show context from the main form
        try:
            form = self.main._collect_form()
        except Exception:
            form = {}

        self.brand_status_var.set("🔄 Asking LLM to propose a palette…")

        def worker():
            try:
                client = self.main._build_client()
                system = (
                    "You design color palettes for TV talk show branding. "
                    "Output STRICT JSON only, no commentary."
                )
                user = PROMPT_STORE.render(
                    "suggest_palette",
                    show_name=form.get("show_name", "Open Talk"),
                    era=self.brand_era.get(),
                    tone=form.get("tone", "US daytime TV"),
                    niche=form.get("niche", "Weight loss"),
                )
                raw = client.complete(system=system, user=user,
                                      max_tokens=200, temperature=0.7)
                self.after(0, lambda: self._apply_palette_response(raw))
            except Exception as e:
                err = str(e)
                self.after(0, lambda: self._palette_failed(err))

        threading.Thread(target=worker, daemon=True).start()

    def _apply_palette_response(self, raw: str):
        # Find a JSON object in the response (model sometimes wraps in code fences)
        start = raw.find("{")
        end = raw.rfind("}")
        if start < 0 or end < 0:
            self.brand_status_var.set(f"❌ Could not parse palette: {raw[:100]}…")
            return
        try:
            pal = json.loads(raw[start : end + 1])
        except json.JSONDecodeError as e:
            self.brand_status_var.set(f"❌ JSON error: {e}")
            return
        if pal.get("primary"):
            self.color_primary.set(pal["primary"])
        if pal.get("secondary"):
            self.color_secondary.set(pal["secondary"])
        if pal.get("accent"):
            self.color_accent.set(pal["accent"])
        self.brand_status_var.set("✅ Palette applied. Click 💾 Save brand to persist.")

    def _palette_failed(self, err: str):
        self.brand_status_var.set(f"❌ Palette suggest failed: {err[:200]}")

    # Logo is locked to Recraft (per user decision) — vector SVG output,
    # $0.08/image, scales cleanly to broadcast resolution.
    LOGO_MODEL_SLUG = "recraft/recraft-v4.1-vector"
    LOGO_MODEL_PRICE = "$0.08/image"

    def _generate_logo(self):
        if not self._require_project():
            return
        # Persist current brand params first so we have them even if render fails
        projects.save_brand(self.main.current_project, self._collect_brand())

        # Compose the prompt via PROMPT_STORE so user can edit via ⚙
        try:
            form = self.main._collect_form()
        except Exception:
            form = {}
        brand = self._collect_brand()
        prompt = PROMPT_STORE.render("logo_image_prompt",
            show_name=form.get("show_name", "Open Talk"),
            logo_style=brand.get("logo_style", ""),
            era=brand.get("era", ""),
            primary=brand["palette"].get("primary", ""),
            secondary=brand["palette"].get("secondary", ""),
            accent=brand["palette"].get("accent", ""),
            typography=brand.get("typography", ""),
            extra_description=brand.get("extra_description", "") or "")

        model_slug = self.LOGO_MODEL_SLUG
        self.brand_status_var.set(
            f"🔄 Generating logo via {model_slug} (~{self.LOGO_MODEL_PRICE})…")

        def worker():
            try:
                from llm_clients import OpenRouterClient
                client = OpenRouterClient(
                    self.main.settings.get("openrouter_api_key", ""), model_slug)
                img_bytes, ext = client.generate_image(prompt, model=model_slug)
                self.after(0, lambda: self._on_logo_generated(img_bytes, ext))
            except Exception as e:
                err = str(e)
                self.after(0, lambda: self.brand_status_var.set(
                    f"❌ Logo generation failed: {err[:240]}"))

        threading.Thread(target=worker, daemon=True).start()

    def _on_logo_generated(self, img_bytes: bytes, ext: str):
        proj = self.main.current_project
        path, archived = projects.save_logo_versioned(proj, img_bytes, ext)

        try:
            cw = max(self.brand_preview_canvas.winfo_width(), 460)
            ch = max(self.brand_preview_canvas.winfo_height(), 240)
        except tk.TclError:
            cw, ch = 460, 240

        # Thumbnails system rasterises SVG via svglib+reportlab too.
        self._brand_logo_photo_ref = display_image_path_on_canvas(
            self.brand_preview_canvas, path, proj, cw, ch)

        msg = f"✅ Logo saved: {path.name}"
        if archived:
            msg += f"  (previous → {archived.name})"
        self.brand_status_var.set(msg)
        self.main._refresh_all_tab_marks()

    # ── 🏛 Studio design sub-tab ────────────────────────────────────
    def _build_studio_design_tab(self, parent):
        # Library row (cross-project saved studios)
        lib_row = ttk.Frame(parent); lib_row.pack(fill="x", pady=(0, 6))
        ttk.Label(lib_row, text="📚 Library:").pack(side="left")
        HelpIcon(lib_row,
            "App-wide saved studios from ~/.talkshow_generator/studios/. "
            "Save the current set design (params + all 5 angles) into the library, "
            "load a saved studio back into the project, or delete an entry."
        ).pack(side="left")
        self.studio_lib_var = tk.StringVar()
        self.studio_lib_picker = ttk.Combobox(lib_row,
            textvariable=self.studio_lib_var, state="readonly", width=40)
        self.studio_lib_picker.pack(side="left", padx=(8, 4))
        load_lib_btn = ttk.Button(lib_row, text="📂 Load",
                                   command=self._load_studio_from_library)
        load_lib_btn.pack(side="left", padx=(0, 4))
        Tooltip(load_lib_btn,
            "Load the selected saved studio into the project. Existing studio.json "
            "and angle PNGs will be rotated as .v<N> backups.")
        save_lib_btn = ttk.Button(lib_row, text="💾 Save to library",
                                   command=self._save_studio_to_library)
        save_lib_btn.pack(side="left", padx=(0, 4))
        Tooltip(save_lib_btn,
            "Save the current studio (params + all 5 angle PNGs) into the cross-project "
            "library. Requires a Studio name and all 5 angles to be already rendered.")
        del_lib_btn = ttk.Button(lib_row, text="🗑 Delete",
                                  command=self._delete_studio_from_library)
        del_lib_btn.pack(side="left")
        Tooltip(del_lib_btn,
            "Permanently delete the currently selected library entry. "
            "Open projects are not affected.")

        cols = ttk.Frame(parent); cols.pack(fill="both", expand=True)
        cols.columnconfigure(0, weight=1)
        cols.columnconfigure(1, weight=1)
        left = ttk.Frame(cols); left.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        right = ttk.Frame(cols); right.grid(row=0, column=1, sticky="nsew")

        # ── LEFT: set design ───────────────────────────────────────
        sd = SectionFrame(left, "🏛 Set design")
        sd.pack(fill="x", pady=(0, 10))

        # Studio name (needed for library save/load slug)
        name_row = ttk.Frame(sd); name_row.pack(fill="x", pady=(0, 6))
        self.studio_name = LabeledEntry(name_row, "Studio name", "",
            help_text="Short name for this studio (used as the library slug when you 💾 Save to library). "
                      "E.g., 'Cozy pink living room' or 'Modern news studio'.")
        self.studio_name.pack(fill="x")

        grid = ttk.Frame(sd); grid.pack(fill="x")
        for c in range(2):
            grid.columnconfigure(c, weight=1)

        self.studio_era = LabeledCombobox(grid, "Era preset",
            cfg.ERA_PRESETS, cfg.ERA_PRESETS[2],
            help_text="Pre-fills from Brand on first project load. Change here only if you want a deliberate mismatch between branding and set design.")
        self.studio_era.grid(row=0, column=0, sticky="ew", padx=(0, 8), pady=4)

        self.studio_palette = LabeledCombobox(grid, "Color palette",
            cfg.STUDIO_COLOR_PALETTES, cfg.STUDIO_COLOR_PALETTES[0],
            help_text="Dominant temperature/saturation of the set lighting and walls. Blends with brand colors during render.")
        self.studio_palette.grid(row=0, column=1, sticky="ew", pady=4)

        self.studio_backdrop = LabeledCombobox(grid, "Backdrop",
            cfg.STUDIO_BACKDROPS, cfg.STUDIO_BACKDROPS[0],
            help_text="Wall behind the host/guest seating area — visible in every wide and 2-shot render.")
        self.studio_backdrop.grid(row=1, column=0, sticky="ew", padx=(0, 8), pady=4)

        self.studio_sofa = LabeledCombobox(grid, "Sofa / seating",
            cfg.SOFA_STYLES, cfg.SOFA_STYLES[0],
            help_text="Where hosts and guests sit. Drives 'seated on sofa' character pose generation.")
        self.studio_sofa.grid(row=1, column=1, sticky="ew", pady=4)

        self.studio_lighting = LabeledCombobox(grid, "Lighting",
            cfg.LIGHTING_STYLES, cfg.LIGHTING_STYLES[0],
            help_text="Mood and brightness. 'bright high-key' = classic daytime; 'dramatic spots' = revelations and confrontations.")
        self.studio_lighting.grid(row=2, column=0, sticky="ew", padx=(0, 8), pady=4)

        self.studio_floor = LabeledCombobox(grid, "Floor",
            cfg.FLOOR_STYLES, cfg.FLOOR_STYLES[0],
            help_text="Floor surface — visible in wide and audience-POV angles.")
        self.studio_floor.grid(row=2, column=1, sticky="ew", pady=4)

        self.studio_aspect = LabeledCombobox(grid, "Aspect ratio",
            cfg.STUDIO_ASPECT_RATIOS, cfg.DEFAULT_STUDIO_ASPECT,
            help_text="16:9 = standard broadcast / cam shots. 9:16 = vertical / promo cuts. "
                      "Passed to the image model via image_config.aspect_ratio.")
        self.studio_aspect.grid(row=3, column=0, sticky="ew", padx=(0, 8), pady=4)

        # Logo-on-backdrop toggle
        logo_row = ttk.Frame(sd); logo_row.pack(fill="x", pady=(8, 0))
        self.studio_logo_var = tk.BooleanVar(value=True)
        cb = ttk.Checkbutton(logo_row, text="Show logo on backdrop",
                             variable=self.studio_logo_var)
        cb.pack(side="left")
        Tooltip(cb,
            "When on, the prompt includes the show's logo prominently displayed on the back wall. "
            "Uses the show name from step 1 + brand style.")
        HelpIcon(logo_row,
            "When on, the studio render prompt includes the show logo on the back wall."
        ).pack(side="left")

        self.studio_extra = LabeledText(sd, "Extra description (optional)",
            height=3, width=40,
            placeholder="e.g., 'big windows showing nighttime city', 'live audience visible behind hosts'",
            help_text="Free-form additions to the studio render prompt. Apply to all 5 angles.")
        self.studio_extra.pack(fill="x", pady=(8, 0))

        # Auto-save bindings for Studio design
        for w in (self.studio_name, self.studio_era, self.studio_palette,
                   self.studio_backdrop, self.studio_sofa, self.studio_lighting,
                   self.studio_floor, self.studio_aspect, self.studio_extra,
                   self.studio_logo_var):
            bind_autosave(w, lambda: self._schedule_silent_save("studio"))

        # ── LEFT: angle renders ────────────────────────────────────
        ar = SectionFrame(left, "🎬 Render angles")
        ar.pack(fill="x")
        ModelPicker(ar, kind="image", main_window=self.main,
                     label_text="Image model:",
                     exclude_slugs=["recraft/recraft-v4.1-vector"]
                     ).pack(anchor="w", pady=(0, 6))
        btn_grid = ttk.Frame(ar); btn_grid.pack(fill="x")
        for c in range(2):
            btn_grid.columnconfigure(c, weight=1)

        for i, (key, label) in enumerate(cfg.STUDIO_ANGLES):
            b = ttk.Button(btn_grid, text=f"🎬 {label}",
                           command=lambda k=key, l=label: self._generate_studio_angle(k, l))
            b.grid(row=i // 2, column=i % 2, sticky="ew",
                   padx=(0, 6) if i % 2 == 0 else (6, 0), pady=2)
            Tooltip(b,
                f"Generate the '{label}' angle via kie.ai. "
                f"Saves to <project>/studio/{key}.png.")

        save_row = ttk.Frame(ar); save_row.pack(fill="x", pady=(8, 0))
        all_btn = ttk.Button(save_row, text="🚀 Generate all 5 angles",
                              command=self._generate_all_studio_angles)
        all_btn.pack(side="left")
        Tooltip(all_btn,
            "Generate all 5 angles in one batch. Costs ~5× a single render. "
            "Backdrops then feed into Characters renders.")

        save_btn = ttk.Button(save_row, text="💾 Save studio params",
                               command=self._save_studio)
        save_btn.pack(side="left", padx=(8, 0))
        Tooltip(save_btn,
            "Persist current studio parameters to <project>/studio/studio.json without rendering.")

        self.studio_status_var = tk.StringVar(value="")
        ttk.Label(ar, textvariable=self.studio_status_var,
                  foreground="grey", wraplength=460).pack(anchor="w", pady=(8, 0))

        # ── RIGHT: angle previews grid ─────────────────────────────
        prev = SectionFrame(right, "👁 Angle previews")
        prev.pack(fill="both", expand=True)

        self.studio_thumbs = {}
        thumb_grid = ttk.Frame(prev); thumb_grid.pack(fill="both", expand=True)
        for c in range(2):
            thumb_grid.columnconfigure(c, weight=1)

        for i, (key, label) in enumerate(cfg.STUDIO_ANGLES):
            cell = ttk.Frame(thumb_grid, padding=4)
            cell.grid(row=i // 2, column=i % 2, sticky="nsew", padx=2, pady=2)
            ttk.Label(cell, text=label, font=("", 9, "bold")).pack(anchor="w")
            canvas = tk.Canvas(cell, height=110, background="#f4f4f4",
                               highlightthickness=1, highlightbackground="#ddd")
            canvas.pack(fill="x")
            canvas.create_text(140, 55, text="🚧 Not generated",
                               fill="#999", font=("", 9))
            self.studio_thumbs[key] = canvas
            canvas.bind("<Button-1>",
                lambda _e, k=key: self._show_studio_angle_popup(k))
            canvas.configure(cursor="hand2")

        # Populate the studio library picker on first build.
        self._refresh_studio_library_list()

    # ── STUDIO ACTIONS ──────────────────────────────────────────────
    def _collect_studio(self) -> dict:
        return {
            "name": self.studio_name.get(),
            "era": self.studio_era.get(),
            "palette": self.studio_palette.get(),
            "backdrop": self.studio_backdrop.get(),
            "sofa": self.studio_sofa.get(),
            "lighting": self.studio_lighting.get(),
            "floor": self.studio_floor.get(),
            "aspect_ratio": self.studio_aspect.get(),
            "logo_on_backdrop": bool(self.studio_logo_var.get()),
            "extra_description": self.studio_extra.get(),
        }

    def apply_studio(self, data: dict):
        """Load studio.json contents into the form + reload existing angle
        renders into the thumbnail grid. Caller is expected to set
        main._autosave_paused = True for the duration."""
        if data:
            if data.get("name"):          self.studio_name.set(data["name"])
            if data.get("era"):           self.studio_era.set(data["era"])
            if data.get("palette"):       self.studio_palette.set(data["palette"])
            if data.get("backdrop"):      self.studio_backdrop.set(data["backdrop"])
            if data.get("sofa"):          self.studio_sofa.set(data["sofa"])
            if data.get("lighting"):      self.studio_lighting.set(data["lighting"])
            if data.get("floor"):         self.studio_floor.set(data["floor"])
            if data.get("aspect_ratio"):  self.studio_aspect.set(data["aspect_ratio"])
            if "logo_on_backdrop" in data:
                self.studio_logo_var.set(bool(data["logo_on_backdrop"]))
            if data.get("extra_description"):
                self.studio_extra.set(data["extra_description"])
        # Reload existing angle PNGs (or any saved extension)
        if self.main.current_project:
            self._reload_studio_thumbnails()
        self._refresh_studio_library_list()

    # ── STUDIO LIBRARY (cross-project) ──────────────────────────────
    def _studio_library_entries(self) -> list:
        import library
        return library.list_entries("studios")

    def _format_studio_library_label(self, entry: dict) -> str:
        p = entry.get("params") or {}
        nm = p.get("name") or entry.get("slug", "")
        era = p.get("era") or "?"
        palette = p.get("palette") or "?"
        return f"{nm} ({era} / {palette}) · {entry.get('slug')}"

    def _refresh_studio_library_list(self):
        if not hasattr(self, "studio_lib_picker"):
            return
        entries = self._studio_library_entries()
        labels = [self._format_studio_library_label(e) for e in entries]
        self._studio_library_cache = list(zip(labels, entries))
        self.studio_lib_picker["values"] = labels
        cur = self.studio_lib_var.get()
        if cur not in labels:
            self.studio_lib_var.set(labels[0] if labels else "")

    def _selected_library_studio(self):
        cache = getattr(self, "_studio_library_cache", [])
        cur = self.studio_lib_var.get()
        return next((e for lbl, e in cache if lbl == cur), None)

    def _save_studio_to_library(self):
        if not self._require_project():
            return
        params = self._collect_studio()
        name = (params.get("name") or "").strip()
        if not name:
            messagebox.showwarning("📚 Library",
                "Type a Studio name first — it's used as the library slug.",
                parent=self)
            return
        # All 5 angles must be rendered (per 5.5 — strict)
        proj = self.main.current_project
        sd = proj / "studio"
        versioned_re = re.compile(r"\.v\d+\.[a-z0-9]+$", re.IGNORECASE)
        files: dict = {}
        missing: list = []
        for angle_key, _label in cfg.STUDIO_ANGLES:
            cand = [p for p in sd.glob(f"{angle_key}.*")
                    if p.is_file() and not versioned_re.search(p.name)
                    and p.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp", ".svg")]
            if not cand:
                missing.append(angle_key)
                continue
            src = cand[0]
            files[f"{name} - {angle_key}{src.suffix}"] = src
        if missing:
            messagebox.showwarning("📚 Library",
                "Cannot save — missing angle(s): " + ", ".join(missing) + ".\n\n"
                "Render all 5 angles first (use '🚀 Generate all 5 angles').",
                parent=self)
            return

        import library
        try:
            entry_path = library.save_entry("studios", name, params, files)
        except Exception as e:
            messagebox.showerror("❌ Library save failed", str(e), parent=self)
            return
        self.studio_status_var.set(
            f"📚 Saved studio to library: {entry_path.name} (5 angles)")
        self._refresh_studio_library_list()

    def _delete_studio_from_library(self):
        entry = self._selected_library_studio()
        if not entry:
            messagebox.showinfo("📚 Library",
                "Pick a saved studio to delete first.", parent=self)
            return
        nm = (entry.get("params") or {}).get("name") or entry["slug"]
        if not messagebox.askyesno("🗑 Delete from library",
            f"Permanently delete studio '{nm}' from the library?\n\n"
            f"This does NOT affect any open project.", parent=self):
            return
        import library
        library.delete_entry("studios", entry["slug"])
        self._refresh_studio_library_list()
        self.studio_status_var.set(f"🗑 Deleted library entry: {entry['slug']}")

    def _load_studio_from_library(self):
        if not self._require_project():
            return
        entry = self._selected_library_studio()
        if not entry:
            messagebox.showinfo("📚 Library",
                "Pick a saved studio from the dropdown first.", parent=self)
            return
        params = entry.get("params") or {}
        files = entry.get("files") or {}

        # Apply params into form (silent so autosave doesn't fire mid-load)
        prev = self.main._autosave_paused
        self.main._autosave_paused = True
        try:
            self.apply_studio(params)
        finally:
            self.main._autosave_paused = prev

        # Persist studio.json (apply_studio doesn't save by itself)
        projects.save_studio(self.main.current_project, self._collect_studio())

        # Copy angle files into project, rotating any existing as .v<N>
        loaded = []
        for filename, src_path in files.items():
            stem = src_path.stem
            m = re.match(r"^.* - ([\w]+)$", stem)
            if not m:
                continue
            angle_key = m.group(1).lower()
            if angle_key not in {k for k, _ in cfg.STUDIO_ANGLES}:
                continue
            try:
                content = src_path.read_bytes()
            except OSError:
                continue
            projects.save_studio_angle_versioned(
                self.main.current_project, angle_key, content,
                src_path.suffix.lstrip("."))
            loaded.append(angle_key)

        self._reload_studio_thumbnails()
        self.main._refresh_all_tab_marks()
        self.studio_status_var.set(
            f"📚 Loaded studio '{params.get('name') or entry['slug']}' "
            f"({len(loaded)}/5 angles)")

    def _save_studio(self):
        if not self._require_project():
            return
        path = projects.save_studio(self.main.current_project, self._collect_studio())
        self.studio_status_var.set(f"✅ Studio saved: {path}")

    # ── Studio render plumbing ──────────────────────────────────────
    def _studio_logo_reference_bytes(self):
        """If 'logo on backdrop' is on AND a logo file exists, return its bytes
        for use as a reference image. Otherwise None."""
        if not self.studio_logo_var.get() or not self.main.current_project:
            return None
        brand_dir = self.main.current_project / "brand"
        if not brand_dir.exists():
            return None
        versioned_re = re.compile(r"^logo\.v\d+\.")
        current = next((p for p in brand_dir.glob("logo.*")
                         if p.is_file() and not versioned_re.match(p.name)), None)
        if not current:
            return None
        try:
            return current.read_bytes()
        except OSError:
            return None

    def _build_studio_prompt(self, angle_key: str) -> str:
        """Render the studio_image_prompt for one angle."""
        try:
            form = self.main._collect_form()
        except Exception:
            form = {}
        s = self._collect_studio()
        brand = self._collect_brand()
        framing = cfg.STUDIO_ANGLE_FRAMING.get(angle_key, "")
        logo_clause = ("A clean, professional show logo is mounted on the "
                       "back wall (use the reference image as guidance)."
                       if s.get("logo_on_backdrop") and self._studio_logo_reference_bytes()
                       else ("A clean, professional show logo for "
                             f"'{form.get('show_name', 'Open Talk')}' "
                             "is mounted on the back wall."
                             if s.get("logo_on_backdrop") else ""))
        return PROMPT_STORE.render("studio_image_prompt",
            era=s.get("era", ""),
            palette=s.get("palette", ""),
            primary=brand["palette"].get("primary", ""),
            secondary=brand["palette"].get("secondary", ""),
            accent=brand["palette"].get("accent", ""),
            backdrop=s.get("backdrop", ""),
            sofa=s.get("sofa", ""),
            lighting=s.get("lighting", ""),
            floor=s.get("floor", ""),
            logo_clause=logo_clause,
            angle_framing=framing,
            extra_description=s.get("extra_description", "") or "")

    def _validate_studio_engine(self) -> bool:
        provider = self.main.image_provider_var.get()
        if provider != "openrouter":
            messagebox.showwarning("⚠ Provider not wired",
                f"Image provider '{provider}' is not wired yet. "
                "Switch to 'openrouter' in the Engine picker.",
                parent=self)
            return False
        model_slug = self.main.image_model_slug_var.get()
        if not model_slug or model_slug == "recraft/recraft-v4.1-vector":
            messagebox.showwarning("⚠ Wrong model",
                "Pick a raster image model in the Engine picker (Recraft is "
                "vector-only and unsuitable for photo-real studio scenes).",
                parent=self)
            return False
        return True

    def _do_studio_render(self, key: str, reference_bytes: bytes = None) -> tuple:
        """Pure render: build prompt, call API. Returns (img_bytes, ext)."""
        aspect = self._collect_studio().get("aspect_ratio", cfg.DEFAULT_STUDIO_ASPECT)
        prompt = self._build_studio_prompt(key)
        model_slug = self.main.image_model_slug_var.get()
        from llm_clients import OpenRouterClient
        client = OpenRouterClient(
            self.main.settings.get("openrouter_api_key", ""), model_slug)
        return client.generate_image(prompt, model=model_slug,
            aspect_ratio=aspect, reference_image_bytes=reference_bytes)

    def _generate_studio_angle(self, key: str, label: str,
                                reference_bytes: bytes = None):
        """Single-angle threaded render with UI updates.

        If `reference_bytes` is None and the user has 'Show logo on backdrop'
        on, the logo image is used. Pass an explicit `reference_bytes` (e.g.
        the wide shot) to override that.
        """
        if not self._require_project():
            return
        if not self._validate_studio_engine():
            return
        projects.save_studio(self.main.current_project, self._collect_studio())

        if reference_bytes is None:
            reference_bytes = self._studio_logo_reference_bytes()

        aspect = self._collect_studio().get("aspect_ratio", cfg.DEFAULT_STUDIO_ASPECT)
        model_slug = self.main.image_model_slug_var.get()
        price_label = next((m["price_label"] for m in cfg.OPENROUTER_IMAGE_MODELS
                             if m["slug"] == model_slug), "?")
        ref_kind = ("wide-anchor" if reference_bytes and key != "wide"
                    else ("logo-ref" if reference_bytes else "no-ref"))
        self.studio_status_var.set(
            f"🔄 Generating {label} ({aspect}, {ref_kind}) via {model_slug} (~{price_label})…")

        def worker():
            try:
                img_bytes, ext = self._do_studio_render(
                    key, reference_bytes=reference_bytes)
                self.after(0, lambda: self._on_studio_angle_done(
                    key, label, img_bytes, ext))
            except Exception as e:
                err = str(e)
                self.after(0, lambda: self.studio_status_var.set(
                    f"❌ {label} failed: {err[:240]}"))

        threading.Thread(target=worker, daemon=True).start()

    def _on_studio_angle_done(self, key: str, label: str,
                               img_bytes: bytes, ext: str):
        path, archived = projects.save_studio_angle_versioned(
            self.main.current_project, key, img_bytes, ext)
        self._render_studio_thumbnail_path(key, path)
        msg = f"✅ {label}: {path.name}"
        if archived:
            msg += f"  (previous → {archived.name})"
        self.studio_status_var.set(msg)
        self.main._refresh_all_tab_marks()

    def _generate_all_studio_angles(self):
        """Two-phase batch for interior consistency:

          Phase 1: render Wide establishing first (uses logo as reference if
                    'Show logo on backdrop' is on). Wait for it to finish.
          Phase 2: render the other 4 angles in a staggered batch (1s apart),
                    all using the FINISHED wide shot as their reference image.
                    This locks the studio interior to one design across all
                    angles — same backdrop, furniture, lighting, logo placement.
        """
        if not self._require_project():
            return
        if not self._validate_studio_engine():
            return
        projects.save_studio(self.main.current_project, self._collect_studio())

        model_slug = self.main.image_model_slug_var.get()
        self.studio_status_var.set(
            f"🔄 Phase 1/2: generating Wide establishing as the interior "
            f"reference anchor via {model_slug}…")

        def worker_wide():
            try:
                img_bytes, ext = self._do_studio_render(
                    "wide", reference_bytes=self._studio_logo_reference_bytes())
                self.after(0, lambda: self._on_wide_anchor_done(img_bytes, ext))
            except Exception as e:
                err = str(e)
                self.after(0, lambda: self.studio_status_var.set(
                    f"❌ Wide (anchor) failed: {err[:240]}"))

        threading.Thread(target=worker_wide, daemon=True).start()

    def _on_wide_anchor_done(self, img_bytes: bytes, ext: str):
        # Save + show wide
        path, archived = projects.save_studio_angle_versioned(
            self.main.current_project, "wide", img_bytes, ext)
        self._render_studio_thumbnail_path("wide", path)
        msg = f"✅ Wide anchor: {path.name}"
        if archived:
            msg += f"  (previous → {archived.name})"
        self.studio_status_var.set(
            f"{msg}. Phase 2/2: rendering 4 angles with wide as reference (1s stagger)…")

        # Phase 2 — staggered spawn of the remaining 4 angles
        remaining = [(k, l) for k, l in cfg.STUDIO_ANGLES if k != "wide"]
        for i, (key, label) in enumerate(remaining):
            self.after(i * 1000,
                lambda k=key, l=label, ref=img_bytes:
                    self._generate_studio_angle(k, l, reference_bytes=ref))

    # ── Thumbnail grid ──────────────────────────────────────────────
    def _render_studio_thumbnail_path(self, key: str, original_path):
        canvas = self.studio_thumbs.get(key)
        if not canvas:
            return
        try:
            cw = max(canvas.winfo_width(), 240)
            ch = max(canvas.winfo_height(), 110)
        except tk.TclError:
            cw, ch = 240, 110
        if not hasattr(self, "_studio_thumb_refs"):
            self._studio_thumb_refs = {}
        self._studio_thumb_refs[key] = display_image_path_on_canvas(
            canvas, original_path, self.main.current_project, cw, ch)

    def _reload_studio_thumbnails(self):
        sd = self.main.current_project / "studio"
        if not sd.exists():
            return
        versioned_re = re.compile(r"\.v\d+\.[a-z0-9]+$", re.IGNORECASE)
        for key, _label in cfg.STUDIO_ANGLES:
            files = [p for p in sd.glob(f"{key}.*")
                     if p.is_file() and not versioned_re.search(p.name)]
            if not files:
                continue
            self._render_studio_thumbnail_path(key, files[0])

    # ── Image popups (click on a thumbnail → full-size view) ───────
    def _current_logo_path(self):
        if not self.main.current_project:
            return None
        bd = self.main.current_project / "brand"
        if not bd.exists():
            return None
        versioned_re = re.compile(r"^logo\.v\d+\.")
        return next((p for p in bd.glob("logo.*")
                      if p.is_file() and not versioned_re.match(p.name)), None)

    def _current_studio_angle_path(self, key: str):
        if not self.main.current_project:
            return None
        sd = self.main.current_project / "studio"
        if not sd.exists():
            return None
        versioned_re = re.compile(rf"^{re.escape(key)}\.v\d+\.")
        return next((p for p in sd.glob(f"{key}.*")
                      if p.is_file() and not versioned_re.match(p.name)), None)

    def _show_logo_popup(self):
        path = self._current_logo_path()
        if path:
            show_image_popup(self, path)

    def _show_studio_angle_popup(self, key: str):
        path = self._current_studio_angle_path(key)
        if path:
            show_image_popup(self, path)

    def _show_character_face_popup(self):
        if not self.main.current_project or not self.current_char_id:
            return
        path = projects.character_face_path(
            self.main.current_project, self.current_char_id)
        if path.exists():
            show_image_popup(self, path)

    def _show_character_pose_popup(self, pose_key: str):
        if not self.main.current_project or not self.current_char_id:
            return
        path = self._current_character_pose_path(pose_key)
        if path:
            show_image_popup(self, path)

    def _current_character_pose_path(self, pose_key: str):
        if not self.main.current_project or not self.current_char_id:
            return None
        cd = projects.character_dir(self.main.current_project, self.current_char_id)
        if not cd.exists():
            return None
        versioned_re = re.compile(rf"^{re.escape(pose_key)}\.v\d+\.")
        return next((p for p in cd.glob(f"{pose_key}.*")
                      if p.is_file() and not versioned_re.match(p.name)), None)

    def _render_pose_thumbnail_path(self, pose_key: str, original_path):
        canvas = self.char_pose_canvases.get(pose_key)
        if not canvas:
            return
        try:
            cw = max(canvas.winfo_width(), 240)
            ch = max(canvas.winfo_height(), 120)
        except tk.TclError:
            cw, ch = 240, 120
        self._pose_thumb_refs[pose_key] = display_image_path_on_canvas(
            canvas, original_path, self.main.current_project, cw, ch)

    def _reload_pose_thumbnails(self):
        """When switching characters or opening a project, paint any saved
        pose files into the 2×2 grid; reset cells where no file exists."""
        if not (self.main.current_project and self.current_char_id):
            for key, canvas in self.char_pose_canvases.items():
                canvas.delete("all")
                canvas.create_text(120, 60, text="🚧 Not generated",
                                    fill="#999", font=("", 9))
            self._pose_thumb_refs.clear()
            return
        versioned_re = re.compile(r"\.v\d+\.[a-z0-9]+$", re.IGNORECASE)
        cd = projects.character_dir(self.main.current_project, self.current_char_id)
        for key, canvas in self.char_pose_canvases.items():
            files = list(cd.glob(f"{key}.*")) if cd.exists() else []
            files = [p for p in files if p.is_file() and not versioned_re.search(p.name)]
            if files:
                self._render_pose_thumbnail_path(key, files[0])
                continue
            canvas.delete("all")
            canvas.create_text(120, 60, text="🚧 Not generated",
                                fill="#999", font=("", 9))
            self._pose_thumb_refs.pop(key, None)

    # ── 🎭 Characters sub-tab ───────────────────────────────────────
    def _build_characters_tab(self, parent):
        # ── Library row (cross-project saved characters) ───────────
        lib_row = ttk.Frame(parent); lib_row.pack(fill="x", pady=(0, 6))
        ttk.Label(lib_row, text="📚 Library:").pack(side="left")
        HelpIcon(lib_row,
            "App-wide saved characters from ~/.talkshow_generator/characters/. "
            "Save the current cast member into the library, load any saved character "
            "into the currently picked cast slot, or delete an entry."
        ).pack(side="left")
        self.char_lib_var = tk.StringVar()
        self.char_lib_picker = ttk.Combobox(lib_row, textvariable=self.char_lib_var,
                                             state="readonly", width=40)
        self.char_lib_picker.pack(side="left", padx=(8, 4))
        load_lib_btn = ttk.Button(lib_row, text="📂 Load",
                                   command=self._load_character_from_library)
        load_lib_btn.pack(side="left", padx=(0, 4))
        Tooltip(load_lib_btn,
            "Load the selected saved character into the currently picked cast slot. "
            "Existing files for that cast slot will be rotated as .v<N> backups.")
        save_lib_btn = ttk.Button(lib_row, text="💾 Save to library",
                                   command=self._save_character_to_library)
        save_lib_btn.pack(side="left", padx=(0, 4))
        Tooltip(save_lib_btn,
            "Save the current cast member (params + whatever face/pose images exist) "
            "into the cross-project library. Each save creates a new timestamped entry.")
        del_lib_btn = ttk.Button(lib_row, text="🗑 Delete",
                                  command=self._delete_character_from_library)
        del_lib_btn.pack(side="left")
        Tooltip(del_lib_btn,
            "Permanently delete the currently selected library entry. "
            "Cast slots in open projects are not affected.")

        # Picker row
        top = ttk.Frame(parent); top.pack(fill="x", pady=(0, 10))
        ttk.Label(top, text="Cast member:").pack(side="left")
        HelpIcon(top,
            "Pick a cast member to configure. The list is built from step 1 (hosts, heroine, friends, expert, antagonist)."
        ).pack(side="left")
        self.char_picker_var = tk.StringVar()
        self.char_picker = ttk.Combobox(top, textvariable=self.char_picker_var,
                                         state="readonly", width=48)
        self.char_picker.pack(side="left", padx=(8, 8))
        self.char_picker.bind("<<ComboboxSelected>>",
                              lambda _e: self._on_character_picked())
        refresh_btn = ttk.Button(top, text="🔄 Refresh from step 1",
                                  command=self._refresh_character_list)
        refresh_btn.pack(side="left")
        Tooltip(refresh_btn,
            "Re-read cast names from the step 1 form. Run after editing hosts/heroine/friends/antagonist names.")

        # Two-column body
        body = ttk.Frame(parent); body.pack(fill="both", expand=True)
        body.columnconfigure(0, weight=1)
        body.columnconfigure(1, weight=1)
        left = ttk.Frame(body); left.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        right = ttk.Frame(body); right.grid(row=0, column=1, sticky="nsew")

        # ── LEFT: face params ──────────────────────────────────────
        fp = SectionFrame(left, "🎲 Face parameters")
        fp.pack(fill="x", pady=(0, 10))

        nm = ttk.Frame(fp); nm.pack(fill="x")
        ttk.Label(nm, text="Character name:").pack(side="left")
        self.char_name_var = tk.StringVar(value="(no character selected)")
        ttk.Label(nm, textvariable=self.char_name_var,
                  foreground="#333", font=("", 10, "bold")).pack(side="left", padx=(6, 0))

        grid = ttk.Frame(fp); grid.pack(fill="x", pady=(8, 0))
        for c in range(3):
            grid.columnconfigure(c, weight=1)

        self.char_gender = LabeledCombobox(grid, "Gender",
            cfg.FACE_GENDERS, cfg.FACE_GENDERS[0],
            help_text="this-person-does-not-exist filter. 'Any' = random gender each fetch.")
        self.char_gender.grid(row=0, column=0, sticky="ew", padx=(0, 8), pady=4)

        self.char_age = LabeledCombobox(grid, "Age",
            cfg.FACE_AGES, cfg.FACE_AGES[0],
            help_text="Age bracket for face generation. Defaults can be inherited from step 1 (e.g., heroine age).")
        self.char_age.grid(row=0, column=1, sticky="ew", padx=(0, 8), pady=4)

        self.char_ethnicity = LabeledCombobox(grid, "Ethnicity",
            cfg.FACE_ETHNICITIES, cfg.FACE_ETHNICITIES[0],
            help_text="Ethnicity filter for face generation. 'Any' = random each fetch.")
        self.char_ethnicity.grid(row=0, column=2, sticky="ew", pady=4)

        self.char_distinctive = LabeledText(fp, "Distinctive features (optional)",
            height=2, width=40,
            placeholder="e.g., 'short grey hair', 'wears glasses', 'kind eyes, neutral business attire'",
            help_text="Extra description appended to pose-render prompts. Helpful to lock in identity beyond the seed face.")
        self.char_distinctive.pack(fill="x", pady=(8, 0))

        # Wardrobe row — values are populated dynamically per character role
        # in _load_character_into_form(); bootstrap with the default role here.
        wardrobe_row = ttk.Frame(fp); wardrobe_row.pack(fill="x", pady=(8, 0))
        wardrobe_row.columnconfigure(0, weight=1)
        wardrobe_row.columnconfigure(1, weight=1)
        _default_role = cfg.DEFAULT_ROLE
        self.char_outfit_style = LabeledCombobox(wardrobe_row, "Outfit style",
            cfg.outfit_labels_for_role(_default_role),
            cfg.default_outfit_label_for_role(_default_role),
            help_text="Wardrobe preset for this character. The list changes per character role (host / heroine / friend / expert / antagonist). The full description for the selected outfit is sent in the pose prompt.")
        self.char_outfit_style.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self.char_outfit_colors = LabeledCombobox(wardrobe_row, "Outfit colors",
            cfg.outfit_color_labels_for_role(_default_role),
            cfg.default_outfit_color_label_for_role(_default_role),
            help_text="Color palette for the outfit. The list changes per character role; the full description is sent in the pose prompt.")
        self.char_outfit_colors.grid(row=0, column=1, sticky="ew")

        fetch_row = ttk.Frame(fp); fetch_row.pack(fill="x", pady=(8, 0))
        get_face_btn = ttk.Button(fetch_row, text="🎲 Get face",
                                   command=self._get_face)
        get_face_btn.pack(side="left")
        Tooltip(get_face_btn,
            "Fetch a new random face matching the filters from this-person-does-not-exist. "
            "Click as many times as you like — each fetch replaces the candidate.")

        self.char_face_status_var = tk.StringVar(value="")
        ttk.Label(fp, textvariable=self.char_face_status_var,
                  foreground="grey", wraplength=460).pack(anchor="w", pady=(8, 0))

        # ── LEFT: poses ────────────────────────────────────────────
        pf = SectionFrame(left, "🎭 Generate poses")
        pf.pack(fill="x")
        ModelPicker(pf, kind="image", main_window=self.main,
                     label_text="Image model:").pack(anchor="w", pady=(0, 6))
        ttk.Label(pf,
            text="ℹ Face-seed fetching uses this-person-does-not-exist (above) — "
                 "this picker is for pose renders.",
            foreground="grey", font=("", 8, "italic")).pack(anchor="w", pady=(0, 4))

        pose_row = ttk.Frame(pf); pose_row.pack(fill="x")
        gen_poses_btn = ttk.Button(pose_row, text="🎭 Generate 4 poses",
                                    command=self._generate_poses)
        gen_poses_btn.pack(side="left")
        Tooltip(gen_poses_btn,
            "Generate all 4 poses (portrait, full-body, entrance, seated) via kie.ai using the chosen face as seed. "
            "Studio backdrops are mixed in for seated/entrance shots.")

        save_btn = ttk.Button(pose_row, text="💾 Save character",
                               command=self._save_character)
        save_btn.pack(side="left", padx=(8, 0))
        Tooltip(save_btn,
            "Persist current face parameters for this character to <project>/characters/<id>/params.json.")

        self.char_pose_status_var = tk.StringVar(value="")
        ttk.Label(pf, textvariable=self.char_pose_status_var,
                  foreground="grey", wraplength=460).pack(anchor="w", pady=(8, 0))

        # ── RIGHT: chosen face preview ─────────────────────────────
        fpr = SectionFrame(right, "👁 Chosen face")
        fpr.pack(fill="x", pady=(0, 10))
        self.char_face_canvas = tk.Canvas(fpr, height=180,
                                          background="#f4f4f4",
                                          highlightthickness=1,
                                          highlightbackground="#ddd")
        self.char_face_canvas.pack(fill="x")
        self._draw_face_placeholder()
        self.char_face_canvas.bind("<Button-1>",
            lambda _e: self._show_character_face_popup())
        self.char_face_canvas.configure(cursor="hand2")

        # ── RIGHT: 4 pose previews in one compact row ──────────────
        pose_prev = SectionFrame(right, "🎭 Pose previews")
        pose_prev.pack(fill="both", expand=True)
        pose_grid = ttk.Frame(pose_prev); pose_grid.pack(fill="x")
        for c in range(len(cfg.CHARACTER_POSES)):
            pose_grid.columnconfigure(c, weight=1)

        self.char_pose_canvases: dict = {}
        self._pose_thumb_refs: dict = {}
        for i, (key, label) in enumerate(cfg.CHARACTER_POSES):
            cell = ttk.Frame(pose_grid, padding=2)
            cell.grid(row=0, column=i, sticky="nsew", padx=2, pady=2)
            # Header row: label + retry button
            hdr = ttk.Frame(cell); hdr.pack(fill="x")
            ttk.Label(hdr, text=label, font=("", 8, "bold")).pack(
                side="left", anchor="w")
            retry_btn = ttk.Button(hdr, text="🔄", width=3,
                                    command=lambda k=key, l=label:
                                        self._retry_single_pose(k, l))
            retry_btn.pack(side="right")
            Tooltip(retry_btn,
                f"Re-render only the '{label}' pose. "
                f"Portrait re-renders from face seed; other poses re-use the "
                f"existing portrait as the identity reference. Previous file "
                f"becomes .v<N> backup.")
            canvas = tk.Canvas(cell, height=140, background="#f4f4f4",
                               highlightthickness=1, highlightbackground="#ddd")
            canvas.pack(fill="x")
            canvas.create_text(70, 70, text="🚧",
                               fill="#999", font=("", 11))
            self.char_pose_canvases[key] = canvas
            canvas.bind("<Button-1>",
                lambda _e, k=key: self._show_character_pose_popup(k))
            canvas.configure(cursor="hand2")

        # Auto-save bindings for Characters (per active character)
        for w in (self.char_gender, self.char_age, self.char_ethnicity,
                   self.char_distinctive, self.char_outfit_style,
                   self.char_outfit_colors):
            bind_autosave(w, lambda: self._schedule_silent_save("characters"))
        # When gender changes, the outfit catalog has to re-filter live.
        self.char_gender.combo.bind("<<ComboboxSelected>>",
            lambda _e: self._refilter_outfits_for_gender(), add="+")

        # Initialize from current form state + library picker values
        self._refresh_character_list()
        self._refresh_character_library_list()

    # ── CHARACTER LIBRARY (cross-project) ───────────────────────────
    def _character_library_entries(self) -> list:
        import library
        return library.list_entries("characters")

    def _format_character_library_label(self, entry: dict) -> str:
        p = entry.get("params") or {}
        nm = p.get("name") or entry.get("slug", "")
        role = p.get("role") or "?"
        age = p.get("age") or "?"
        return f"{nm} ({role}, {age}) · {entry.get('slug')}"

    def _refresh_character_library_list(self):
        if not hasattr(self, "char_lib_picker"):
            return
        entries = self._character_library_entries()
        labels = [self._format_character_library_label(e) for e in entries]
        self._character_library_cache = list(zip(labels, entries))
        self.char_lib_picker["values"] = labels
        # Preserve selection if still valid
        cur = self.char_lib_var.get()
        if cur not in labels:
            self.char_lib_var.set(labels[0] if labels else "")

    def _selected_library_character(self):
        cache = getattr(self, "_character_library_cache", [])
        cur = self.char_lib_var.get()
        return next((e for lbl, e in cache if lbl == cur), None)

    def _save_character_to_library(self):
        if not self.current_char_id:
            messagebox.showinfo("📚 Library",
                "Pick a cast member first.", parent=self)
            return
        params = self._collect_character_form()
        params["role"] = cfg.role_for_char_id(self.current_char_id)
        params["cast_slot"] = self.current_char_id
        display_name = next((c[2] for c in self._characters
                              if c[0] == self.current_char_id),
                             self.current_char_id) or self.current_char_id
        params["name"] = display_name

        # Collect files from the current project (only those that exist).
        files: dict = {}
        proj = self.main.current_project
        if proj:
            face = projects.character_face_path(proj, self.current_char_id)
            if face.exists():
                files[f"{display_name} - face{face.suffix}"] = face
            cd = projects.character_dir(proj, self.current_char_id)
            if cd.exists():
                versioned_re = re.compile(r"\.v\d+\.[a-z0-9]+$", re.IGNORECASE)
                for pose_key, _ in cfg.CHARACTER_POSES:
                    for p in cd.glob(f"{pose_key}.*"):
                        if not p.is_file() or versioned_re.search(p.name):
                            continue
                        if p.suffix.lower() not in (".png", ".jpg", ".jpeg", ".webp"):
                            continue
                        files[f"{display_name} - {pose_key}{p.suffix}"] = p
                        break

        import library
        try:
            entry_path = library.save_entry("characters", display_name, params, files)
        except Exception as e:
            messagebox.showerror("❌ Library save failed", str(e), parent=self)
            return
        self.char_pose_status_var.set(
            f"📚 Saved to library: {entry_path.name} ({len(files)} file(s))")
        self._refresh_character_library_list()

    def _delete_character_from_library(self):
        entry = self._selected_library_character()
        if not entry:
            messagebox.showinfo("📚 Library",
                "Pick a saved character to delete first.", parent=self)
            return
        nm = (entry.get("params") or {}).get("name") or entry["slug"]
        if not messagebox.askyesno("🗑 Delete from library",
            f"Permanently delete '{nm}' from the library?\n\n"
            f"This does NOT affect any open project.", parent=self):
            return
        import library
        library.delete_entry("characters", entry["slug"])
        self._refresh_character_library_list()
        self.char_pose_status_var.set(f"🗑 Deleted library entry: {entry['slug']}")

    def _load_character_from_library(self):
        if not self._require_project():
            return
        if not self.current_char_id:
            messagebox.showinfo("📚 Library",
                "Pick the cast slot to load into first.", parent=self)
            return
        entry = self._selected_library_character()
        if not entry:
            messagebox.showinfo("📚 Library",
                "Pick a saved character from the dropdown first.", parent=self)
            return
        params = entry.get("params") or {}
        files = entry.get("files") or {}

        # Apply params into the form (role gets overwritten by current cast role)
        target_role = cfg.role_for_char_id(self.current_char_id)
        new_form = {
            "gender": params.get("gender", "Any"),
            "age": params.get("age", "Any"),
            "ethnicity": params.get("ethnicity", "Any"),
            "distinctive": params.get("distinctive", ""),
            "outfit_style": params.get("outfit_style", ""),
            "outfit_colors": params.get("outfit_colors", ""),
        }
        # Stash in memory + apply via _load_character_into_form
        self._character_form_state[self.current_char_id] = new_form
        self._load_character_into_form(self.current_char_id)
        # Persist to project disk
        projects.save_character_params(
            self.main.current_project, self.current_char_id, new_form)

        # Copy media files. Names in the library are
        # "<display name> - <pose>.<ext>" or "<display name> - face.<ext>".
        proj = self.main.current_project
        cd = projects.character_dir(proj, self.current_char_id)
        cd.mkdir(parents=True, exist_ok=True)
        pose_keys = {pk for pk, _ in cfg.CHARACTER_POSES}
        present_poses: set = set()
        face_loaded = False
        for filename, src_path in files.items():
            # Parse " - <suffix>" from the filename
            stem = src_path.stem
            ext = src_path.suffix
            m = re.match(r"^.* - ([\w]+)$", stem)
            if not m:
                continue
            slot = m.group(1).lower()
            if slot == "face":
                target = projects.character_face_path(proj, self.current_char_id)
                # Rotate any existing face
                if target.exists():
                    n = 1
                    while (target.parent / f"face_seed.v{n}{target.suffix}").exists():
                        n += 1
                    try:
                        target.rename(target.parent / f"face_seed.v{n}{target.suffix}")
                    except OSError:
                        pass
                target.write_bytes(src_path.read_bytes())
                face_loaded = True
            elif slot in pose_keys:
                bytes_ = src_path.read_bytes()
                projects.save_character_pose_versioned(
                    proj, self.current_char_id, slot, bytes_, ext.lstrip("."))
                present_poses.add(slot)

        # Refresh UI thumbnails
        self._reload_pose_thumbnails()
        if face_loaded:
            try:
                face_p = projects.character_face_path(proj, self.current_char_id)
                cw = max(self.char_face_canvas.winfo_width(), 360)
                ch = max(self.char_face_canvas.winfo_height(), 180)
                self._face_photo_ref = display_image_path_on_canvas(
                    self.char_face_canvas, face_p, proj, cw, ch)
            except tk.TclError:
                pass

        self.main._refresh_all_tab_marks()

        # Offer to generate missing poses
        missing = [pk for pk, _ in cfg.CHARACTER_POSES if pk not in present_poses]
        nm = params.get("name") or self.current_char_id
        if missing:
            msg = (f"Loaded '{nm}' into cast slot '{self.current_char_id}'.\n\n"
                   f"Missing poses: {', '.join(missing)}.\n\n"
                   f"Generate them now?")
            self.char_pose_status_var.set(
                f"📚 Loaded {nm} ({len(present_poses)}/{len(pose_keys)} poses, "
                f"face={'✓' if face_loaded else '–'})")
            if messagebox.askyesno("📚 Library", msg, parent=self):
                self._generate_missing_poses(missing)
        else:
            self.char_pose_status_var.set(
                f"📚 Loaded {nm} into '{self.current_char_id}' "
                f"({len(present_poses)} poses, face={'✓' if face_loaded else '–'})")

    def _generate_missing_poses(self, missing: list):
        """Render the named poses using the existing face seed as identity ref.
        Reuses _generate_single_pose for in-studio context handling."""
        if not (self.main.current_project and self.current_char_id):
            return
        face_path = projects.character_face_path(
            self.main.current_project, self.current_char_id)
        if not face_path.exists():
            messagebox.showwarning("⚠ No face seed",
                "Cannot render missing poses without a face seed. "
                "Click 🎲 Get face first.", parent=self)
            return
        if not self._validate_studio_engine():
            return
        try:
            face_bytes = face_path.read_bytes()
        except OSError as e:
            messagebox.showerror("❌ Read failed", str(e), parent=self)
            return

        # If portrait is among the missing, render it FIRST as the identity
        # anchor, then run the rest with the new portrait as identity ref.
        if "portrait" in missing:
            self._generate_single_pose("portrait", "Portrait (CU)",
                                        identity_ref=face_bytes,
                                        char_id=self.current_char_id)
            remaining = [m for m in missing if m != "portrait"]
        else:
            # Use existing portrait if present, otherwise face seed.
            portrait_file = self._current_character_pose_path("portrait")
            identity = face_bytes
            if portrait_file and portrait_file.exists():
                try:
                    identity = portrait_file.read_bytes()
                except OSError:
                    pass
            remaining = missing
            for i, pose_key in enumerate(remaining):
                label = next((l for k, l in cfg.CHARACTER_POSES if k == pose_key),
                              pose_key)
                self.after(i * 1000,
                    lambda k=pose_key, l=label, p=identity,
                            c=self.current_char_id:
                        self._generate_single_pose(k, l, identity_ref=p, char_id=c))
            return

        # When portrait is being rendered first, defer the rest to
        # _on_portrait_anchor_done — but only the ones still missing. The
        # default 4-pose phase-2 path would re-render everything, so we
        # custom-schedule here using a 5s grace then identity from disk.
        for i, pose_key in enumerate(remaining):
            label = next((l for k, l in cfg.CHARACTER_POSES if k == pose_key),
                          pose_key)
            def _later(k=pose_key, l=label, c=self.current_char_id):
                pf = self._current_character_pose_path("portrait")
                ref = face_bytes
                if pf and pf.exists():
                    try:
                        ref = pf.read_bytes()
                    except OSError:
                        pass
                self._generate_single_pose(k, l, identity_ref=ref, char_id=c)
            self.after(5000 + i * 1000, _later)

    # ── CHARACTER ACTIONS ───────────────────────────────────────────
    def _resolve_characters_from_form(self, form: dict) -> list:
        """Build a (char_id, picker_label, display_name) list from step 1 cast fields."""
        chars = [
            ("host1",    f"🎙 Host 1 — {form.get('host1_name', 'Host 1')}",
                                                form.get("host1_name", "Host 1")),
            ("host2",    f"🎙 Host 2 — {form.get('host2_name', 'Host 2')}",
                                                form.get("host2_name", "Host 2")),
            ("heroine",  f"✨ Heroine — {form.get('heroine_name', 'Heroine')}",
                                                form.get("heroine_name", "Heroine")),
        ]
        friend_count = int(form.get("friend_count", 2) or 2)
        friends = form.get("friend_results", []) or []
        for i in range(friend_count):
            entry = friends[i] if i < len(friends) else ""
            first = entry.split(",")[0].strip() if entry else f"Friend {i+1}"
            chars.append((f"friend{i+1}", f"👯 Friend {i+1} — {first}", first))
        chars.append(("expert", "🥼 Expert", "Expert"))
        ant_label = form.get("antagonist_type", "Antagonist") or "Antagonist"
        chars.append(("antagonist", f"🦹 Antagonist — {ant_label[:30]}", ant_label))
        return chars

    def _refresh_character_list(self):
        try:
            form = self.main._collect_form()
        except Exception:
            form = {}
        self._characters = self._resolve_characters_from_form(form)
        labels = [c[1] for c in self._characters]
        self.char_picker["values"] = labels
        if not labels:
            return
        # Try to keep current selection if it still exists
        current_label = next(
            (l for cid, l, _ in self._characters if cid == self.current_char_id),
            labels[0],
        )
        self.char_picker_var.set(current_label)
        self.current_char_id = next(
            (cid for cid, l, _ in self._characters if l == current_label),
            self._characters[0][0],
        )
        self._load_character_into_form(self.current_char_id)

    def _label_to_char_id(self, label: str):
        return next((cid for cid, l, _ in self._characters if l == label), None)

    def _on_character_picked(self):
        new_id = self._label_to_char_id(self.char_picker_var.get())
        if not new_id or new_id == self.current_char_id:
            return
        # Save current to memory before switching
        if self.current_char_id:
            self._character_form_state[self.current_char_id] = self._collect_character_form()
        self.current_char_id = new_id
        self._load_character_into_form(new_id)

    def _collect_character_form(self) -> dict:
        return {
            "gender": self.char_gender.get(),
            "age": self.char_age.get(),
            "ethnicity": self.char_ethnicity.get(),
            "distinctive": self.char_distinctive.get(),
            "outfit_style": self.char_outfit_style.get(),
            "outfit_colors": self.char_outfit_colors.get(),
        }

    def _refilter_outfits_for_gender(self):
        """When the user flips Gender, swap the outfit dropdown values to the
        new gender-filtered list. If the current outfit slot isn't in the new
        list, pick a random replacement (per user's 2.4 answer)."""
        if not self.current_char_id:
            return
        role = cfg.role_for_char_id(self.current_char_id)
        gender = self.char_gender.get()
        new_labels = cfg.outfit_labels_for_role(role, gender)
        self.char_outfit_style.combo["values"] = new_labels
        if self.char_outfit_style.get() not in new_labels:
            import random
            self.char_outfit_style.set(random.choice(new_labels)
                                        if new_labels else "")

    def _load_character_into_form(self, char_id: str):
        # In-memory state first, then disk, then defaults
        data = self._character_form_state.get(char_id)
        if data is None and self.main.current_project:
            data = projects.load_character_params(self.main.current_project, char_id)
        if data is None:
            data = {}

        name = next((c[2] for c in self._characters if c[0] == char_id), "")
        self.char_name_var.set(name or "(unknown)")

        # Resolve role for this character → choose the right outfit catalog
        role = cfg.role_for_char_id(char_id)
        gender = data.get("gender") or cfg.FACE_GENDERS[0]
        outfit_labels = cfg.outfit_labels_for_role(role, gender)
        color_labels = cfg.outfit_color_labels_for_role(role)

        # Suppress auto-save while we set fields programmatically
        prev = self.main._autosave_paused
        self.main._autosave_paused = True
        try:
            self.char_gender.set(gender)
            self.char_age.set(data.get("age") or cfg.FACE_AGES[0])
            self.char_ethnicity.set(data.get("ethnicity") or cfg.FACE_ETHNICITIES[0])
            self.char_distinctive.set(data.get("distinctive") or "")

            # Swap dropdown values to this role's gender-filtered catalogs
            self.char_outfit_style.combo["values"] = outfit_labels
            self.char_outfit_colors.combo["values"] = color_labels

            # Pick saved value if still valid; else random from new list
            import random
            saved_outfit = data.get("outfit_style")
            if saved_outfit in outfit_labels:
                self.char_outfit_style.set(saved_outfit)
            else:
                self.char_outfit_style.set(random.choice(outfit_labels)
                                            if outfit_labels else "")

            saved_colors = data.get("outfit_colors")
            if saved_colors in color_labels:
                self.char_outfit_colors.set(saved_colors)
            else:
                self.char_outfit_colors.set(random.choice(color_labels)
                                             if color_labels else "")
        finally:
            self.main._autosave_paused = prev

        self.char_face_status_var.set("")
        self.char_pose_status_var.set("")
        # If a previously fetched face exists on disk, render it; otherwise placeholder.
        loaded = False
        if self.main.current_project:
            face_path = projects.character_face_path(
                self.main.current_project, char_id)
            if face_path.exists():
                try:
                    canvas_w = max(self.char_face_canvas.winfo_width(), 360)
                    canvas_h = max(self.char_face_canvas.winfo_height(), 180)
                    self._face_photo_ref = display_image_path_on_canvas(
                        self.char_face_canvas, face_path,
                        self.main.current_project, canvas_w, canvas_h)
                    self.char_face_status_var.set(f"💾 Loaded from {face_path}")
                    loaded = True
                except tk.TclError:
                    loaded = False
        if not loaded:
            self._face_photo_ref = None
            self._draw_face_placeholder()
        # Pose thumbnails — reload from disk for this character
        self._reload_pose_thumbnails()

    def _draw_face_placeholder(self):
        self.char_face_canvas.delete("all")
        self.char_face_canvas.create_text(
            230, 90,
            text="🚧 No face fetched yet\nClick 🎲 Get face",
            fill="#999", font=("", 10), justify="center",
        )

    def _get_face(self):
        if not self.current_char_id:
            return
        if not self._require_project():
            return

        gender = self.char_gender.get()
        age = self.char_age.get()
        ethnicity = self.char_ethnicity.get()
        char_id = self.current_char_id

        self.char_face_status_var.set(
            f"🔄 Fetching face — {gender} / {age} / {ethnicity}…")

        def worker():
            try:
                from face_client import PersonNotExistClient
                client = PersonNotExistClient()
                img_bytes = client.fetch_face(
                    gender=gender, age=age, ethnicity=ethnicity)
                # Persist to <project>/characters/<id>/face_seed.jpg
                path = projects.character_face_path(
                    self.main.current_project, char_id)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(img_bytes)
                try:
                    import thumbnails as _th
                    _th.ensure_thumbnail(self.main.current_project, path)
                except Exception:
                    pass
                self.after(0, lambda: self._on_face_fetched(img_bytes, path))
            except Exception as e:
                err = str(e)
                self.after(0, lambda: self.char_face_status_var.set(
                    f"❌ Fetch failed: {err[:240]}"))

        threading.Thread(target=worker, daemon=True).start()

    def _on_face_fetched(self, img_bytes: bytes, path):
        # Only render if the user hasn't switched to a different character
        # mid-fetch. (Path basename will still match current_char_id.)
        try:
            canvas_w = max(self.char_face_canvas.winfo_width(), 360)
            canvas_h = max(self.char_face_canvas.winfo_height(), 180)
        except tk.TclError:
            canvas_w, canvas_h = 460, 180
        self._face_photo_ref = display_image_path_on_canvas(
            self.char_face_canvas, path,
            self.main.current_project, canvas_w, canvas_h)
        self.char_face_status_var.set(f"✅ Face saved: {path}")
        self.main._refresh_all_tab_marks()

    def _save_character(self):
        if not self._require_project():
            return
        if not self.current_char_id:
            return
        projects.save_character_params(
            self.main.current_project,
            self.current_char_id,
            self._collect_character_form(),
        )
        self.char_pose_status_var.set(
            f"✅ Character '{self.current_char_id}' saved.")

    def _generate_poses(self):
        """Two-phase batch:
          Phase 1: portrait first (face_seed as identity reference).
          Phase 2: standing / entrance / seated, each using the FINISHED
                    portrait as the identity reference. For entrance and
                    seated, the matching studio shot is also sent as a
                    secondary reference (backdrop continuity).
        """
        if not self._require_project():
            return
        if not self.current_char_id:
            return

        # Block if no face seed yet — pose gen without identity lock = chaos
        face_path = projects.character_face_path(
            self.main.current_project, self.current_char_id)
        if not face_path.exists():
            messagebox.showwarning("⚠ No face seed",
                "Click 🎲 Get face first. Pose rendering needs the face seed "
                "as identity reference — without it each pose would have a "
                "different face.",
                parent=self)
            return
        if not self._validate_studio_engine():
            return

        # Persist params before render
        projects.save_character_params(
            self.main.current_project, self.current_char_id,
            self._collect_character_form())

        try:
            face_bytes = face_path.read_bytes()
        except OSError as e:
            messagebox.showerror("❌ Read failed",
                f"Could not read face seed: {e}", parent=self)
            return

        model_slug = self.main.image_model_slug_var.get()
        self.char_pose_status_var.set(
            f"🔄 Phase 1/2: portrait (face-anchor) via {model_slug}…")

        def worker_portrait():
            try:
                img_bytes, ext = self._do_pose_render("portrait", refs=[face_bytes])
                self.after(0,
                    lambda: self._on_portrait_anchor_done(img_bytes, ext))
            except Exception as e:
                err = str(e)
                self.after(0, lambda: self.char_pose_status_var.set(
                    f"❌ Portrait failed: {err[:240]}"))

        threading.Thread(target=worker_portrait, daemon=True).start()

    def _do_pose_render(self, pose_key: str, refs: list) -> tuple:
        """Pure render — build prompt and call API. Returns (img_bytes, ext)."""
        aspect = cfg.CHARACTER_POSE_ASPECTS.get(pose_key, "9:16")
        prompt = self._build_character_pose_prompt(pose_key, has_studio_ref=len(refs) > 1)
        model_slug = self.main.image_model_slug_var.get()
        from llm_clients import OpenRouterClient
        client = OpenRouterClient(
            self.main.settings.get("openrouter_api_key", ""), model_slug)
        return client.generate_image(prompt, model=model_slug,
            aspect_ratio=aspect, reference_image_bytes=refs)

    def _build_character_pose_prompt(self, pose_key: str,
                                       has_studio_ref: bool = False) -> str:
        data = self._collect_character_form()
        # Resolve display name from cast list
        display_name = next((c[2] for c in self._characters
                              if c[0] == self.current_char_id),
                             self.current_char_id)
        role = cfg.role_for_char_id(self.current_char_id or "")
        outfit_label = data.get("outfit_style") or cfg.default_outfit_label_for_role(role)
        colors_label = data.get("outfit_colors") or cfg.default_outfit_color_label_for_role(role)
        outfit_description = cfg.find_outfit_description(role, outfit_label)
        colors_description = cfg.find_outfit_color_description(role, colors_label)
        framing = cfg.CHARACTER_POSE_FRAMING.get(pose_key, "")

        # Two-phase wardrobe / identity language:
        #   Portrait phase: full outfit + concrete color palette (anchor).
        #   Other poses:   WARDROBE LOCK to the reference image (the portrait
        #                   already shows the outfit) — prevents outfit drift
        #                   across the 4-pose batch.
        if pose_key == "portrait":
            wardrobe_clause = (
                f"Wardrobe: {outfit_description}.\n"
                f"Color palette — use ONLY these colors and nothing else: "
                f"{colors_description}.")
            identity_lock_clause = (
                "IMPORTANT — IDENTITY LOCK: The first reference image is the "
                "person's face. Keep the face EXACTLY as in that reference — "
                "same features, same skin tone, same hairstyle, same age. "
                "Do not change facial structure or invent a different person.")
        else:
            wardrobe_clause = (
                "IMPORTANT — WARDROBE LOCK: The first reference image already "
                "shows this person fully dressed. Reproduce the outfit EXACTLY "
                "as in that reference — same garments, same cut, same fabric, "
                "same colors, same accessories. DO NOT invent new clothing, "
                "DO NOT change colors, DO NOT add or remove layers.\n"
                f"(For continuity: the outfit should match a {outfit_description}, "
                f"in the colors of {colors_description}.)")
            identity_lock_clause = (
                "IMPORTANT — IDENTITY LOCK: The first reference image is the "
                "same person already rendered. Keep the face, hair, and body "
                "EXACTLY as in that reference. Do not invent a different person.")

        studio_clause = ("STUDIO BACKDROP: The secondary reference image shows "
                         "the studio set. Place the character INTO that studio "
                         "context — same backdrop, same lighting, same furniture."
                         if has_studio_ref else "")
        return PROMPT_STORE.render("character_pose_prompt",
            character_name=display_name or "(unnamed)",
            role=role,
            gender=data.get("gender", "Any"),
            age=data.get("age", "Any"),
            ethnicity=data.get("ethnicity", "Any"),
            distinctive=data.get("distinctive", "") or "(none specified)",
            wardrobe_clause=wardrobe_clause,
            identity_lock_clause=identity_lock_clause,
            studio_clause=studio_clause,
            pose_framing=framing)

    def _on_portrait_anchor_done(self, img_bytes: bytes, ext: str):
        char_id = self.current_char_id
        path, archived = projects.save_character_pose_versioned(
            self.main.current_project, char_id, "portrait", img_bytes, ext)
        self._render_pose_thumbnail_path("portrait", path)
        msg = f"✅ Portrait anchor saved: {path.name}"
        if archived:
            msg += f"  (previous → {archived.name})"
        self.char_pose_status_var.set(
            f"{msg}. Phase 2/2: rendering 3 poses with portrait as identity ref (1s stagger)…")
        self.main._refresh_all_tab_marks()

        # Phase 2: 3 other poses, staggered, each using portrait as identity ref
        # + optional studio ref for in-studio poses (entrance / seated).
        remaining = [(k, l) for k, l in cfg.CHARACTER_POSES if k != "portrait"]
        for i, (key, label) in enumerate(remaining):
            self.after(i * 1000,
                lambda k=key, l=label, p=img_bytes, c=char_id:
                    self._generate_single_pose(k, l, identity_ref=p, char_id=c))

    def _retry_single_pose(self, pose_key: str, label: str):
        """Re-render exactly one pose, leaving the others alone.

          • Portrait: face seed is the identity reference (same as phase-1 path).
          • Other poses: use the existing portrait as identity ref (+ studio
            for entrance/seated, per CHARACTER_POSE_STUDIO_REF).

        Saves via the versioned helper so the previous image becomes a .v<N>
        backup automatically. No-op with a friendly warning if prerequisites
        are missing."""
        if not self._require_project():
            return
        if not self.current_char_id:
            return
        if not self._validate_studio_engine():
            return

        proj = self.main.current_project
        char_id = self.current_char_id

        if pose_key == "portrait":
            face_path = projects.character_face_path(proj, char_id)
            if not face_path.exists():
                messagebox.showwarning("⚠ No face seed",
                    "Click 🎲 Get face first — the portrait needs the face seed "
                    "as identity reference.", parent=self)
                return
            try:
                face_bytes = face_path.read_bytes()
            except OSError as e:
                messagebox.showerror("❌ Read failed",
                    f"Could not read face seed: {e}", parent=self)
                return
            # Persist current outfit/colors before render (so they end up in prompt)
            projects.save_character_params(
                proj, char_id, self._collect_character_form())
            self.char_pose_status_var.set(
                f"🔄 Re-rendering {label} (face-anchor)…")

            def worker():
                try:
                    img_bytes, ext = self._do_pose_render("portrait", refs=[face_bytes])
                    self.after(0, lambda: self._on_pose_done(
                        char_id, "portrait", label, img_bytes, ext))
                except Exception as e:
                    err = str(e)
                    self.after(0, lambda: self.char_pose_status_var.set(
                        f"❌ {label} retry failed: {err[:240]}"))
            threading.Thread(target=worker, daemon=True).start()
            return

        # Non-portrait retry — needs an existing portrait as identity ref.
        portrait_path = self._current_character_pose_path("portrait")
        if not portrait_path or not portrait_path.exists():
            messagebox.showwarning("⚠ No portrait yet",
                "Generate the Portrait pose first — other poses re-use it as "
                "the identity reference (and wardrobe lock).", parent=self)
            return
        try:
            identity = portrait_path.read_bytes()
        except OSError as e:
            messagebox.showerror("❌ Read failed",
                f"Could not read portrait: {e}", parent=self)
            return
        projects.save_character_params(
            proj, char_id, self._collect_character_form())
        # Reuse the existing single-pose render path — it already handles
        # the studio secondary reference for entrance / seated.
        self._generate_single_pose(pose_key, label,
            identity_ref=identity, char_id=char_id)

    def _generate_single_pose(self, pose_key: str, label: str,
                                identity_ref: bytes, char_id: str):
        """Render one pose. identity_ref = portrait bytes (face identity lock).
        For poses with a studio reference mapping, also include that studio
        shot as secondary reference."""
        refs = [identity_ref]
        studio_ref_key = cfg.CHARACTER_POSE_STUDIO_REF.get(pose_key)
        if studio_ref_key and self.main.current_project:
            studio_file = (self.main.current_project / "studio"
                            / f"{studio_ref_key}.png")
            # Try other extensions too
            if not studio_file.exists():
                versioned_re = re.compile(rf"^{re.escape(studio_ref_key)}\.v\d+\.")
                studio_dir = self.main.current_project / "studio"
                if studio_dir.exists():
                    studio_file = next((p for p in studio_dir.glob(f"{studio_ref_key}.*")
                                          if p.is_file() and not versioned_re.match(p.name)),
                                         None)
            if studio_file and studio_file.exists():
                try:
                    refs.append(studio_file.read_bytes())
                except OSError:
                    pass

        ref_kind = "id+studio" if len(refs) > 1 else "id-only"
        self.char_pose_status_var.set(
            f"🔄 {label} ({ref_kind})…")

        def worker():
            try:
                img_bytes, ext = self._do_pose_render(pose_key, refs=refs)
                self.after(0, lambda: self._on_pose_done(
                    char_id, pose_key, label, img_bytes, ext))
            except Exception as e:
                err = str(e)
                self.after(0, lambda: self.char_pose_status_var.set(
                    f"❌ {label} failed: {err[:240]}"))

        threading.Thread(target=worker, daemon=True).start()

    def _on_pose_done(self, char_id: str, pose_key: str, label: str,
                       img_bytes: bytes, ext: str):
        path, archived = projects.save_character_pose_versioned(
            self.main.current_project, char_id, pose_key, img_bytes, ext)
        # Only render thumbnail if we're still on the same character — user
        # could have switched mid-batch.
        if self.current_char_id == char_id:
            self._render_pose_thumbnail_path(pose_key, path)
        msg = f"✅ {label}: {path.name}"
        if archived:
            msg += f"  (previous → {archived.name})"
        self.char_pose_status_var.set(msg)
        self.main._refresh_all_tab_marks()

    def apply_characters(self, project_path):
        """Populate in-memory character state from disk. Called by MainWindow on project open."""
        self._character_form_state = {}
        if not project_path:
            return
        for cid in projects.list_characters_with_params(project_path):
            self._character_form_state[cid] = projects.load_character_params(project_path, cid)
        # Refresh form so newly-loaded values appear
        if self.current_char_id:
            self._load_character_into_form(self.current_char_id)

    # ── 👥 Audience sub-tab ─────────────────────────────────────────
    def _build_audience_tab(self, parent):
        # Library row (cross-project saved audiences)
        lib_row = ttk.Frame(parent); lib_row.pack(fill="x", pady=(0, 6))
        ttk.Label(lib_row, text="📚 Library:").pack(side="left")
        HelpIcon(lib_row,
            "App-wide saved audiences from ~/.talkshow_generator/audiences/. "
            "Save the current crowd (params + all 4 reaction images) into the "
            "library, load a saved audience into the project, or delete an entry."
        ).pack(side="left")
        self.aud_lib_var = tk.StringVar()
        self.aud_lib_picker = ttk.Combobox(lib_row,
            textvariable=self.aud_lib_var, state="readonly", width=40)
        self.aud_lib_picker.pack(side="left", padx=(8, 4))
        load_lib_btn = ttk.Button(lib_row, text="📂 Load",
                                   command=self._load_audience_from_library)
        load_lib_btn.pack(side="left", padx=(0, 4))
        Tooltip(load_lib_btn,
            "Load the selected saved audience into the project. Existing audience.json "
            "and pose PNGs are rotated as .v<N> backups.")
        save_lib_btn = ttk.Button(lib_row, text="💾 Save to library",
                                   command=self._save_audience_to_library)
        save_lib_btn.pack(side="left", padx=(0, 4))
        Tooltip(save_lib_btn,
            "Save the current audience (composition + all 4 reaction images) "
            "into the cross-project library. Requires an Audience name and "
            "all 4 reactions to be already rendered.")
        del_lib_btn = ttk.Button(lib_row, text="🗑 Delete",
                                  command=self._delete_audience_from_library)
        del_lib_btn.pack(side="left")
        Tooltip(del_lib_btn,
            "Permanently delete the currently selected library entry. "
            "Open projects are not affected.")

        cols = ttk.Frame(parent); cols.pack(fill="both", expand=True)
        cols.columnconfigure(0, weight=1)
        cols.columnconfigure(1, weight=1)
        left = ttk.Frame(cols); left.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        right = ttk.Frame(cols); right.grid(row=0, column=1, sticky="nsew")

        # ── LEFT: composition ──────────────────────────────────────
        cf = SectionFrame(left, "👥 Crowd composition")
        cf.pack(fill="x", pady=(0, 10))

        # Audience name (needed for library save slug)
        name_row = ttk.Frame(cf); name_row.pack(fill="x", pady=(0, 6))
        self.aud_name = LabeledEntry(name_row, "Audience name", "",
            help_text="Short name for this audience (used as the library slug when you 💾 Save to library). "
                      "E.g., 'Daytime weight-loss crowd' or 'European morning TV mixed'.")
        self.aud_name.pack(fill="x")

        grid = ttk.Frame(cf); grid.pack(fill="x")
        for c in range(2):
            grid.columnconfigure(c, weight=1)

        self.aud_gender = LabeledCombobox(grid, "Gender ratio",
            cfg.AUDIENCE_GENDER_RATIOS, cfg.AUDIENCE_GENDER_RATIOS[0],
            help_text="Approximate gender split of the studio audience. Mostly-female matches classic daytime talk demographics.")
        self.aud_gender.grid(row=0, column=0, sticky="ew", padx=(0, 8), pady=4)

        self.aud_ethnic = LabeledCombobox(grid, "Ethnic mix",
            cfg.AUDIENCE_ETHNIC_MIXES, cfg.AUDIENCE_ETHNIC_MIXES[1],
            help_text="Dominant ethnic composition. 'Mixed' is most flexible and reads as US national TV.")
        self.aud_ethnic.grid(row=0, column=1, sticky="ew", pady=4)

        self.aud_age = LabeledCombobox(grid, "Age range",
            cfg.AUDIENCE_AGE_RANGES, cfg.AUDIENCE_AGE_RANGES[3],
            help_text="Age bracket the crowd should fall into. 'Mixed' = full daytime-TV spread.")
        self.aud_age.grid(row=1, column=0, sticky="ew", padx=(0, 8), pady=4)

        self.aud_size = LabeledCombobox(grid, "Crowd size",
            cfg.AUDIENCE_CROWD_SIZES, cfg.AUDIENCE_CROWD_SIZES[1],
            help_text="Approximate visible audience size. Affects wide-shot density and applause-volume cues.")
        self.aud_size.grid(row=1, column=1, sticky="ew", pady=4)

        self.aud_dress = LabeledCombobox(grid, "Dress code",
            cfg.AUDIENCE_DRESS_CODES, cfg.AUDIENCE_DRESS_CODES[0],
            help_text="What the crowd is wearing. 'Casual' fits daytime US format; 'dressy daytime' for European morning TV.")
        self.aud_dress.grid(row=2, column=0, sticky="ew", padx=(0, 8), pady=4)

        self.aud_energy = LabeledCombobox(grid, "Energy baseline",
            cfg.AUDIENCE_ENERGY_BASELINES, cfg.AUDIENCE_ENERGY_BASELINES[1],
            help_text="Default emotional intensity. 'Polite' = quiet attentive baseline; 'rowdy' = primed to interrupt with reactions.")
        self.aud_energy.grid(row=2, column=1, sticky="ew", pady=4)

        self.aud_extra = LabeledText(cf, "Extra description (optional)",
            height=3, width=40,
            placeholder="e.g., 'a few visible journalists with notepads', 'audience holding pink ribbons for breast cancer awareness'",
            help_text="Free-form additions to the audience render prompt. Applies to all 4 reactions.")
        self.aud_extra.pack(fill="x", pady=(8, 0))

        # Auto-save bindings for Audience
        for w in (self.aud_name, self.aud_gender, self.aud_ethnic, self.aud_age,
                   self.aud_size, self.aud_dress, self.aud_energy, self.aud_extra):
            bind_autosave(w, lambda: self._schedule_silent_save("audience"))

        # ── LEFT: render reactions ─────────────────────────────────
        rf = SectionFrame(left, "🎬 Render reactions")
        rf.pack(fill="x")
        ModelPicker(rf, kind="image", main_window=self.main,
                     label_text="Image model:",
                     exclude_slugs=["recraft/recraft-v4.1-vector"]
                     ).pack(anchor="w", pady=(0, 6))
        ttk.Label(rf,
            text="ℹ Two-phase batch: 'Attentive' renders first as crowd anchor; "
                 "the other 3 reactions lock to it so the SAME faces & clothes "
                 "appear across all 4 shots.",
            foreground="grey", font=("", 8, "italic"),
            wraplength=420).pack(anchor="w", pady=(0, 4))

        action_row = ttk.Frame(rf); action_row.pack(fill="x", pady=(2, 0))
        all_btn = ttk.Button(action_row, text="🎭 Generate 4 reactions",
                              command=self._generate_all_audience_poses)
        all_btn.pack(side="left")
        Tooltip(all_btn,
            "Two-phase batch render: phase 1 = attentive anchor, phase 2 = "
            "applauding + laughing + disapproving with attentive as crowd-lock "
            "reference. ~4× a single render in cost.")

        save_btn = ttk.Button(action_row, text="💾 Save audience",
                               command=self._save_audience)
        save_btn.pack(side="left", padx=(8, 0))
        Tooltip(save_btn,
            "Persist current audience composition to <project>/audience/audience.json "
            "without rendering.")

        self.aud_status_var = tk.StringVar(value="")
        ttk.Label(rf, textvariable=self.aud_status_var,
                  foreground="grey", wraplength=460).pack(anchor="w", pady=(8, 0))

        # ── RIGHT: 4 reaction previews in one compact row ──────────
        prev = SectionFrame(right, "👁 Reaction previews")
        prev.pack(fill="both", expand=True)

        thumb_grid = ttk.Frame(prev); thumb_grid.pack(fill="x")
        for c in range(len(cfg.AUDIENCE_POSES)):
            thumb_grid.columnconfigure(c, weight=1)

        self.aud_pose_canvases: dict = {}
        self._aud_thumb_refs: dict = {}
        for i, (key, label) in enumerate(cfg.AUDIENCE_POSES):
            cell = ttk.Frame(thumb_grid, padding=2)
            cell.grid(row=0, column=i, sticky="nsew", padx=2, pady=2)
            hdr = ttk.Frame(cell); hdr.pack(fill="x")
            ttk.Label(hdr, text=label, font=("", 8, "bold")).pack(
                side="left", anchor="w")
            retry_btn = ttk.Button(hdr, text="🔄", width=3,
                                    command=lambda k=key, l=label:
                                        self._retry_audience_pose(k, l))
            retry_btn.pack(side="right")
            Tooltip(retry_btn,
                f"Re-render only the '{label}' reaction. "
                f"For attentive: re-renders the anchor from scratch. "
                f"For others: reuses the existing attentive shot as the "
                f"crowd-lock reference. Previous file becomes .v<N> backup.")
            canvas = tk.Canvas(cell, height=140, background="#f4f4f4",
                               highlightthickness=1, highlightbackground="#ddd")
            canvas.pack(fill="x")
            canvas.create_text(70, 70, text="🚧",
                               fill="#999", font=("", 11))
            self.aud_pose_canvases[key] = canvas
            canvas.bind("<Button-1>",
                lambda _e, k=key: self._show_audience_pose_popup(k))
            canvas.configure(cursor="hand2")

        # Populate library picker on first build
        self._refresh_audience_library_list()

    # ── AUDIENCE ACTIONS ────────────────────────────────────────────
    def _collect_audience(self) -> dict:
        return {
            "name": self.aud_name.get(),
            "gender_ratio": self.aud_gender.get(),
            "ethnic_mix": self.aud_ethnic.get(),
            "age_range": self.aud_age.get(),
            "crowd_size": self.aud_size.get(),
            "dress_code": self.aud_dress.get(),
            "energy_baseline": self.aud_energy.get(),
            "extra_description": self.aud_extra.get(),
        }

    def apply_audience(self, data: dict):
        if data:
            if data.get("name"):            self.aud_name.set(data["name"])
            if data.get("gender_ratio"):    self.aud_gender.set(data["gender_ratio"])
            if data.get("ethnic_mix"):      self.aud_ethnic.set(data["ethnic_mix"])
            if data.get("age_range"):       self.aud_age.set(data["age_range"])
            if data.get("crowd_size"):      self.aud_size.set(data["crowd_size"])
            if data.get("dress_code"):      self.aud_dress.set(data["dress_code"])
            if data.get("energy_baseline"): self.aud_energy.set(data["energy_baseline"])
            if data.get("extra_description"):
                self.aud_extra.set(data["extra_description"])
        if self.main.current_project:
            self._reload_audience_thumbnails()
        self._refresh_audience_library_list()

    def _save_audience(self):
        if not self._require_project():
            return
        path = projects.save_audience(self.main.current_project, self._collect_audience())
        self.aud_status_var.set(f"✅ Audience saved: {path}")

    def _build_audience_composition_text(self, data: dict) -> str:
        return (f"  • Gender ratio: {data.get('gender_ratio', '')}\n"
                f"  • Ethnic mix: {data.get('ethnic_mix', '')}\n"
                f"  • Age range: {data.get('age_range', '')}\n"
                f"  • Crowd size: {data.get('crowd_size', '')} "
                  f"(make the visible crowd density match this)\n"
                f"  • Dress code: {data.get('dress_code', '')}\n"
                f"  • Energy baseline: {data.get('energy_baseline', '')}")

    def _build_audience_studio_context(self) -> str:
        try:
            studio = self._collect_studio()
        except Exception:
            studio = {}
        try:
            brand = self._collect_brand()
        except Exception:
            brand = {}
        pal = brand.get("palette", {}) or {}
        bits = []
        if studio.get("era"):       bits.append(f"era: {studio['era']}")
        if studio.get("palette"):   bits.append(f"color palette: {studio['palette']}")
        if studio.get("lighting"):  bits.append(f"lighting: {studio['lighting']}")
        if studio.get("floor"):     bits.append(f"floor: {studio['floor']}")
        if pal.get("primary"):      bits.append(f"brand primary {pal['primary']}")
        if pal.get("secondary"):    bits.append(f"brand secondary {pal['secondary']}")
        if pal.get("accent"):       bits.append(f"brand accent {pal['accent']}")
        return ", ".join(bits) or "modern talk-show studio styling"

    def _build_audience_prompt(self, pose_key: str,
                                 has_crowd_anchor: bool = False) -> str:
        data = self._collect_audience()
        composition = self._build_audience_composition_text(data)
        studio_ctx = self._build_audience_studio_context()
        framing = cfg.AUDIENCE_POSE_FRAMING.get(pose_key, "")
        if has_crowd_anchor:
            crowd_lock_clause = (
                "IMPORTANT — CROWD LOCK: The reference image already shows this "
                "audience. Reproduce the SAME crowd EXACTLY — same faces, same "
                "clothing, same seating positions, same lighting, same camera "
                "framing. Only change the expressions and body language to match "
                "the reaction described below. DO NOT introduce new people, DO NOT "
                "rearrange the rows, DO NOT change the wardrobe.")
        else:
            crowd_lock_clause = ""
        extra = (data.get("extra_description") or "").strip()
        extra_clause = f"Extra: {extra}" if extra else ""
        return PROMPT_STORE.render("audience_pose_prompt",
            composition=composition,
            studio_context=studio_ctx,
            crowd_lock_clause=crowd_lock_clause,
            pose_framing=framing,
            extra_description=extra_clause)

    def _validate_audience_engine(self) -> bool:
        # Same constraint as Studio: openrouter + raster model only.
        return self._validate_studio_engine()

    def _do_audience_render(self, pose_key: str, refs: list) -> tuple:
        prompt = self._build_audience_prompt(pose_key,
                                              has_crowd_anchor=len(refs) >= 1)
        model_slug = self.main.image_model_slug_var.get()
        from llm_clients import OpenRouterClient
        client = OpenRouterClient(
            self.main.settings.get("openrouter_api_key", ""), model_slug)
        return client.generate_image(prompt, model=model_slug,
            aspect_ratio=cfg.AUDIENCE_POSE_ASPECT,
            reference_image_bytes=refs or None)

    def _generate_all_audience_poses(self):
        """Two-phase batch:
            Phase 1 — render 'attentive' from text only (anchor for crowd
                       composition).
            Phase 2 — render the 3 reactions staggered, each using the
                       attentive anchor as reference (crowd lock)."""
        if not self._require_project():
            return
        if not self._validate_audience_engine():
            return
        projects.save_audience(self.main.current_project, self._collect_audience())

        model_slug = self.main.image_model_slug_var.get()
        self.aud_status_var.set(
            f"🔄 Phase 1/2: rendering Attentive anchor via {model_slug}…")

        def worker_anchor():
            try:
                img_bytes, ext = self._do_audience_render("attentive", refs=[])
                self.after(0,
                    lambda: self._on_audience_anchor_done(img_bytes, ext))
            except Exception as e:
                err = str(e)
                self.after(0, lambda: self.aud_status_var.set(
                    f"❌ Attentive anchor failed: {err[:240]}"))

        threading.Thread(target=worker_anchor, daemon=True).start()

    def _on_audience_anchor_done(self, img_bytes: bytes, ext: str):
        path, archived = projects.save_audience_pose_versioned(
            self.main.current_project, "attentive", img_bytes, ext)
        self._render_audience_thumbnail_path("attentive", path)
        msg = f"✅ Attentive anchor: {path.name}"
        if archived:
            msg += f"  (previous → {archived.name})"
        self.aud_status_var.set(
            f"{msg}. Phase 2/2: rendering 3 reactions with attentive as "
            f"crowd-lock reference (1s stagger)…")
        self.main._refresh_all_tab_marks()

        remaining = [(k, l) for k, l in cfg.AUDIENCE_POSES if k != "attentive"]
        for i, (key, label) in enumerate(remaining):
            self.after(i * 1000,
                lambda k=key, l=label, p=img_bytes:
                    self._generate_single_audience_reaction(k, l, anchor_ref=p))

    def _generate_single_audience_reaction(self, pose_key: str, label: str,
                                              anchor_ref: bytes):
        """Render one non-anchor reaction with the attentive shot as crowd ref."""
        self.aud_status_var.set(f"🔄 {label} (crowd-lock)…")

        def worker():
            try:
                img_bytes, ext = self._do_audience_render(pose_key, refs=[anchor_ref])
                self.after(0, lambda: self._on_audience_pose_done(
                    pose_key, label, img_bytes, ext))
            except Exception as e:
                err = str(e)
                self.after(0, lambda: self.aud_status_var.set(
                    f"❌ {label} failed: {err[:240]}"))

        threading.Thread(target=worker, daemon=True).start()

    def _on_audience_pose_done(self, pose_key: str, label: str,
                                 img_bytes: bytes, ext: str):
        path, archived = projects.save_audience_pose_versioned(
            self.main.current_project, pose_key, img_bytes, ext)
        self._render_audience_thumbnail_path(pose_key, path)
        msg = f"✅ {label}: {path.name}"
        if archived:
            msg += f"  (previous → {archived.name})"
        self.aud_status_var.set(msg)
        self.main._refresh_all_tab_marks()

    def _retry_audience_pose(self, pose_key: str, label: str):
        """Re-render exactly one audience reaction.
          • attentive: re-renders the anchor from scratch (text only).
          • others:   re-uses the existing attentive shot as crowd-lock ref."""
        if not self._require_project():
            return
        if not self._validate_audience_engine():
            return
        projects.save_audience(self.main.current_project, self._collect_audience())

        if pose_key == "attentive":
            self.aud_status_var.set(f"🔄 Re-rendering {label} (anchor)…")
            def worker():
                try:
                    img_bytes, ext = self._do_audience_render("attentive", refs=[])
                    self.after(0, lambda: self._on_audience_pose_done(
                        "attentive", label, img_bytes, ext))
                except Exception as e:
                    err = str(e)
                    self.after(0, lambda: self.aud_status_var.set(
                        f"❌ {label} retry failed: {err[:240]}"))
            threading.Thread(target=worker, daemon=True).start()
            return

        # Non-attentive retry needs an existing attentive anchor.
        anchor_path = self._current_audience_pose_path("attentive")
        if not anchor_path or not anchor_path.exists():
            messagebox.showwarning("⚠ No attentive anchor",
                "Generate the Attentive reaction first — other reactions "
                "re-use it as the crowd-lock reference.", parent=self)
            return
        try:
            anchor_bytes = anchor_path.read_bytes()
        except OSError as e:
            messagebox.showerror("❌ Read failed",
                f"Could not read attentive anchor: {e}", parent=self)
            return
        self._generate_single_audience_reaction(pose_key, label,
                                                  anchor_ref=anchor_bytes)

    # ── Audience thumbnail + popup helpers ──────────────────────────
    def _render_audience_thumbnail_path(self, pose_key: str, original_path):
        canvas = self.aud_pose_canvases.get(pose_key)
        if not canvas:
            return
        try:
            cw = max(canvas.winfo_width(), 140)
            ch = max(canvas.winfo_height(), 110)
        except tk.TclError:
            cw, ch = 140, 110
        self._aud_thumb_refs[pose_key] = display_image_path_on_canvas(
            canvas, original_path, self.main.current_project, cw, ch)

    def _reload_audience_thumbnails(self):
        ad = self.main.current_project / "audience"
        if not ad.exists():
            return
        versioned_re = re.compile(r"\.v\d+\.[a-z0-9]+$", re.IGNORECASE)
        for key, _label in cfg.AUDIENCE_POSES:
            files = [p for p in ad.glob(f"{key}.*")
                     if p.is_file() and not versioned_re.search(p.name)
                     and p.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp")]
            if not files:
                continue
            self._render_audience_thumbnail_path(key, files[0])

    def _current_audience_pose_path(self, pose_key: str):
        if not self.main.current_project:
            return None
        ad = self.main.current_project / "audience"
        if not ad.exists():
            return None
        versioned_re = re.compile(rf"^{re.escape(pose_key)}\.v\d+\.")
        return next((p for p in ad.glob(f"{pose_key}.*")
                      if p.is_file() and not versioned_re.match(p.name)
                      and p.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp")),
                     None)

    def _show_audience_pose_popup(self, pose_key: str):
        path = self._current_audience_pose_path(pose_key)
        if path:
            show_image_popup(self, path)

    # ── AUDIENCE LIBRARY (cross-project) ────────────────────────────
    def _audience_library_entries(self) -> list:
        import library
        return library.list_entries("audiences")

    def _format_audience_library_label(self, entry: dict) -> str:
        p = entry.get("params") or {}
        nm = p.get("name") or entry.get("slug", "")
        size = p.get("crowd_size") or "?"
        dress = p.get("dress_code") or "?"
        return f"{nm} ({size}, {dress}) · {entry.get('slug')}"

    def _refresh_audience_library_list(self):
        if not hasattr(self, "aud_lib_picker"):
            return
        entries = self._audience_library_entries()
        labels = [self._format_audience_library_label(e) for e in entries]
        self._audience_library_cache = list(zip(labels, entries))
        self.aud_lib_picker["values"] = labels
        cur = self.aud_lib_var.get()
        if cur not in labels:
            self.aud_lib_var.set(labels[0] if labels else "")

    def _selected_library_audience(self):
        cache = getattr(self, "_audience_library_cache", [])
        cur = self.aud_lib_var.get()
        return next((e for lbl, e in cache if lbl == cur), None)

    def _save_audience_to_library(self):
        if not self._require_project():
            return
        params = self._collect_audience()
        name = (params.get("name") or "").strip()
        if not name:
            messagebox.showwarning("📚 Library",
                "Type an Audience name first — it's used as the library slug.",
                parent=self)
            return
        # All 4 reactions must be rendered (per strict ✅ predicate too).
        proj = self.main.current_project
        ad = proj / "audience"
        versioned_re = re.compile(r"\.v\d+\.[a-z0-9]+$", re.IGNORECASE)
        files: dict = {}
        missing: list = []
        for pose_key, _label in cfg.AUDIENCE_POSES:
            cand = [p for p in ad.glob(f"{pose_key}.*")
                    if p.is_file() and not versioned_re.search(p.name)
                    and p.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp")]
            if not cand:
                missing.append(pose_key)
                continue
            src = cand[0]
            files[f"{name} - {pose_key}{src.suffix}"] = src
        if missing:
            messagebox.showwarning("📚 Library",
                "Cannot save — missing reaction(s): " + ", ".join(missing) + ".\n\n"
                "Render all 4 first (use '🎭 Generate 4 reactions').",
                parent=self)
            return

        import library
        try:
            entry_path = library.save_entry("audiences", name, params, files)
        except Exception as e:
            messagebox.showerror("❌ Library save failed", str(e), parent=self)
            return
        self.aud_status_var.set(
            f"📚 Saved audience to library: {entry_path.name} (4 reactions)")
        self._refresh_audience_library_list()

    def _delete_audience_from_library(self):
        entry = self._selected_library_audience()
        if not entry:
            messagebox.showinfo("📚 Library",
                "Pick a saved audience to delete first.", parent=self)
            return
        nm = (entry.get("params") or {}).get("name") or entry["slug"]
        if not messagebox.askyesno("🗑 Delete from library",
            f"Permanently delete audience '{nm}' from the library?\n\n"
            f"This does NOT affect any open project.", parent=self):
            return
        import library
        library.delete_entry("audiences", entry["slug"])
        self._refresh_audience_library_list()
        self.aud_status_var.set(f"🗑 Deleted library entry: {entry['slug']}")

    def _load_audience_from_library(self):
        if not self._require_project():
            return
        entry = self._selected_library_audience()
        if not entry:
            messagebox.showinfo("📚 Library",
                "Pick a saved audience from the dropdown first.", parent=self)
            return
        params = entry.get("params") or {}
        files = entry.get("files") or {}

        # Apply params (silent so autosave doesn't fire mid-load)
        prev = self.main._autosave_paused
        self.main._autosave_paused = True
        try:
            self.apply_audience(params)
        finally:
            self.main._autosave_paused = prev
        # Persist audience.json (apply_audience doesn't save by itself)
        projects.save_audience(self.main.current_project, self._collect_audience())

        # Copy reaction files, rotating any existing as .v<N>
        loaded = []
        pose_keys = {k for k, _ in cfg.AUDIENCE_POSES}
        for filename, src_path in files.items():
            stem = src_path.stem
            m = re.match(r"^.* - ([\w]+)$", stem)
            if not m:
                continue
            pose_key = m.group(1).lower()
            if pose_key not in pose_keys:
                continue
            try:
                content = src_path.read_bytes()
            except OSError:
                continue
            projects.save_audience_pose_versioned(
                self.main.current_project, pose_key, content,
                src_path.suffix.lstrip("."))
            loaded.append(pose_key)

        self._reload_audience_thumbnails()
        self.main._refresh_all_tab_marks()
        self.aud_status_var.set(
            f"📚 Loaded audience '{params.get('name') or entry['slug']}' "
            f"({len(loaded)}/4 reactions)")

    # ── 🔊 Voices sub-tab ───────────────────────────────────────────
    def _build_voices_tab(self, parent):
        # ── TOP: cast picker ───────────────────────────────────────
        top = ttk.Frame(parent); top.pack(fill="x", pady=(0, 6))
        ttk.Label(top, text="Cast member:").pack(side="left")
        HelpIcon(top,
            "Pick a cast member to assign an ElevenLabs voice to. Voices are "
            "filtered by the character's gender (set on the Characters tab). "
            "The last entry is a voice-only Voiceover/Narrator slot — used for "
            "lines parsed with speaker NARRATOR/VOICEOVER/VO/etc."
        ).pack(side="left")
        self.voice_picker_var = tk.StringVar()
        self.voice_picker = ttk.Combobox(top, textvariable=self.voice_picker_var,
                                          state="readonly", width=48)
        self.voice_picker.pack(side="left", padx=(8, 8))
        self.voice_picker.bind("<<ComboboxSelected>>",
                                lambda _e: self._on_voice_character_picked())
        refresh_btn = ttk.Button(top, text="🔄 Refresh from step 1",
                                  command=self._refresh_voices_list)
        refresh_btn.pack(side="left")
        Tooltip(refresh_btn,
            "Re-read cast names from the step 1 form. Run after editing hosts / heroine / friends / antagonist names.")

        # ── MAIN: nested resizable PanedWindows ────────────────────
        # Outer horizontal: LEFT (portrait+settings) | RIGHT (voice+lines).
        # tk.PanedWindow (not ttk) is used because it lets us style the sash
        # explicitly — visible grip handle, raised relief, distinct color.
        sash_kw = dict(
            sashwidth=8, sashrelief="raised",
            background="#8a8a8a", showhandle=True, handlesize=10,
            sashpad=1, borderwidth=0,
        )
        main_paned = tk.PanedWindow(parent, orient="horizontal", **sash_kw)
        main_paned.pack(fill="both", expand=True)
        self._voices_paned_main = main_paned

        # LEFT pane: inner horizontal split — portrait | settings
        left_paned = tk.PanedWindow(main_paned, orient="horizontal", **sash_kw)
        main_paned.add(left_paned, stretch="always", minsize=240)
        self._voices_paned_left = left_paned

        # Portrait
        pf = SectionFrame(left_paned, "🖼 Portrait")
        left_paned.add(pf, stretch="always", minsize=120)
        self.voice_portrait_canvas = tk.Canvas(pf,
                                                background="#f4f4f4",
                                                highlightthickness=1,
                                                highlightbackground="#ddd")
        self.voice_portrait_canvas.pack(fill="both", expand=True)
        self._voice_portrait_photo = None
        self.voice_portrait_status = tk.StringVar(value="")
        ttk.Label(pf, textvariable=self.voice_portrait_status,
                  foreground="grey", wraplength=240, font=("", 9)).pack(
            anchor="w", pady=(4, 0))

        # Voice settings (right of portrait inside left pane)
        ss = SectionFrame(left_paned, "🎚 Voice settings")
        left_paned.add(ss, stretch="always", minsize=180)
        self.voice_stability = LabeledSlider(ss, "Stability",
            from_=0.0, to=1.0, default=cfg.DEFAULT_VOICE_SETTINGS["stability"],
            help_text="ElevenLabs stability — higher = more consistent (less expressive); lower = more emotional variation.")
        self.voice_stability.pack(fill="x", pady=(4, 0))
        self.voice_style = LabeledSlider(ss, "Style",
            from_=0.0, to=1.0, default=cfg.DEFAULT_VOICE_SETTINGS["style"],
            help_text="Style exaggeration. Higher = strong character; very high can introduce artifacts.")
        self.voice_style.pack(fill="x", pady=(4, 0))
        self.voice_speed = LabeledSlider(ss, "Speed",
            from_=0.7, to=1.2, default=cfg.DEFAULT_VOICE_SETTINGS["speed"],
            help_text="Playback speed multiplier. 1.0 = natural; <1 = slower (gravitas); >1 = quicker (urgent).")
        self.voice_speed.pack(fill="x", pady=(4, 0))

        # RIGHT pane: inner vertical split — voice picker | lines list
        right_paned = tk.PanedWindow(main_paned, orient="vertical", **sash_kw)
        main_paned.add(right_paned, stretch="always", minsize=360)
        self._voices_paned_right = right_paned

        # Voice picker section
        vf = SectionFrame(right_paned, "🎤 Voice")
        right_paned.add(vf, stretch="always", minsize=120)

        nm = ttk.Frame(vf); nm.pack(fill="x")
        ttk.Label(nm, text="Character:").pack(side="left")
        self.voice_name_var = tk.StringVar(value="(no character selected)")
        ttk.Label(nm, textvariable=self.voice_name_var,
                  foreground="#333", font=("", 10, "bold")).pack(side="left", padx=(6, 0))
        self.voice_gender_var = tk.StringVar(value="")
        ttk.Label(nm, textvariable=self.voice_gender_var,
                  foreground="grey", font=("", 9, "italic")).pack(side="left", padx=(6, 0))

        self.voice_choice = LabeledCombobox(vf, "ElevenLabs voice",
            [], "",
            help_text="Voices are filtered by the current character's gender. "
                      "Premade voices come from ElevenLabs; click ➕ Add voice "
                      "to attach a custom voice_id from the Voice Library.")
        self.voice_choice.pack(fill="x", pady=(8, 0))
        self.voice_choice.combo.bind("<<ComboboxSelected>>",
            lambda _e: self.voice_status_var.set(""), add="+")

        # Action buttons row — Demo / Synth / Assign / Add / Remove
        btn_row = ttk.Frame(vf); btn_row.pack(fill="x", pady=(8, 0))
        demo_btn = ttk.Button(btn_row, text="🔉 Demo",
                               command=self._preview_voice_demo)
        demo_btn.pack(side="left")
        Tooltip(demo_btn,
            "Play the ElevenLabs-shipped sample of the selected voice. "
            "Cached to ~/.talkshow_generator/voice_cache/ — free after first play. "
            "Custom voices without a preview_url will TTS-synthesize a short demo "
            "phrase once (small one-time API charge) and cache it.")
        assign_btn = ttk.Button(btn_row, text="🔗 Assign",
                                 command=self._assign_voice_to_character)
        assign_btn.pack(side="left", padx=(6, 0))
        Tooltip(assign_btn,
            "Bind the currently-selected voice (with current Stability / Style / "
            "Speed) to the currently-picked cast member. Persists immediately to "
            "<project>/audio/voices.json.")
        add_btn = ttk.Button(btn_row, text="➕ Add",
                              command=self._open_add_custom_voice_dialog)
        add_btn.pack(side="left", padx=(12, 0))
        Tooltip(add_btn,
            "Open the Add-custom-voice dialog. Paste a voice_id from the "
            "ElevenLabs Voice Library to attach a new voice to your dropdown.")
        rm_btn = ttk.Button(btn_row, text="🗑 Remove",
                             command=self._remove_selected_voice)
        rm_btn.pack(side="left", padx=(6, 0))
        Tooltip(rm_btn,
            "Remove the currently-selected voice from the list (custom voices "
            "only — premade voices cannot be removed).")

        # Lines list section (per-character TTS source-of-truth UI)
        ls = SectionFrame(right_paned, "🎭 Lines for current character")
        right_paned.add(ls, stretch="always", minsize=160)

        hdr = ttk.Frame(ls); hdr.pack(fill="x")
        self.lines_title_var = tk.StringVar(value="(pick a character)")
        ttk.Label(hdr, textvariable=self.lines_title_var,
                  foreground="grey", font=("", 9)).pack(side="left")
        HelpIcon(hdr,
            "All beats from the storyboard whose speaker matches the current "
            "character (or NARRATOR/VOICEOVER synonyms for the voiceover slot). "
            "Status ✅ means an audio file already exists at "
            "<project>/audio/beat_NNNN_<speaker>.mp3. "
            "Double-click the text cell to edit a line — Enter saves."
        ).pack(side="left")

        lines_btn_row = ttk.Frame(ls); lines_btn_row.pack(fill="x", pady=(4, 4))
        gen_all_btn = ttk.Button(lines_btn_row, text="🎭 Generate all missing",
                                   command=self._generate_all_lines_for_voice_character)
        gen_all_btn.pack(side="left")
        Tooltip(gen_all_btn,
            "Render every line of the current character that doesn't yet have "
            "an audio file. Uses the voice + settings on the left. Costs "
            "~$0.0003 per character of text.")
        play_btn = ttk.Button(lines_btn_row, text="▶ Play selected",
                               command=self._play_selected_line)
        play_btn.pack(side="left", padx=(6, 0))
        Tooltip(play_btn,
            "Play the audio of the currently selected line (must have ✅).")
        retry_btn = ttk.Button(lines_btn_row, text="🔄 Re-render selected",
                                command=self._retry_selected_line)
        retry_btn.pack(side="left", padx=(6, 0))
        Tooltip(retry_btn,
            "Re-synthesize the selected line through the current voice + "
            "settings. Previous file is overwritten. Auto-plays after render.")

        # Custom scrollable list of line rows. Each row shows the # / status
        # icon, plus the full line text wrapped to the fixed text-column
        # width. Double-click on the text → inline edit. Hover → tooltip with
        # the previous and next storyboard beats for context.
        list_frame = ttk.Frame(ls); list_frame.pack(fill="both", expand=True)
        self.lines_canvas = tk.Canvas(list_frame, background="#fafafa",
                                       highlightthickness=0)
        self.lines_canvas.pack(side="left", fill="both", expand=True)
        lines_yscroll = ttk.Scrollbar(list_frame, orient="vertical",
                                       command=self.lines_canvas.yview)
        lines_yscroll.pack(side="right", fill="y")
        self.lines_canvas.configure(yscrollcommand=lines_yscroll.set)
        self.lines_inner = ttk.Frame(self.lines_canvas)
        self.lines_inner_id = self.lines_canvas.create_window(
            (0, 0), window=self.lines_inner, anchor="nw")
        self.lines_canvas.bind("<Configure>",
            lambda e: self.lines_canvas.itemconfigure(
                self.lines_inner_id, width=e.width))
        self.lines_inner.bind("<Configure>",
            lambda _e: self.lines_canvas.configure(
                scrollregion=self.lines_canvas.bbox("all")))
        # Mouse-wheel scrolling
        self.lines_canvas.bind("<Enter>",
            lambda _e: self._bind_lines_mousewheel(True))
        self.lines_canvas.bind("<Leave>",
            lambda _e: self._bind_lines_mousewheel(False))
        # Per-row widget refs {beat_idx: {row_frame, text_label, status_label, tooltip}}
        self._lines_rows: dict = {}
        # Selected beat for play/retry buttons
        self._lines_selected_idx: int | None = None
        self._lines_inline_editor = None

        # ── FOOTER: save + status ──────────────────────────────────
        footer = ttk.Frame(parent); footer.pack(fill="x", pady=(6, 0))
        save_btn = ttk.Button(footer, text="💾 Save voices",
                               command=self._save_voices)
        save_btn.pack(side="left")
        Tooltip(save_btn,
            "Persist voice assignments for all characters to <project>/audio/voices.json.")
        self.voice_status_var = tk.StringVar(value="")
        ttk.Label(footer, textvariable=self.voice_status_var,
                  foreground="grey", wraplength=900,
                  font=("", 9)).pack(side="left", padx=(12, 0))

        # Auto-save bindings — value changes trigger the debounced save.
        for w in (self.voice_choice, self.voice_stability, self.voice_style,
                   self.voice_speed):
            bind_autosave(w, lambda: self._schedule_silent_save("voices"))

        # Persist sash positions on user drag.
        main_paned.bind("<ButtonRelease-1>",
            lambda _e: self._save_voice_sashes(), add="+")
        left_paned.bind("<ButtonRelease-1>",
            lambda _e: self._save_voice_sashes(), add="+")
        right_paned.bind("<ButtonRelease-1>",
            lambda _e: self._save_voice_sashes(), add="+")

        # Apply saved sash positions ONCE when the panedwindow first becomes
        # visible — earlier (right after build) the widget's width is still
        # 1px because the tab hasn't been shown yet, and sash_place(0, 0)
        # would collapse the left pane.
        self._voices_sashes_applied = False
        main_paned.bind("<Visibility>",
            self._maybe_apply_voice_sashes_once, add="+")
        main_paned.bind("<Map>",
            self._maybe_apply_voice_sashes_once, add="+")

        # Initial population — picker first, voices fetch in background.
        self._refresh_voices_list()
        self._maybe_fetch_premade_voices()

    # ── VOICES — cache helpers ──────────────────────────────────────
    def _voices_cache(self) -> list:
        return list(self.main.settings.get("voices_cache") or [])

    def _persist_voices_cache(self, voices: list):
        import settings as _settings
        self.main.settings["voices_cache"] = voices
        _settings.set_setting("voices_cache", voices)

    def _maybe_fetch_premade_voices(self):
        """Background fetch of premade voices on first need. No-op if cache
        already has any premade entries (per user — no manual refresh)."""
        cache = self._voices_cache()
        if any(v.get("source") == "premade" for v in cache):
            return
        if not self.main.settings.get("elevenlabs_api_key"):
            self.voice_status_var.set(
                "ℹ Set the ElevenLabs API key in Settings to load the premade voices.")
            return
        self.voice_status_var.set("🔄 Fetching premade voices from ElevenLabs…")

        def worker():
            try:
                from llm_clients import ElevenLabsClient
                client = ElevenLabsClient(
                    self.main.settings.get("elevenlabs_api_key", ""))
                voices = client.list_voices()
                new_entries = []
                for v in voices:
                    if v.get("category") != "premade":
                        continue
                    labels_ = v.get("labels") or {}
                    g = (labels_.get("gender") or "any").lower()
                    if g not in ("male", "female"):
                        g = "any"
                    new_entries.append({
                        "voice_id":    v.get("voice_id"),
                        "name":        v.get("name") or v.get("voice_id"),
                        "gender":      g,
                        "preview_url": v.get("preview_url"),
                        "source":      "premade",
                    })
                self.after(0, lambda: self._on_premade_fetched(new_entries))
            except Exception as e:
                err = str(e)
                self.after(0, lambda: self.voice_status_var.set(
                    f"⚠ Could not fetch premade voices: {err[:200]}"))

        threading.Thread(target=worker, daemon=True).start()

    def _on_premade_fetched(self, premade: list):
        existing_custom = [v for v in self._voices_cache()
                           if v.get("source") == "custom"]
        merged = premade + existing_custom
        self._persist_voices_cache(merged)
        self._refresh_voice_dropdown()
        self.voice_status_var.set(
            f"✅ Loaded {len(premade)} premade voice(s) "
            f"({len(existing_custom)} custom).")

    # ── VOICES — filter / dropdown ──────────────────────────────────
    def _current_voice_character_gender(self) -> str:
        cid = self.current_voice_char_id
        if not cid:
            return "Any"
        if cid == "narrator":
            # Voiceover/narrator has no on-screen body — show all voices
            # regardless of gender filter.
            return "Any"
        if cid in self._character_form_state:
            return self._character_form_state[cid].get("gender") or "Any"
        if self.main.current_project:
            params = projects.load_character_params(self.main.current_project, cid)
            if params:
                return params.get("gender") or "Any"
        return "Any"

    def _voices_for_gender(self, char_gender: str) -> list:
        cg = (char_gender or "Any").strip().lower()
        cache = self._voices_cache()
        if cg in ("any", ""):
            return list(cache)
        out = []
        for v in cache:
            vg = (v.get("gender") or "any").lower()
            if vg == cg or vg in ("any", "unknown"):
                out.append(v)
        return out

    def _refresh_voice_dropdown(self):
        gender = self._current_voice_character_gender()
        voices = self._voices_for_gender(gender)
        labels = [v.get("name") or v.get("voice_id", "?") for v in voices]
        self._current_voice_options = voices
        prev = self.main._autosave_paused
        self.main._autosave_paused = True
        try:
            self.voice_choice.combo["values"] = labels
            cur = self.voice_choice.get()
            if cur not in labels:
                self.voice_choice.set(labels[0] if labels else "")
        finally:
            self.main._autosave_paused = prev

    def _voice_id_for_label(self, label: str) -> str:
        for v in getattr(self, "_current_voice_options", []) or []:
            if (v.get("name") or "") == label:
                return v.get("voice_id", "")
        for v in self._voices_cache():
            if (v.get("name") or "") == label:
                return v.get("voice_id", "")
        return ""

    def _voice_entry_for_label(self, label: str) -> dict:
        for v in self._voices_cache():
            if (v.get("name") or "") == label:
                return v
        return {}

    # ── VOICES — cast picker / form load ────────────────────────────
    def _refresh_voices_list(self):
        try:
            form = self.main._collect_form()
        except Exception:
            form = {}
        characters = self._resolve_characters_from_form(form)
        # Append the voice-only voiceover/narrator slot. Not part of the
        # standard cast (no portrait, no Characters-tab entry), so we add it
        # here rather than in _resolve_characters_from_form.
        characters.append(("narrator", "🎙 Voiceover / Narrator", "Narrator"))
        labels = [c[1] for c in characters]
        self.voice_picker["values"] = labels
        self._voices_characters = characters
        if not labels:
            self._refresh_voice_summary()
            self._refresh_portrait_preview()
            return
        current_label = next(
            (l for cid, l, _ in characters if cid == self.current_voice_char_id),
            labels[0],
        )
        self.voice_picker_var.set(current_label)
        self.current_voice_char_id = next(
            (cid for cid, l, _ in characters if l == current_label),
            characters[0][0],
        )
        self._load_voice_into_form(self.current_voice_char_id)
        self._refresh_voice_summary()

    def _on_voice_character_picked(self):
        new_id = next(
            (cid for cid, l, _ in self._voices_characters
             if l == self.voice_picker_var.get()),
            None,
        )
        if not new_id or new_id == self.current_voice_char_id:
            return
        if self.current_voice_char_id:
            self._voice_form_state[self.current_voice_char_id] = self._collect_voice_form()
        self.current_voice_char_id = new_id
        self._load_voice_into_form(new_id)

    def _collect_voice_form(self) -> dict:
        label = self.voice_choice.get()
        return {
            "voice_name": label,
            "voice_id":   self._voice_id_for_label(label),
            "stability":  self.voice_stability.get(),
            "style":      self.voice_style.get(),
            "speed":      self.voice_speed.get(),
        }

    def _load_voice_into_form(self, char_id: str):
        data = self._voice_form_state.get(char_id)
        if data is None and self.main.current_project:
            stored = projects.load_voices(self.main.current_project)
            data = (stored.get("voices") or {}).get(char_id)
        if data is None:
            data = {}

        name = next((c[2] for c in self._voices_characters if c[0] == char_id), "")
        self.voice_name_var.set(name or "(unknown)")
        gender = self._current_voice_character_gender()
        self.voice_gender_var.set(f"({gender.lower()})" if gender else "")

        # Re-filter dropdown for this character's gender FIRST so the saved
        # voice can be re-selected if still in scope.
        self._refresh_voice_dropdown()

        # Resolve saved voice — prefer voice_id (stable) over name (renameable).
        saved_id = data.get("voice_id") or ""
        saved_label = data.get("voice_name") or data.get("voice_label") or ""
        resolved_label = None
        if saved_id:
            for v in getattr(self, "_current_voice_options", []) or []:
                if v.get("voice_id") == saved_id:
                    resolved_label = v.get("name")
                    break
        if resolved_label is None and saved_label:
            # Legacy fallback: strip " — calm female" suffix from old labels
            stripped = saved_label.split(" — ")[0].strip()
            labels = self.voice_choice.combo["values"]
            if stripped in labels:
                resolved_label = stripped

        prev = self.main._autosave_paused
        self.main._autosave_paused = True
        try:
            if resolved_label:
                self.voice_choice.set(resolved_label)
            self.voice_stability.set(data.get("stability", cfg.DEFAULT_VOICE_SETTINGS["stability"]))
            self.voice_style.set(data.get("style", cfg.DEFAULT_VOICE_SETTINGS["style"]))
            self.voice_speed.set(data.get("speed", cfg.DEFAULT_VOICE_SETTINGS["speed"]))
        finally:
            self.main._autosave_paused = prev
        self.voice_status_var.set("")
        self._refresh_portrait_preview()
        self._refresh_character_lines()

    def _refresh_voice_summary(self):
        """Backward-compat alias — old code paths call this whenever voice
        state changes. We now show per-character lines instead of an
        aggregate cast summary."""
        self._refresh_character_lines()

    def _bind_lines_mousewheel(self, on: bool):
        if on:
            self.lines_canvas.bind_all("<MouseWheel>",
                self._on_lines_mousewheel)
        else:
            try:
                self.lines_canvas.unbind_all("<MouseWheel>")
            except tk.TclError:
                pass

    def _on_lines_mousewheel(self, event):
        try:
            self.lines_canvas.yview_scroll(int(-event.delta / 120), "units")
        except tk.TclError:
            pass

    def _refresh_character_lines(self):
        """Repaint the lines list — one row per BEAT-PART (long beats are
        split into ≤25-word parts, each gets its own TTS file). Marks parts
        whose mp3 already exists with ✅. Hover tooltip on a row shows the
        previous + next storyboard beats for global context."""
        if not hasattr(self, "lines_inner"):
            return
        # Destroy any open inline editor before rebuilding
        self._close_line_inline_editor(commit=False)
        for child in self.lines_inner.winfo_children():
            child.destroy()
        self._lines_rows.clear()
        self._lines_selected_idx = None

        cid = self.current_voice_char_id
        if not cid:
            self.lines_title_var.set("(no character picked)")
            return
        speaker_map = self._build_speaker_to_char_map()
        # (beat_idx, part_idx_1based, beat, part) for every part the current
        # character speaks. parts numbering is 1-based to match file naming.
        char_rows = []
        for i, beat in enumerate(self._beats):
            if beat.get("type") not in ("line", "host_interjection"):
                continue
            speaker = beat.get("speaker") or ""
            if self._resolve_char_id_from_speaker(speaker, speaker_map) != cid:
                continue
            parts = beat.get("parts") or [{
                "text": beat.get("text", ""),
                "duration": beat.get("duration", 0.0),
            }]
            for p_zero, part in enumerate(parts):
                char_rows.append((i, p_zero + 1, beat, part))

        char_display = next((c[2] for c in self._voices_characters
                              if c[0] == cid), cid)
        if not char_rows:
            self.lines_title_var.set(
                f"0 lines for {char_display} — run Storyboard → Parse first, "
                f"or check the speaker name in the beats list.")
            return
        rendered_count = 0
        proj = self.main.current_project
        for beat_idx, part_idx, beat, part in char_rows:
            speaker_slug = projects.speaker_slugify(beat.get("speaker") or "")
            has_audio = False
            if proj:
                path = projects.audio_beat_path(
                    proj, beat_idx, speaker_slug, part_idx=part_idx)
                has_audio = path.exists()
            if has_audio:
                rendered_count += 1
            self._build_line_row(beat_idx, part_idx, beat, part, has_audio)
        total_parts = len(char_rows)
        self.lines_title_var.set(
            f"{total_parts} part(s) for {char_display} — "
            f"{rendered_count} rendered, {total_parts - rendered_count} missing")

    def _build_line_row(self, beat_idx: int, part_idx: int,
                          beat: dict, part: dict, has_audio: bool):
        row = ttk.Frame(self.lines_inner, borderwidth=1, relief="flat",
                         padding=4)
        row.pack(fill="x", padx=2, pady=1)
        # Header: idx (#N.P) + status
        hdr = ttk.Frame(row); hdr.pack(side="left", anchor="n", padx=(0, 8))
        parts_count = len(beat.get("parts") or [1])
        if parts_count > 1:
            label = f"#{beat_idx + 1}.{part_idx}"
        else:
            label = f"#{beat_idx + 1}"
        ttk.Label(hdr, text=label, width=7,
                  foreground="#888", font=("", 9)).pack()
        ttk.Label(hdr, text=("✅" if has_audio else "—"),
                  foreground=("#3a7d3a" if has_audio else "#999")).pack()
        # Text — wrapped Label (this part's text only)
        text_str = (part.get("text") or "").replace("\r", " ")
        text_lbl = ttk.Label(row, text=text_str, wraplength=560,
                              justify="left", foreground="#222",
                              cursor="hand2")
        text_lbl.pack(side="left", fill="x", expand=True)
        # Row selection key — (beat_idx, part_idx)
        sel_key = (beat_idx, part_idx)
        # Bindings
        for w in (row, hdr, text_lbl):
            w.bind("<Button-1>",
                lambda _e, k=sel_key: self._select_line_row(k))
        text_lbl.bind("<Double-Button-1>",
            lambda _e, i=beat_idx: self._on_line_text_double_click(i))
        # Hover tooltip — prev / next beats for context (global order)
        ctx = self._line_context_tooltip(beat_idx)
        if ctx:
            tip = Tooltip(text_lbl, ctx, wraplength=500)
            self._lines_rows[sel_key] = {
                "row": row, "text_label": text_lbl, "tooltip": tip,
                "beat_idx": beat_idx, "part_idx": part_idx,
            }
        else:
            self._lines_rows[sel_key] = {
                "row": row, "text_label": text_lbl,
                "beat_idx": beat_idx, "part_idx": part_idx,
            }

    def _line_context_tooltip(self, beat_idx: int) -> str:
        """Return prev + next beat text (truncated to 120 chars) for the
        hover tooltip. Returns empty string if there's nothing to show."""
        def trunc(s: str, n: int = 120) -> str:
            s = (s or "").replace("\n", " ").replace("\r", " ").strip()
            return s if len(s) <= n else s[: n - 1] + "…"
        lines = []
        # Previous beat
        if beat_idx > 0:
            pb = self._beats[beat_idx - 1]
            sp = pb.get("speaker") or "—"
            lines.append(f"⬆ #{beat_idx} ({sp}): {trunc(pb.get('text', ''))}")
        else:
            lines.append("⬆ (first beat of the show)")
        # Next beat
        if beat_idx < len(self._beats) - 1:
            nb = self._beats[beat_idx + 1]
            sp = nb.get("speaker") or "—"
            lines.append(f"⬇ #{beat_idx + 2} ({sp}): {trunc(nb.get('text', ''))}")
        else:
            lines.append("⬇ (last beat of the show)")
        return "\n\n".join(lines)

    def _select_line_row(self, sel_key):
        """Highlight the selected row. sel_key is (beat_idx, part_idx)."""
        for _key, w in self._lines_rows.items():
            try:
                w["row"].configure(relief="flat")
            except tk.TclError:
                pass
        if sel_key in self._lines_rows:
            try:
                self._lines_rows[sel_key]["row"].configure(relief="solid")
            except tk.TclError:
                pass
        self._lines_selected_idx = sel_key

    def _on_line_text_double_click(self, beat_idx: int):
        """Double-click on text → start inline edit. (Other regions fall
        through to play/render via the row's primary click handler.)"""
        self._select_line_row(beat_idx)
        self._start_line_inline_edit(str(beat_idx))

    def _save_voices(self):
        if not self._require_project():
            return
        if self.current_voice_char_id:
            self._voice_form_state[self.current_voice_char_id] = self._collect_voice_form()
        payload = {"voices": self._voice_form_state}
        projects.save_voices(self.main.current_project, payload)
        self.voice_status_var.set(
            f"✅ Voices saved: {projects.voices_path(self.main.current_project)}")
        self._refresh_voice_summary()
        self.main._refresh_all_tab_marks()

    def _assign_voice_to_character(self):
        """Bind the currently-selected voice to the currently-picked character
        and persist immediately. Same as 💾 Save voices, but the status text
        names the specific binding for clearer feedback."""
        if not self._require_project():
            return
        if not self.current_voice_char_id:
            messagebox.showinfo("🔗 Assign voice",
                "Pick a cast member first.", parent=self)
            return
        label = self.voice_choice.get()
        if not label:
            messagebox.showinfo("🔗 Assign voice",
                "Pick a voice first.", parent=self)
            return
        self._voice_form_state[self.current_voice_char_id] = self._collect_voice_form()
        payload = {"voices": self._voice_form_state}
        projects.save_voices(self.main.current_project, payload)
        char_name = next((c[2] for c in self._voices_characters
                           if c[0] == self.current_voice_char_id),
                          self.current_voice_char_id)
        self.voice_status_var.set(
            f"🔗 Assigned voice '{label}' → {char_name}. Saved.")
        self._refresh_voice_summary()
        self.main._refresh_all_tab_marks()

    # ── VOICES — portrait preview ───────────────────────────────────
    def _refresh_portrait_preview(self):
        canvas = getattr(self, "voice_portrait_canvas", None)
        if canvas is None:
            return
        canvas.delete("all")
        self._voice_portrait_photo = None
        cid = self.current_voice_char_id
        if not cid:
            self._draw_portrait_message("(no character)")
            return
        if cid == "narrator":
            self._draw_portrait_message(
                "🎙 Voiceover / Narrator\n"
                "Voice-only — no portrait.\n"
                "Pick any voice from the list\n"
                "(gender filter is disabled).")
            self.voice_portrait_status.set("")
            return
        if not self.main.current_project:
            self._draw_portrait_message("⚠ Open a project to see portraits")
            self.voice_portrait_status.set("")
            return
        cd = projects.character_dir(self.main.current_project, cid)
        versioned_re = re.compile(r"\.v\d+\.[a-z0-9]+$", re.IGNORECASE)
        files = list(cd.glob("portrait.*")) if cd.exists() else []
        files = [p for p in files if p.is_file() and not versioned_re.search(p.name)
                 and p.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp")]
        if not files:
            self._draw_portrait_message(
                "⚠ No portrait yet\n"
                "Generate the Portrait pose on\n"
                "the 🎭 Characters tab so you\n"
                "can match voice to face.")
            self.voice_portrait_status.set("")
            return
        try:
            cw = max(canvas.winfo_width(), 220)
            ch = max(canvas.winfo_height(), 320)
            self._voice_portrait_photo = display_image_path_on_canvas(
                canvas, files[0], self.main.current_project, cw, ch)
            self.voice_portrait_status.set(f"📁 {files[0].name}")
        except tk.TclError as e:
            self._draw_portrait_message(f"❌ Could not load: {e}")

    def _draw_portrait_message(self, text: str):
        c = self.voice_portrait_canvas
        c.delete("all")
        try:
            cw = c.winfo_width() or 200
        except tk.TclError:
            cw = 200
        c.create_text(max(cw // 2, 100), 160, text=text,
                       fill="#999", font=("", 10), justify="center")
        self._voice_portrait_photo = None

    # ── VOICES — preview playback ───────────────────────────────────
    def _cache_path_for_voice(self, voice_id: str):
        return cfg.VOICE_CACHE_DIR / f"{voice_id}.mp3"

    def _preview_voice_demo(self):
        """Play the ElevenLabs-shipped demo for the selected voice. If the
        voice has no preview_url (typically user-added custom voices),
        TTS-synthesize a default demo phrase once and cache it."""
        label = self.voice_choice.get()
        if not label:
            self.voice_status_var.set("ℹ Pick a voice first.")
            return
        entry = self._voice_entry_for_label(label)
        if not entry:
            self.voice_status_var.set(f"❌ Voice '{label}' not in cache.")
            return
        voice_id = entry.get("voice_id", "")
        if not voice_id:
            self.voice_status_var.set("❌ This voice has no voice_id.")
            return
        cache_path = self._cache_path_for_voice(voice_id)
        if cache_path.exists():
            self._play_audio_path(cache_path, f"🔉 Demo: {label}")
            return

        preview_url = entry.get("preview_url")
        if preview_url:
            self.voice_status_var.set(f"🔄 Downloading demo for {label}…")

            def worker_dl():
                try:
                    import urllib.request
                    req = urllib.request.Request(
                        preview_url,
                        headers={"User-Agent": "talkshow-generator/0.1"})
                    with urllib.request.urlopen(req, timeout=30) as resp:
                        data = resp.read()
                    cache_path.write_bytes(data)
                    self.after(0,
                        lambda: self._play_audio_path(cache_path, f"🔉 Demo: {label}"))
                except Exception as e:
                    err = str(e)
                    self.after(0, lambda: self.voice_status_var.set(
                        f"❌ Demo download failed: {err[:240]}"))

            threading.Thread(target=worker_dl, daemon=True).start()
            return

        # No preview_url — synthesize a default demo phrase and cache it.
        if not self.main.settings.get("elevenlabs_api_key"):
            self.voice_status_var.set(
                "ℹ No demo available and ElevenLabs API key is not set — "
                "add one in Settings.")
            return
        self.voice_status_var.set(
            f"🔄 Synthesizing demo for {label} (custom voice, one-time)…")

        def worker_synth_demo():
            try:
                from llm_clients import ElevenLabsClient
                client = ElevenLabsClient(
                    self.main.settings.get("elevenlabs_api_key", ""))
                audio = client.tts(voice_id, cfg.CUSTOM_VOICE_DEMO_TEXT,
                                    stability=0.5, style=0.0, speed=1.0)
                cache_path.write_bytes(audio)
                self.after(0,
                    lambda: self._play_audio_path(cache_path, f"🔉 Demo: {label}"))
            except Exception as e:
                err = str(e)
                self.after(0, lambda: self.voice_status_var.set(
                    f"❌ Demo synth failed: {err[:240]}"))

        threading.Thread(target=worker_synth_demo, daemon=True).start()

    def _play_audio_path(self, path, success_msg: str):
        try:
            import audio_player
            audio_player.play(path)
            self.voice_status_var.set(success_msg)
        except RuntimeError as e:
            self.voice_status_var.set(
                f"❌ {e}".replace("\n", " ").replace("  ", " ")[:300])
        except Exception as e:
            self.voice_status_var.set(f"❌ Playback failed: {e}")

    # ── VOICES — custom voice add/remove + library link ─────────────
    def _add_custom_voice_with_args(self, name: str, voice_id: str,
                                      gender: str) -> tuple:
        """Internal helper — used by both inline form (legacy) and the new
        Add-voice popup dialog. Returns (ok: bool, msg: str)."""
        name = (name or "").strip()
        voice_id = (voice_id or "").strip()
        if not name or not voice_id:
            return False, "Both Name and voice_id are required."
        g = (gender or "").lower()
        if g not in ("male", "female", "any"):
            g = "any"
        cache = self._voices_cache()
        if any(v.get("voice_id") == voice_id for v in cache):
            return False, "A voice with that voice_id already exists."
        cache.append({
            "voice_id":    voice_id,
            "name":        name,
            "gender":      g,
            "preview_url": None,
            "source":      "custom",
        })
        self._persist_voices_cache(cache)
        self._refresh_voice_dropdown()
        # Auto-select the newly added voice in the dropdown so the user can
        # immediately click 🔉 Demo to generate the demo clip.
        self.voice_choice.set(name)
        return True, f"Added '{name}' ({g})"

    def _open_add_custom_voice_dialog(self):
        AddCustomVoiceDialog(self, self)

    def _remove_selected_voice(self):
        label = self.voice_choice.get()
        entry = self._voice_entry_for_label(label)
        if not entry:
            return
        if entry.get("source") != "custom":
            messagebox.showinfo("🗑 Remove",
                "Premade voices cannot be removed — only custom ones.",
                parent=self)
            return
        if not messagebox.askyesno("🗑 Remove voice",
            f"Remove custom voice '{label}' from your voice list?\n\n"
            f"Saved characters using this voice will still keep the voice_id, "
            f"but the dropdown will show '(missing)'.",
            parent=self):
            return
        vid = entry.get("voice_id")
        cache = [v for v in self._voices_cache() if v.get("voice_id") != vid]
        self._persist_voices_cache(cache)
        self._refresh_voice_dropdown()
        self.voice_status_var.set(f"🗑 Removed custom voice '{label}'.")

    def _open_voice_library(self):
        import webbrowser
        webbrowser.open(cfg.ELEVENLABS_VOICE_LIBRARY_URL)
        self.voice_status_var.set(
            "🔗 Opened ElevenLabs Voice Library in browser — "
            "copy a voice_id and paste it above.")

    def apply_voices(self, project_path):
        """Load voices.json into memory. Called by MainWindow on project open."""
        self._voice_form_state = {}
        if not project_path:
            return
        data = projects.load_voices(project_path)
        self._voice_form_state = data.get("voices", {}) or {}
        # The cast picker was built before the form was loaded — refresh it
        # now so the resumed project's cast members appear and the lines
        # list paints. _refresh_voices_list → _load_voice_into_form →
        # _refresh_character_lines chain handles everything.
        if hasattr(self, "voice_picker"):
            self._refresh_voices_list()

    # ── VOICES — per-part TTS actions ───────────────────────────────
    def _selected_line_key(self):
        """Returns (beat_idx, part_idx) for the highlighted row, or None."""
        return self._lines_selected_idx

    def _selected_line_beat_idx(self):
        """Back-compat shim — returns just the beat_idx of the selected row."""
        k = self._lines_selected_idx
        if isinstance(k, tuple):
            return k[0]
        return k

    # ── VOICES — inline edit of beat text in the lines list ─────────
    def _start_line_inline_edit(self, item: str):
        """Show a multi-line Text widget on top of the row's text label so
        the user can edit a beat's spoken text. Enter commits; Escape cancels.
        On commit, persists the change into self._beats and saves the
        storyboard.json so the Storyboard tab sees it too."""
        self._close_line_inline_editor(commit=False)
        try:
            beat_idx = int(item)
        except ValueError:
            return
        if beat_idx < 0 or beat_idx >= len(self._beats):
            return
        row_info = self._lines_rows.get(beat_idx)
        if not row_info:
            return
        text_lbl = row_info["text_label"]
        try:
            text_lbl.update_idletasks()
            w = max(text_lbl.winfo_width(), 400)
            h = max(text_lbl.winfo_height(), 40)
            x = text_lbl.winfo_rootx() - row_info["row"].winfo_rootx()
            y = text_lbl.winfo_rooty() - row_info["row"].winfo_rooty()
        except tk.TclError:
            return
        current_text = (self._beats[beat_idx].get("text") or "")
        editor = tk.Text(row_info["row"], borderwidth=1, relief="solid",
                          wrap="word", font=("", 10))
        editor.place(x=x, y=y, width=w, height=h)
        editor.insert("1.0", current_text)
        editor.focus_set()
        # Select all
        editor.tag_add("sel", "1.0", "end-1c")
        self._lines_inline_editor = {"widget": editor, "item": item,
                                      "beat_idx": beat_idx,
                                      "original": current_text}
        # Enter commits — but the user might want to add a newline. Plain
        # Enter is interpreted as commit (matches the user's spec). Shift+Enter
        # would be natural for newline; binding swallows the plain Return.
        editor.bind("<Return>",   lambda _e: ("break", self._commit_line_inline_edit())[0])
        editor.bind("<KP_Enter>", lambda _e: ("break", self._commit_line_inline_edit())[0])
        editor.bind("<Escape>",   lambda _e: self._close_line_inline_editor(commit=False))
        editor.bind("<FocusOut>", lambda _e: self._commit_line_inline_edit())

    def _commit_line_inline_edit(self):
        if not self._lines_inline_editor:
            return
        info = self._lines_inline_editor
        widget = info["widget"]
        beat_idx = info["beat_idx"]
        original = info["original"]
        try:
            # Text widget — strip the trailing newline tk always appends.
            new_text = widget.get("1.0", "end-1c")
        except tk.TclError:
            self._lines_inline_editor = None
            return
        if new_text != original and 0 <= beat_idx < len(self._beats):
            self._beats[beat_idx]["text"] = new_text
            # Recompute estimated duration (it'll be overwritten by real
            # TTS duration later but keep the rough estimate fresh).
            self._beats[beat_idx]["duration"] = self._estimate_duration(new_text)
            # Edited beat — re-split into parts. Old per-part state is
            # preserved by _split_beats_into_parts when the part text
            # didn't change.
            self._split_beats_into_parts()
            if self.main.current_project:
                try:
                    projects.save_storyboard(self.main.current_project, {
                        "beats": self._beats,
                        "pass_statuses": self._pass_statuses,
                    })
                except OSError as e:
                    self.voice_status_var.set(
                        f"❌ Could not save storyboard: {e}")
            self.voice_status_var.set(
                f"✏ Beat {beat_idx + 1} text updated. "
                f"Click 🔄 Re-render selected to refresh audio.")
            # Keep the Storyboard tab's beats tree and Talking heads cards
            # in sync if they're mounted.
            if hasattr(self, "beats_tree"):
                self._refresh_beats_tree()
            if hasattr(self, "th_inner"):
                self._refresh_talking_heads_cards()
        self._close_line_inline_editor(commit=False)
        self._refresh_character_lines()

    def _close_line_inline_editor(self, commit: bool = False):
        """Destroy the inline edit Entry (if any). When commit=True, save
        first; otherwise discard."""
        info = self._lines_inline_editor
        if not info:
            return
        if commit:
            # Re-enter commit path to avoid divergence
            self._commit_line_inline_edit()
            return
        try:
            info["widget"].destroy()
        except tk.TclError:
            pass
        self._lines_inline_editor = None

    # ── VOICES — resizable panel sashes (persisted in app settings) ─
    _VOICES_SASH_KEY = "voices_sash_positions"

    def _save_voice_sashes(self):
        """Persist sash positions as fractions of the corresponding paned
        width/height so the layout adapts to different window sizes on
        re-open. tk.PanedWindow uses sash_coord(idx) → (x, y)."""
        try:
            main_w = self._voices_paned_main.winfo_width()
            left_w = self._voices_paned_left.winfo_width()
            right_h = self._voices_paned_right.winfo_height()
            cur = {}
            if main_w > 0:
                x, _y = self._voices_paned_main.sash_coord(0)
                cur["main"] = max(0.05, min(0.95, x / main_w))
            if left_w > 0:
                x, _y = self._voices_paned_left.sash_coord(0)
                cur["left"] = max(0.05, min(0.95, x / left_w))
            if right_h > 0:
                _x, y = self._voices_paned_right.sash_coord(0)
                cur["right"] = max(0.05, min(0.95, y / right_h))
        except (tk.TclError, AttributeError, ZeroDivisionError):
            return
        import settings as _settings
        self.main.settings[self._VOICES_SASH_KEY] = cur
        _settings.set_setting(self._VOICES_SASH_KEY, cur)

    def _maybe_apply_voice_sashes_once(self, _event=None):
        """Apply saved sash positions once — when the panedwindow has a real
        width (after the tab first becomes visible). Bound to <Visibility>
        and <Map>; gated by the _voices_sashes_applied flag so subsequent
        tab switches don't reset positions the user has manually adjusted."""
        if getattr(self, "_voices_sashes_applied", False):
            return
        if not hasattr(self, "_voices_paned_main"):
            return
        try:
            w = self._voices_paned_main.winfo_width()
        except tk.TclError:
            return
        if w < 100:
            # Widget still measuring — retry on next event.
            return
        self._apply_saved_voice_sashes()
        self._voices_sashes_applied = True

    def _apply_saved_voice_sashes(self):
        """Restore sash positions from settings, or apply visible-friendly
        defaults so all panels are visible on first open. tk.PanedWindow
        uses sash_place(idx, x, y)."""
        cur = self.main.settings.get(self._VOICES_SASH_KEY) or {}
        try:
            self._voices_paned_main.update_idletasks()
            mw = self._voices_paned_main.winfo_width()
            lw = self._voices_paned_left.winfo_width()
            rh = self._voices_paned_right.winfo_height()
            # Default: 38% LEFT pane / 62% RIGHT pane
            f_main = float(cur.get("main", 0.38))
            # Default inside LEFT pane: portrait 38% / settings 62%
            f_left = float(cur.get("left", 0.38))
            # Default inside RIGHT pane: voice picker 28% / lines 72%
            f_right = float(cur.get("right", 0.28))
            if mw > 0:
                self._voices_paned_main.sash_place(0, int(mw * f_main), 0)
            if lw > 0:
                self._voices_paned_left.sash_place(0, int(lw * f_left), 0)
            if rh > 0:
                self._voices_paned_right.sash_place(0, 0, int(rh * f_right))
        except (tk.TclError, AttributeError):
            pass

    def _play_selected_line(self):
        sel = self._selected_line_key()
        if not sel:
            self.voice_status_var.set("ℹ Pick a line first.")
            return
        if not self._require_project():
            return
        beat_idx, part_idx = sel
        beat = self._beats[beat_idx]
        speaker_slug = projects.speaker_slugify(beat.get("speaker") or "")
        path = projects.audio_beat_path(
            self.main.current_project, beat_idx, speaker_slug,
            part_idx=part_idx)
        if not path.exists():
            self.voice_status_var.set(
                f"ℹ No audio for #{beat_idx + 1}.{part_idx} yet — use "
                f"🔄 Re-render or 🎭 Generate all missing.")
            return
        self._play_audio_path(path,
            f"▶ Playing #{beat_idx + 1}.{part_idx}")

    def _retry_selected_line(self):
        sel = self._selected_line_key()
        if not sel:
            self.voice_status_var.set("ℹ Pick a line first.")
            return
        if not self._require_project():
            return
        if not self.main.settings.get("elevenlabs_api_key"):
            messagebox.showwarning("⚠ Missing API key",
                "ElevenLabs API key is not set. Add it in ⚙ Settings.",
                parent=self)
            return
        if self.current_voice_char_id:
            self._voice_form_state[self.current_voice_char_id] = self._collect_voice_form()
            projects.save_voices(self.main.current_project,
                {"voices": self._voice_form_state})
        beat_idx, part_idx = sel
        self._render_single_part(beat_idx, part_idx)

    def _render_single_part_sync(self, beat_idx: int, part_idx: int):
        """Synthesize one part of a beat through the speaker's assigned
        voice + settings. Saves to <project>/audio/beat_NNNN_<speaker>_pN.mp3.
        Raises RuntimeError on missing voice / API failure / empty text."""
        proj = self.main.current_project
        if not proj:
            raise RuntimeError("No project open.")
        beat = self._beats[beat_idx]
        parts = beat.get("parts") or []
        if part_idx < 1 or part_idx > len(parts):
            raise RuntimeError(
                f"Beat {beat_idx + 1} has no part {part_idx}.")
        part = parts[part_idx - 1]
        text = (part.get("text") or "").strip()
        if not text:
            raise RuntimeError(
                f"#{beat_idx + 1}.{part_idx} has no text.")
        speaker = beat.get("speaker") or ""
        speaker_slug = projects.speaker_slugify(speaker)
        voices_map = projects.load_voices(proj).get("voices") or {}
        char_id = self._resolve_char_id_from_speaker(
            speaker, self._build_speaker_to_char_map())
        voice_entry = voices_map.get(char_id) or {}
        voice_id = voice_entry.get("voice_id")
        if not voice_id:
            raise RuntimeError(
                f"No voice assigned for '{speaker}'. Pick one in the dropdown "
                f"above and click 🔗 Assign to character.")
        from llm_clients import ElevenLabsClient
        client = ElevenLabsClient(
            self.main.settings.get("elevenlabs_api_key", ""))
        audio_bytes = client.tts(
            voice_id, text,
            stability=float(voice_entry.get("stability", 0.5)),
            style=float(voice_entry.get("style", 0.0)),
            speed=float(voice_entry.get("speed", 1.0)))
        path = projects.audio_beat_path(
            proj, beat_idx, speaker_slug, part_idx=part_idx)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(audio_bytes)
        return path

    # Back-compat alias — single-part beats still callable as _render_single_line_sync
    def _render_single_line_sync(self, beat_idx: int, part_idx: int = 1):
        return self._render_single_part_sync(beat_idx, part_idx)

    def _render_single_part(self, beat_idx: int, part_idx: int):
        self.voice_status_var.set(
            f"🔄 Rendering #{beat_idx + 1}.{part_idx}…")

        def worker():
            try:
                path = self._render_single_part_sync(beat_idx, part_idx)
                self.after(0, self._refresh_character_lines)
                self.after(0, lambda: self.voice_status_var.set(
                    f"✅ Rendered: {path.name}"))
                self.after(0, lambda p=path, b=beat_idx, q=part_idx:
                    self._play_audio_path(p, f"▶ Playing #{b + 1}.{q}"))
            except Exception as e:
                err = str(e)
                self.after(0, lambda: self.voice_status_var.set(
                    f"❌ #{beat_idx + 1}.{part_idx}: {err[:240]}"))

        threading.Thread(target=worker, daemon=True).start()

    # Back-compat alias for callers that don't know about parts
    def _render_single_line(self, beat_idx: int, part_idx: int = 1):
        return self._render_single_part(beat_idx, part_idx)

    def _generate_all_lines_for_voice_character(self):
        if not self._require_project():
            return
        if not self.main.settings.get("elevenlabs_api_key"):
            messagebox.showwarning("⚠ Missing API key",
                "ElevenLabs API key is not set. Add it in ⚙ Settings.",
                parent=self)
            return
        cid = self.current_voice_char_id
        if not cid:
            self.voice_status_var.set("ℹ Pick a character first.")
            return
        # Snapshot voice form edits so the latest settings are used.
        self._voice_form_state[cid] = self._collect_voice_form()
        projects.save_voices(self.main.current_project,
            {"voices": self._voice_form_state})

        speaker_map = self._build_speaker_to_char_map()
        proj = self.main.current_project
        # Collect (beat_idx, part_idx) pairs for missing parts of this character.
        missing: list = []
        for i, beat in enumerate(self._beats):
            if beat.get("type") not in ("line", "host_interjection"):
                continue
            speaker = beat.get("speaker") or ""
            if self._resolve_char_id_from_speaker(speaker, speaker_map) != cid:
                continue
            parts = beat.get("parts") or []
            if not parts:
                continue
            speaker_slug = projects.speaker_slugify(speaker)
            for p_zero, part in enumerate(parts):
                if not (part.get("text") or "").strip():
                    continue
                part_idx = p_zero + 1
                path = projects.audio_beat_path(
                    proj, i, speaker_slug, part_idx=part_idx)
                if not path.exists():
                    missing.append((i, part_idx))
        if not missing:
            self.voice_status_var.set(
                "ℹ Already rendered — no missing parts for this character.")
            return

        total = len(missing)
        self.voice_status_var.set(
            f"🔄 Generating {total} missing part(s) for current character…")

        def worker():
            done = 0
            failed = 0
            for n, (beat_idx, part_idx) in enumerate(missing):
                try:
                    self._render_single_part_sync(beat_idx, part_idx)
                    done += 1
                    self.after(0, lambda b=beat_idx, q=part_idx, n_=n, t=total:
                        self.voice_status_var.set(
                            f"🔄 Rendered #{b + 1}.{q} ({n_ + 1}/{t})"))
                    self.after(0, self._refresh_character_lines)
                except Exception as e:
                    failed += 1
                    self.after(0, lambda b=beat_idx, q=part_idx, e_=str(e):
                        self.voice_status_var.set(
                            f"⚠ #{b + 1}.{q}: {e_[:160]}"))
            self.after(0, lambda: self.voice_status_var.set(
                f"✅ Batch done — {done} rendered, {failed} failed."))
            self.after(0, self._refresh_character_lines)
            self.after(0, self.main._refresh_all_tab_marks)

        threading.Thread(target=worker, daemon=True).start()

    # ── 📋 Storyboard sub-tab ───────────────────────────────────────
    def _build_storyboard_tab(self, parent):
        # ── Source script preview (read-only) ──────────────────────
        sf = SectionFrame(parent, "📄 Source script — fed to all 3 LLM passes")
        sf.pack(fill="x", pady=(0, 10))
        script_row = ttk.Frame(sf); script_row.pack(fill="x")
        self.story_script_text = tk.Text(
            script_row, height=8, wrap="word", state="disabled",
            background="#f9f9f9", font=("Consolas", 9))
        self.story_script_text.pack(side="left", fill="both", expand=True)
        script_scroll = ttk.Scrollbar(script_row, orient="vertical",
                                       command=self.story_script_text.yview)
        self.story_script_text.configure(yscrollcommand=script_scroll.set)
        script_scroll.pack(side="right", fill="y")

        info_row = ttk.Frame(sf); info_row.pack(fill="x", pady=(4, 0))
        self.story_script_info_var = tk.StringVar(value="(no script loaded)")
        ttk.Label(info_row, textvariable=self.story_script_info_var,
                  foreground="grey", font=("", 9)).pack(side="left")
        reload_btn = ttk.Button(info_row, text="🔄 Reload",
                                 command=self._load_script_preview)
        reload_btn.pack(side="right")
        Tooltip(reload_btn,
            "Re-read <project>/script.txt and refresh this preview. "
            "Run after re-generating the script on step 1.")

        # ── Pipeline control bar ───────────────────────────────────
        ctrl = SectionFrame(parent, "🔧 Multi-pass LLM pipeline")
        ctrl.pack(fill="x", pady=(0, 10))
        ModelPicker(ctrl, kind="text", main_window=self.main,
                     label_text="Text model:").pack(anchor="w", pady=(0, 6))

        btn_row = ttk.Frame(ctrl); btn_row.pack(fill="x")
        self._pass_status_labels: dict = {}
        pass_handlers = {
            "parse":        self._run_parse,
            "atmospherize": self._run_atmospherize,
            "camera":       self._run_camera_plan,
        }
        for i, (key, label) in enumerate(cfg.STORYBOARD_PASSES):
            cell = ttk.Frame(btn_row); cell.pack(side="left", padx=(0 if i == 0 else 8, 0))
            b = ttk.Button(cell, text=f"▶ {label}", command=pass_handlers[key])
            b.pack(side="left")
            tip = {
                "parse":        "Read script.txt from the project and break it into structured beats (speaker, text, act). First pass — required before the others.",
                "atmospherize": "Add audience reactions (applause/boo/laugh), host interjections, pauses, and character entrances between existing beats.",
                "camera":       "Assign shot type (CU / MS / 2-shot / wide / audience reaction / entrance wide) and transition type (hard cut / smooth) to every beat.",
            }[key]
            Tooltip(b, tip)
            status_lbl = ttk.Label(cell, text="⏸", foreground="grey")
            status_lbl.pack(side="left", padx=(4, 0))
            self._pass_status_labels[key] = status_lbl
            # For the Camera pass, add a ⚙ button right after the status to
            # open the director-preference dialog (formerly its own sub-tab).
            if key == "camera":
                cam_settings_btn = ttk.Button(cell, text="⚙", width=3,
                    command=self._open_camera_plan_dialog)
                cam_settings_btn.pack(side="left", padx=(2, 0))
                Tooltip(cam_settings_btn,
                    "Open the Camera plan settings (preset, reaction %, "
                    "audience %, avg shot duration, default transition, "
                    "wide-shot frequency, custom rules). These feed the "
                    "Camera-pass LLM context.")

        sep = ttk.Separator(btn_row, orient="vertical")
        sep.pack(side="left", fill="y", padx=12)

        save_btn = ttk.Button(btn_row, text="💾 Save storyboard",
                               command=self._save_storyboard)
        save_btn.pack(side="left")
        Tooltip(save_btn,
            "Persist all beats and pass statuses to <project>/storyboard.json. Required so step 2 'Generate' can read it.")

        clear_btn = ttk.Button(btn_row, text="🗑 Clear all beats",
                                command=self._clear_beats)
        clear_btn.pack(side="left", padx=(6, 0))
        Tooltip(clear_btn,
            "Wipe the current beat list and reset all pass statuses. Useful before re-running Parse from scratch.")

        self.story_status_var = tk.StringVar(value="")
        ttk.Label(ctrl, textvariable=self.story_status_var,
                  foreground="grey", wraplength=900).pack(anchor="w", pady=(8, 0))

        # ── Beats list + editor ────────────────────────────────────
        list_frame = SectionFrame(parent, "📋 Beats")
        list_frame.pack(fill="both", expand=True, pady=(0, 10))

        # Treeview with columns
        cols = ("idx", "type", "speaker", "text", "dur", "shot", "trans", "act")
        self.beats_tree = ttk.Treeview(list_frame, columns=cols, show="headings",
                                        height=12, selectmode="browse")
        headings = {
            "idx": "#", "type": "Type", "speaker": "Speaker",
            "text": "Text", "dur": "Dur",
            "shot": "Shot", "trans": "Trans", "act": "Act",
        }
        widths = {
            "idx": 40, "type": 130, "speaker": 130,
            "text": 360, "dur": 50, "shot": 120, "trans": 80, "act": 40,
        }
        for c in cols:
            self.beats_tree.heading(c, text=headings[c])
            self.beats_tree.column(c, width=widths[c],
                                   anchor="w" if c in ("text", "speaker", "type", "shot") else "center")
        tree_scroll = ttk.Scrollbar(list_frame, orient="vertical", command=self.beats_tree.yview)
        self.beats_tree.configure(yscrollcommand=tree_scroll.set)
        self.beats_tree.pack(side="left", fill="both", expand=True)
        tree_scroll.pack(side="right", fill="y")
        self.beats_tree.bind("<<TreeviewSelect>>", lambda _e: self._on_beat_selected())
        self.beats_tree.bind("<Double-Button-1>", self._on_beats_tree_double_click)

        # ── Editor below ───────────────────────────────────────────
        ed = SectionFrame(parent, "✏ Edit selected beat")
        ed.pack(fill="x")

        grid = ttk.Frame(ed); grid.pack(fill="x")
        for c in range(4):
            grid.columnconfigure(c, weight=1)

        beat_type_labels = [label for _, label in cfg.BEAT_TYPES]
        self.beat_type = LabeledCombobox(grid, "Type",
            beat_type_labels, beat_type_labels[0],
            help_text="Beat category. 'Line' = character speaking; 'Audience' = crowd reaction SFX; 'Host interjection' = quick host cut-in; 'Pause' = silent beat; 'Entrance' = character walks onto stage.")
        self.beat_type.grid(row=0, column=0, sticky="ew", padx=(0, 8), pady=4)

        self.beat_speaker = LabeledEntry(grid, "Speaker", "",
            help_text="Character speaking this beat. Empty for audience reactions and pauses.")
        self.beat_speaker.grid(row=0, column=1, sticky="ew", padx=(0, 8), pady=4)

        self.beat_duration = LabeledEntry(grid, "Duration (s)", "3.0", width=8,
            help_text="Estimated seconds. After TTS rendering this will be replaced with the actual audio duration.")
        self.beat_duration.grid(row=0, column=2, sticky="ew", padx=(0, 8), pady=4)

        self.beat_act = LabeledCombobox(grid, "Act",
            ["1", "2", "3", "4"], "1", width=4,
            help_text="Which of the 4 acts this beat belongs to. Drives pacing and the LLM Atmospherize pass context.")
        self.beat_act.grid(row=0, column=3, sticky="ew", pady=4)

        self.beat_shot = LabeledCombobox(grid, "Shot",
            cfg.SHOT_TYPES, cfg.SHOT_TYPES[0],
            help_text="Camera framing. Filled by the Camera pass; you can override per beat.")
        self.beat_shot.grid(row=1, column=0, sticky="ew", padx=(0, 8), pady=4)

        self.beat_transition = LabeledCombobox(grid, "Transition into this beat",
            cfg.TRANSITION_TYPES, cfg.TRANSITION_TYPES[0],
            help_text="Cut from previous beat. Hard cut for energy / hot moments; smooth cross-fade for calmer transitions.")
        self.beat_transition.grid(row=1, column=1, columnspan=3, sticky="ew", pady=4)

        self.beat_text = LabeledText(ed, "Text / SFX description",
            height=3, width=80,
            placeholder="Spoken line OR audience description like '[applause]' / '[Boo!]' / '[Marina enters from stage left]'",
            help_text="The dialogue line for 'Line' beats, or the SFX/action description for audience/entrance/pause beats.")
        self.beat_text.pack(fill="x", pady=(4, 0))

        # Editor buttons
        ed_btns = ttk.Frame(ed); ed_btns.pack(fill="x", pady=(8, 0))
        apply_btn = ttk.Button(ed_btns, text="💾 Apply changes",
                                command=self._apply_beat_edit)
        apply_btn.pack(side="left")
        Tooltip(apply_btn,
            "Save the editor fields back into the selected beat. Required after edits — switching rows without Apply discards changes.")

        del_btn = ttk.Button(ed_btns, text="🗑 Delete beat", command=self._delete_beat)
        del_btn.pack(side="left", padx=(6, 0))
        Tooltip(del_btn, "Permanently remove the selected beat from the list.")

        up_btn = ttk.Button(ed_btns, text="⬆ Move up", command=self._move_beat_up)
        up_btn.pack(side="left", padx=(6, 0))
        Tooltip(up_btn, "Move the selected beat one position earlier in the timeline.")

        down_btn = ttk.Button(ed_btns, text="⬇ Move down", command=self._move_beat_down)
        down_btn.pack(side="left", padx=(6, 0))
        Tooltip(down_btn, "Move the selected beat one position later in the timeline.")

        add_btn = ttk.Button(ed_btns, text="➕ Add beat", command=self._add_beat)
        add_btn.pack(side="left", padx=(20, 0))
        Tooltip(add_btn, "Insert a new empty beat at the end of the list. Edit it in the form above.")

        # Render the (probably empty) list
        self._refresh_beats_tree()
        self._refresh_pass_status_labels()

    # ── STORYBOARD HELPERS ──────────────────────────────────────────
    def _beat_type_label_to_key(self, label: str) -> str:
        return next((k for k, l in cfg.BEAT_TYPES if l == label), "line")

    def _beat_type_key_to_label(self, key: str) -> str:
        return next((l for k, l in cfg.BEAT_TYPES if k == key), cfg.BEAT_TYPES[0][1])

    def _on_beats_tree_double_click(self, event):
        tree = self.beats_tree
        row_id = tree.identify_row(event.y)
        column_id = tree.identify_column(event.x)
        if not row_id or not column_id:
            return

        try:
            idx = int(row_id)
        except ValueError:
            return

        if idx < 0 or idx >= len(self._beats):
            return

        tree.selection_set(row_id)

        try:
            col_idx = int(column_id.replace("#", "")) - 1
        except ValueError:
            return

        columns = ("idx", "type", "speaker", "text", "dur", "shot", "trans", "act")
        if col_idx < 0 or col_idx >= len(columns):
            return
        column_name = columns[col_idx]

        if column_name == "idx":
            return

        bbox = tree.bbox(row_id, column_id)
        if not bbox:
            return
        x, y, w, h = bbox

        val = tree.item(row_id, "values")[col_idx]
        edit_var = tk.StringVar(value=val if val != "—" else "")

        if column_name == "type":
            beat_type_labels = [label for _, label in cfg.BEAT_TYPES]
            editor = ttk.Combobox(tree, textvariable=edit_var, values=beat_type_labels, state="readonly")
        elif column_name == "shot":
            editor = ttk.Combobox(tree, textvariable=edit_var, values=cfg.SHOT_TYPES, state="readonly")
        elif column_name == "trans":
            editor = ttk.Combobox(tree, textvariable=edit_var, values=cfg.TRANSITION_TYPES, state="readonly")
        elif column_name == "act":
            editor = ttk.Combobox(tree, textvariable=edit_var, values=["1", "2", "3", "4"], state="readonly")
        else:
            editor = ttk.Entry(tree, textvariable=edit_var)

        editor.place(x=x, y=y, width=w, height=h)
        editor.focus_set()
        if isinstance(editor, ttk.Entry):
            editor.select_range(0, "end")
            editor.icursor("end")

        def commit(event=None):
            if not editor.winfo_exists():
                return
            new_val = edit_var.get()
            b = self._beats[idx]

            if column_name == "type":
                b["type"] = self._beat_type_label_to_key(new_val)
            elif column_name == "speaker":
                b["speaker"] = new_val
            elif column_name == "text":
                b["text"] = new_val
                b["duration"] = self._estimate_duration(new_val)
            elif column_name == "dur":
                try:
                    b["duration"] = float(new_val)
                except ValueError:
                    pass
            elif column_name == "shot":
                b["shot"] = new_val
            elif column_name == "trans":
                b["transition"] = new_val
            elif column_name == "act":
                try:
                    b["act"] = int(new_val)
                except ValueError:
                    pass

            self._split_beats_into_parts()
            self._refresh_beats_tree()
            self._schedule_silent_save("storyboard")

            if hasattr(self, "th_inner"):
                self._refresh_talking_heads_cards()
            if hasattr(self, "lines_inner"):
                self._refresh_character_lines()

            editor.destroy()

        def cancel(event=None):
            if editor.winfo_exists():
                editor.destroy()

        editor.bind("<Return>", commit)
        if isinstance(editor, ttk.Combobox):
            editor.bind("<<ComboboxSelected>>", commit)
        editor.bind("<Escape>", cancel)
        editor.bind("<FocusOut>", lambda e: tree.after(100, lambda: editor.winfo_exists() and commit()))

    def _refresh_beats_tree(self):
        # Repopulate the treeview from self._beats
        for iid in self.beats_tree.get_children():
            self.beats_tree.delete(iid)
        for i, b in enumerate(self._beats):
            text = (b.get("text") or "").replace("\n", " ")
            if len(text) > 60:
                text = text[:57] + "…"
            self.beats_tree.insert("", "end", iid=str(i), values=(
                i + 1,
                self._beat_type_key_to_label(b.get("type", "line")),
                b.get("speaker", "") or "—",
                text,
                f"{b.get('duration', 0):.1f}",
                b.get("shot", "") or "—",
                b.get("transition", "") or "—",
                b.get("act", ""),
            ))

    def _refresh_pass_status_labels(self):
        icons = {"pending": "⏸", "in_progress": "▶", "done": "✅", "failed": "❌"}
        colors = {"pending": "grey", "in_progress": "#1d4e89",
                  "done": "#3a7d3a", "failed": "#c84141"}
        for key, lbl in self._pass_status_labels.items():
            st = self._pass_statuses.get(key, "pending")
            lbl.config(text=icons.get(st, "⏸"), foreground=colors.get(st, "grey"))

    def _set_pass_status(self, key: str, status: str):
        self._pass_statuses[key] = status
        self._refresh_pass_status_labels()

    def _on_beat_selected(self):
        sel = self.beats_tree.selection()
        if not sel:
            return
        idx = int(sel[0])
        if idx >= len(self._beats):
            return
        self._selected_beat_idx = idx
        b = self._beats[idx]
        self.beat_type.set(self._beat_type_key_to_label(b.get("type", "line")))
        self.beat_speaker.set(b.get("speaker", ""))
        self.beat_duration.set(f"{b.get('duration', 0):.1f}")
        self.beat_act.set(str(b.get("act", "1")))
        self.beat_shot.set(b.get("shot", "") or cfg.SHOT_TYPES[0])
        self.beat_transition.set(b.get("transition", "") or cfg.TRANSITION_TYPES[0])
        self.beat_text.set(b.get("text", ""))

    def _apply_beat_edit(self):
        if self._selected_beat_idx is None:
            return
        idx = self._selected_beat_idx
        try:
            duration = float(self.beat_duration.get() or "0")
        except ValueError:
            duration = 0.0
        try:
            act = int(self.beat_act.get())
        except ValueError:
            act = 1
        self._beats[idx] = {
            "type": self._beat_type_label_to_key(self.beat_type.get()),
            "speaker": self.beat_speaker.get(),
            "duration": duration,
            "act": act,
            "shot": self.beat_shot.get(),
            "transition": self.beat_transition.get(),
            "text": self.beat_text.get(),
        }
        # Beat text/type may have changed — re-split into parts.
        self._split_beats_into_parts()
        self._refresh_beats_tree()
        self.beats_tree.selection_set(str(idx))
        self.story_status_var.set(f"✅ Beat {idx + 1} updated.")
        self._schedule_silent_save("storyboard")
        if hasattr(self, "th_inner"):
            self._refresh_talking_heads_cards()
        if hasattr(self, "lines_inner"):
            self._refresh_character_lines()

    def _delete_beat(self):
        if self._selected_beat_idx is None:
            return
        idx = self._selected_beat_idx
        del self._beats[idx]
        self._selected_beat_idx = None
        self._refresh_beats_tree()
        self.story_status_var.set(f"🗑 Beat {idx + 1} deleted.")
        self._schedule_silent_save("storyboard")

    def _move_beat_up(self):
        if self._selected_beat_idx is None or self._selected_beat_idx == 0:
            return
        idx = self._selected_beat_idx
        self._beats[idx - 1], self._beats[idx] = self._beats[idx], self._beats[idx - 1]
        self._selected_beat_idx = idx - 1
        self._refresh_beats_tree()
        self.beats_tree.selection_set(str(idx - 1))

    def _move_beat_down(self):
        if self._selected_beat_idx is None or self._selected_beat_idx >= len(self._beats) - 1:
            return
        idx = self._selected_beat_idx
        self._beats[idx + 1], self._beats[idx] = self._beats[idx], self._beats[idx + 1]
        self._selected_beat_idx = idx + 1
        self._refresh_beats_tree()
        self.beats_tree.selection_set(str(idx + 1))

    def _add_beat(self):
        self._beats.append({
            "type": "line", "speaker": "", "text": "",
            "duration": 3.0, "shot": "", "transition": "",
            "act": 1,
        })
        self._refresh_beats_tree()
        new_idx = len(self._beats) - 1
        self.beats_tree.selection_set(str(new_idx))
        self.beats_tree.see(str(new_idx))
        self._on_beat_selected()
        self._schedule_silent_save("storyboard")

    def _clear_beats(self):
        if self._beats and not messagebox.askyesno(
            "🗑 Clear beats",
            f"Delete all {len(self._beats)} beats and reset pipeline statuses?",
            parent=self,
        ):
            return
        self._beats = []
        self._selected_beat_idx = None
        self._pass_statuses = {"parse": "pending",
                                "atmospherize": "pending",
                                "camera": "pending"}
        self._refresh_beats_tree()
        self._refresh_pass_status_labels()
        self.story_status_var.set("🗑 Beats cleared. Re-run Parse to start over.")

    def _save_storyboard(self):
        if not self._require_project():
            return
        payload = {
            "beats": self._beats,
            "pass_statuses": self._pass_statuses,
        }
        path, archived = projects.save_storyboard_versioned(
            self.main.current_project, payload)
        if archived:
            self.story_status_var.set(
                f"✅ Storyboard saved: {path.name}  (previous → {archived.name})")
        else:
            self.story_status_var.set(f"✅ Storyboard saved: {path}")

    def _load_script_preview(self):
        """Read <project>/script.txt and paint it into the read-only preview.
        Called on project open + after the script is regenerated."""
        if not hasattr(self, "story_script_text"):
            return
        if not self.main.current_project:
            self._set_script_preview("", "(no project loaded)")
            return
        sp = self.main.current_project / "script.txt"
        if not sp.exists():
            self._set_script_preview("",
                "(no script.txt — run step 1 → 🎬 Generate first)")
            return
        try:
            text = sp.read_text(encoding="utf-8")
        except OSError as e:
            self._set_script_preview("", f"(read error: {e})")
            return
        act_count = len(_ACT_HEADER_RE.findall(text))
        word_count = len(text.split())
        info = (f"📄 {sp.name} — {len(text):,} chars, {word_count:,} words, "
                f"{act_count} act header(s)")
        self._set_script_preview(text, info)

    def _set_script_preview(self, text: str, info: str):
        self.story_script_text.config(state="normal")
        self.story_script_text.delete("1.0", "end")
        self.story_script_text.insert("1.0", text)
        self.story_script_text.config(state="disabled")
        self.story_script_info_var.set(info)

    def reload_script_preview(self):
        """Public hook for MainWindow to call after step-1 Generate finishes."""
        self._load_script_preview()

    # ── STORYBOARD PIPELINE (real LLM passes) ──────────────────────
    def _read_script_or_warn(self) -> str | None:
        """Hard error if <project>/script.txt is missing."""
        if not self._require_project():
            return None
        sp = self.main.current_project / "script.txt"
        if not sp.exists():
            messagebox.showerror("⚠ No script",
                "Run step 1 → 🎬 Generate first to produce script.txt. "
                "The Storyboard passes need a real script to parse.",
                parent=self)
            return None
        try:
            return sp.read_text(encoding="utf-8")
        except OSError as e:
            messagebox.showerror("❌ Read failed", str(e), parent=self)
            return None

    def _cast_names_for_prompt(self) -> str:
        try:
            form = self.main._collect_form()
        except Exception:
            form = {}
        cast = []
        for k in ("host1_name", "host2_name", "heroine_name"):
            v = form.get(k, "")
            if v:
                cast.append(v)
        for f in (form.get("friend_results") or []):
            if f:
                cast.append(f.split(",")[0].strip())
        cast.append("Expert")
        ant = form.get("antagonist_type", "")
        if ant:
            cast.append(ant)
        return ", ".join(cast)

    def _audience_summary_for_prompt(self) -> str:
        try:
            collected = self._collect_audience()
        except Exception:
            return "mixed daytime audience, engaged baseline"
        return (f"gender_ratio={collected['gender_ratio']}; "
                f"ethnic_mix={collected['ethnic_mix']}; "
                f"age_range={collected['age_range']}; "
                f"crowd_size={collected['crowd_size']}; "
                f"dress_code={collected['dress_code']}; "
                f"energy_baseline={collected['energy_baseline']}")

    def _camera_plan_for_prompt(self) -> tuple:
        try:
            cp = self._collect_camera_plan()
        except Exception:
            cp = dict(cfg.DEFAULT_CAMERA_PLAN)
        custom = cp.pop("custom_rules", "") or "(none)"
        return json.dumps(cp, ensure_ascii=False, indent=2), custom

    def _prior_summary_for_acts(self, completed_acts: list) -> str:
        if not completed_acts:
            return "(no previous acts yet)"
        parts = []
        for n in completed_acts:
            count = sum(1 for b in self._beats if b.get("act") == n)
            parts.append(f"Act {n}: {count} beats already processed.")
        return "\n".join(parts)

    # ── Parse pass (sync core + async UI wrapper) ───────────────────
    def _parse_sync(self, progress_cb=None) -> list:
        """Sync — must be called from a worker thread. Parses script.txt
        through all 4 acts via the LLM and returns the merged beats list.
        Raises RuntimeError on missing project / missing script / no act
        headers. The optional progress_cb(act_num, total_acts) is invoked
        between act calls (use it to update UI status)."""
        if not self.main.current_project:
            raise RuntimeError("No project open.")
        sp = self.main.current_project / "script.txt"
        if not sp.exists():
            raise RuntimeError(
                "No script.txt in the project. Run step 1 → 🎬 Generate first.")
        script_text = sp.read_text(encoding="utf-8")
        act_texts = _split_script_into_acts(script_text)

        client = self.main._build_client()
        cast_names = self._cast_names_for_prompt()
        all_beats: list = []
        total = len(act_texts)
        for act_num in sorted(act_texts.keys()):
            if progress_cb:
                progress_cb(act_num, total)
            user = PROMPT_STORE.render("storyboard_parse_user",
                act_number=act_num,
                cast_names=cast_names,
                act_text=act_texts[act_num])
            raw = client.complete(
                system=PROMPT_STORE.get_active_template("storyboard_parse_system"),
                user=user, max_tokens=4000, temperature=0.3)
            beats = _extract_beats_json(raw)
            for b in beats:
                b.setdefault("type", "line")
                b.setdefault("speaker", "")
                b.setdefault("text", "")
                b.setdefault("duration", self._estimate_duration(b.get("text", "")))
                b.setdefault("shot", "")
                b.setdefault("transition", "")
                b["act"] = act_num
            all_beats.extend(beats)
        return all_beats

    def _run_parse(self):
        if self._is_pass_in_flight():
            return
        script_text = self._read_script_or_warn()
        if script_text is None:
            return
        try:
            _split_script_into_acts(script_text)  # early validation
        except RuntimeError as e:
            messagebox.showerror("❌ Parse failed", str(e), parent=self)
            return

        self._set_pass_status("parse", "in_progress")
        self.story_status_var.set("🔄 Parse: starting…")

        def worker():
            try:
                def pcb(act, total):
                    self.after(0,
                        lambda a=act, t=total: self.story_status_var.set(
                            f"🔄 Parse: act {a} of {t}…"))
                beats = self._parse_sync(progress_cb=pcb)
                self.after(0, lambda: self._on_parse_done(beats))
            except Exception as e:
                err = str(e)
                self.after(0, lambda: self._on_pass_failed("parse", err))

        threading.Thread(target=worker, daemon=True).start()

    def _on_parse_done(self, beats: list):
        self._beats = beats
        self._split_beats_into_parts()
        self._set_pass_status("parse", "done")
        self._set_pass_status("atmospherize", "pending")
        self._set_pass_status("camera", "pending")
        self._refresh_beats_tree()
        self.story_status_var.set(
            f"✅ Parse done: {len(beats)} beats from {len(set(b.get('act') for b in beats))} acts.")
        self._schedule_silent_save("storyboard")

    @staticmethod
    def _estimate_duration(text: str) -> float:
        words = len((text or "").split())
        return round(max(words / 150.0 * 60.0, 1.0), 1)  # min 1s

    # ── Atmospherize pass (sync core + async UI wrapper) ────────────
    def _atmospherize_sync(self, progress_cb=None) -> list:
        """Sync — must be called from a worker thread. Enriches self._beats
        by inserting audience reactions / host interjections / pauses /
        entrances via the LLM. Returns the new enriched beats list. Raises
        RuntimeError if there are no beats to process."""
        if not self._beats:
            raise RuntimeError("No beats — run Parse first.")
        client = self.main._build_client()
        audience_summary = self._audience_summary_for_prompt()
        audience_energy = "engaged"
        try:
            audience_energy = self._collect_audience().get("energy_baseline", audience_energy)
        except Exception:
            pass
        system = PROMPT_STORE.render("storyboard_atmospherize_system",
            audience_energy=audience_energy)
        acts = sorted(set(b.get("act", 1) for b in self._beats))
        total = len(acts)
        all_enriched: list = []
        for act_num in acts:
            if progress_cb:
                progress_cb(act_num, total)
            act_beats = [b for b in self._beats if b.get("act") == act_num]
            user = PROMPT_STORE.render("storyboard_atmospherize_user",
                act_number=act_num,
                beats_json=json.dumps(act_beats, ensure_ascii=False, indent=2),
                prior_summary=self._prior_summary_for_acts(
                    acts[:acts.index(act_num)]),
                audience_summary=audience_summary)
            raw = client.complete(system=system, user=user,
                                   max_tokens=6000, temperature=0.6)
            enriched = _extract_beats_json(raw)
            for b in enriched:
                b.setdefault("type", "line")
                b.setdefault("speaker", "")
                b.setdefault("text", "")
                b.setdefault("duration", self._estimate_duration(b.get("text", "")))
                b.setdefault("shot", "")
                b.setdefault("transition", "")
                b["act"] = act_num
            all_enriched.extend(enriched)
        return all_enriched

    def _run_atmospherize(self):
        if self._is_pass_in_flight():
            return
        if not self._beats:
            messagebox.showinfo("⚠ Atmospherize",
                                "Run Parse first — there are no beats to atmospherize.",
                                parent=self)
            return
        self._set_pass_status("atmospherize", "in_progress")
        self.story_status_var.set("🔄 Atmospherize: starting…")

        def worker():
            try:
                def pcb(act, _total):
                    self.after(0, lambda a=act: self.story_status_var.set(
                        f"🔄 Atmospherize: act {a}…"))
                enriched = self._atmospherize_sync(progress_cb=pcb)
                self.after(0, lambda: self._on_atmospherize_done(enriched))
            except Exception as e:
                err = str(e)
                self.after(0, lambda: self._on_pass_failed("atmospherize", err))

        threading.Thread(target=worker, daemon=True).start()

    def _split_beats_into_parts(self):
        """For every beat in self._beats, populate beat["parts"] using the
        heuristic splitter (10-25 words per part). Speaking-beat parts each
        carry their own head orientation + style fields. Non-speaking beats
        get a single uniform part so downstream code can treat them the same."""
        for b in self._beats:
            text = b.get("text") or ""
            existing_parts = b.get("parts") or []
            if b.get("type") not in ("line", "host_interjection"):
                # Non-speaking beats: one wrapping part to keep callers uniform.
                b["parts"] = [{
                    "text": text,
                    "duration": float(b.get("duration") or _estimate_part_duration(text)),
                    "head_orientation": "front",
                    "head_custom": "",
                    "style_options": [],
                    "style_selected_idx": 0,
                    "style_custom": "",
                }]
                continue
            new_parts = split_text_into_parts(text)
            # Preserve per-part state when the split shape didn't change.
            for i, np in enumerate(new_parts):
                src = existing_parts[i] if i < len(existing_parts) else {}
                # Only carry over per-part state if the new text matches the
                # old part's text exactly — otherwise drop the style options
                # (they were tailored to a different sentence).
                if src.get("text") == np["text"]:
                    np["head_orientation"] = src.get("head_orientation", "front")
                    np["head_custom"] = src.get("head_custom", "")
                    np["style_options"] = src.get("style_options", [])
                    np["style_selected_idx"] = src.get("style_selected_idx", 0)
                    np["style_custom"] = src.get("style_custom", "")
                else:
                    np["head_orientation"] = "front"
                    np["head_custom"] = ""
                    np["style_options"] = []
                    np["style_selected_idx"] = 0
                    np["style_custom"] = ""
            b["parts"] = new_parts

    def _on_atmospherize_done(self, beats: list):
        self._beats = beats
        self._split_beats_into_parts()
        self._set_pass_status("atmospherize", "done")
        # Camera info is now stale on inserted beats — reset its status.
        if self._pass_statuses.get("camera") == "done":
            self._set_pass_status("camera", "pending")
        self._refresh_beats_tree()
        self.story_status_var.set(
            f"✅ Atmospherize done: {len(beats)} beats total (re-run Camera to assign shots on new beats).")
        self._schedule_silent_save("storyboard")

    # ── Camera pass (sync core + async UI wrapper) ──────────────────
    def _camera_sync(self, progress_cb=None) -> list:
        """Sync — must be called from a worker thread. Assigns shot type and
        transition style to every beat. Returns the planned beats list."""
        if not self._beats:
            raise RuntimeError("No beats — run Parse first.")
        client = self.main._build_client()
        cp_json, custom_rules = self._camera_plan_for_prompt()
        system = PROMPT_STORE.get_active_template("storyboard_camera_system")
        acts = sorted(set(b.get("act", 1) for b in self._beats))
        total = len(acts)
        all_planned: list = []
        for act_num in acts:
            if progress_cb:
                progress_cb(act_num, total)
            act_beats = [b for b in self._beats if b.get("act") == act_num]
            user = PROMPT_STORE.render("storyboard_camera_user",
                act_number=act_num,
                beats_json=json.dumps(act_beats, ensure_ascii=False, indent=2),
                prior_summary=self._prior_summary_for_acts(
                    acts[:acts.index(act_num)]),
                camera_plan_json=cp_json,
                custom_rules=custom_rules)
            raw = client.complete(system=system, user=user,
                                   max_tokens=6000, temperature=0.4)
            planned = _extract_beats_json(raw)
            for b in planned:
                b["act"] = act_num
            all_planned.extend(planned)
        return all_planned

    def _run_camera_plan(self):
        if self._is_pass_in_flight():
            return
        if not self._beats:
            messagebox.showinfo("⚠ Camera plan",
                                "Run Parse first — there are no beats to plan camera for.",
                                parent=self)
            return
        self._set_pass_status("camera", "in_progress")
        self.story_status_var.set("🔄 Camera plan: starting…")

        def worker():
            try:
                def pcb(act, _total):
                    self.after(0, lambda a=act: self.story_status_var.set(
                        f"🔄 Camera: act {a}…"))
                planned = self._camera_sync(progress_cb=pcb)
                self.after(0, lambda: self._on_camera_done(planned))
            except Exception as e:
                err = str(e)
                self.after(0, lambda: self._on_pass_failed("camera", err))

        threading.Thread(target=worker, daemon=True).start()

    def _on_camera_done(self, beats: list):
        self._beats = beats
        self._split_beats_into_parts()
        self._set_pass_status("camera", "done")
        self._refresh_beats_tree()
        self.story_status_var.set(
            f"✅ Camera plan done: shot + transition assigned across {len(beats)} beats.")
        self._schedule_silent_save("storyboard")

    def _on_pass_failed(self, key: str, err: str):
        self._set_pass_status(key, "failed")
        self.story_status_var.set(f"❌ {key.title()} failed: {err[:240]}")

    def _is_pass_in_flight(self) -> bool:
        if any(v == "in_progress" for v in self._pass_statuses.values()):
            messagebox.showinfo("⚠ Already running",
                "A Storyboard pass is already running — wait for it to finish.",
                parent=self)
            return True
        return False

    # ── STUB BEAT GENERATION (placeholder for real LLM) ─────────────
    def _generate_stub_parse_beats(self) -> list:
        try:
            form = self.main._collect_form()
        except Exception:
            form = {}
        h1 = form.get("host1_name", "Andrew Cornell")
        h2 = form.get("host2_name", "Olivia Vance")
        her = form.get("heroine_name", "Marina Kravchenko")
        ant = form.get("antagonist_type", "Industry rep")
        show = form.get("show_name", "Open Talk")
        return [
            {"type": "line", "speaker": h1, "text": f"Welcome to {show}.", "duration": 2.5, "shot": "", "transition": "", "act": 1},
            {"type": "line", "speaker": h2, "text": "Today we're tackling something millions struggle with…", "duration": 4.0, "shot": "", "transition": "", "act": 1},
            {"type": "line", "speaker": h1, "text": "What if everything they told you was wrong?", "duration": 3.5, "shot": "", "transition": "", "act": 1},
            {"type": "line", "speaker": her, "text": "I lost 27 kilograms in five months — and I'll tell you exactly how.", "duration": 5.0, "shot": "", "transition": "", "act": 2},
            {"type": "line", "speaker": h2, "text": f"{her.split()[0]}, that's incredible. Take us back to the beginning.", "duration": 4.0, "shot": "", "transition": "", "act": 2},
            {"type": "line", "speaker": "Expert", "text": "What we're seeing is a complete reactivation of the GLP-1 pathway.", "duration": 5.5, "shot": "", "transition": "", "act": 3},
            {"type": "line", "speaker": ant, "text": "These claims are not supported by peer review.", "duration": 4.5, "shot": "", "transition": "", "act": 3},
            {"type": "line", "speaker": h1, "text": "And here's how you can try it today.", "duration": 3.5, "shot": "", "transition": "", "act": 4},
        ]

    def _stub_atmospherize(self, beats: list) -> list:
        try:
            form = self.main._collect_form()
        except Exception:
            form = {}
        h1 = form.get("host1_name", "Andrew Cornell")
        her = form.get("heroine_name", "Marina Kravchenko")
        ant = form.get("antagonist_type", "Industry rep")
        enriched = []
        heroine_entered = False
        for beat in beats:
            # Drop an entrance + applause just before the heroine's first line
            if (beat["type"] == "line" and beat["speaker"] == her
                    and not heroine_entered):
                enriched.append({"type": "entrance", "speaker": her,
                                 "text": f"[{her.split()[0]} enters stage from left]",
                                 "duration": 3.0, "shot": "", "transition": "",
                                 "act": beat["act"]})
                enriched.append({"type": "audience", "speaker": "",
                                 "text": "[applause and cheers]",
                                 "duration": 3.5, "shot": "", "transition": "",
                                 "act": beat["act"]})
                heroine_entered = True
            enriched.append(beat)
            # Dramatic reactions
            if "27 kilograms" in beat["text"]:
                enriched.append({"type": "audience", "speaker": "",
                                 "text": "[gasps and murmurs]",
                                 "duration": 2.0, "shot": "", "transition": "",
                                 "act": beat["act"]})
            if beat["speaker"] == ant and "not supported" in beat["text"]:
                enriched.append({"type": "audience", "speaker": "",
                                 "text": "[Boo!]",
                                 "duration": 2.5, "shot": "", "transition": "",
                                 "act": beat["act"]})
                enriched.append({"type": "host_interjection", "speaker": h1,
                                 "text": "Let her finish.",
                                 "duration": 1.5, "shot": "", "transition": "",
                                 "act": beat["act"]})
        return enriched

    def _stub_camera_plan(self, beats: list) -> None:
        rules = {
            "line":              ("CU (close-up)",    "smooth"),
            "audience":          ("audience reaction", "hard cut"),
            "host_interjection": ("CU (close-up)",    "hard cut"),
            "pause":             ("2-shot",           "smooth"),
            "entrance":          ("entrance wide",    "hard cut"),
        }
        for b in beats:
            shot, trans = rules.get(b["type"], ("MS (medium)", "smooth"))
            b["shot"] = shot
            b["transition"] = trans

    # ── Auto-save dispatcher (one debouncer per kind) ──────────────
    def _schedule_silent_save(self, kind: str):
        """Debounced (~300ms) silent save. Silently dropped if autosave
        is paused (during apply_*) or no project is open."""
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

    # ── Tab ✅-on-complete marks ────────────────────────────────────
    def refresh_sub_tab_marks(self) -> tuple:
        """Update ✅ / ⚠ marks on each sub-tab. Returns (all_done, any_done) —
        MainWindow picks ✅ for all_done, ⚠ for partial (any but not all),
        and no mark otherwise on the top-level Studio shoot tab."""
        proj = self.main.current_project
        if not hasattr(self, "_sub_nb"):
            return (False, False)

        if proj:
            done_flags = {
                "brand":         self._has_brand_done(proj),
                "studio":        self._has_studio_done(proj),
                "characters":    self._has_characters_done(proj),
                "audience":      self._has_audience_done(proj),
                "voices":        self._has_voices_done_strict(proj),
                "storyboard":    self._has_storyboard_done(),
                "talking_heads": self._has_talking_heads_done(proj),
                "timeline":      self._has_timeline_done(proj),
            }
        else:
            done_flags = {k: False for k in self._sub_tabs}

        all_done = bool(done_flags) and all(done_flags.values())
        any_done = any(done_flags.values())
        for key, widget in self._sub_tabs.items():
            original = self._sub_tab_originals[key]
            done = done_flags.get(key, False)
            try:
                self._sub_nb.tab(widget,
                    text=(f"{original}  ✅" if done else original))
            except tk.TclError:
                pass
        return (all_done, any_done)

    def _has_storyboard_done(self) -> bool:
        """All 3 storyboard passes complete AND beats array non-empty."""
        if not self._beats:
            return False
        return all(self._pass_statuses.get(k) == "done"
                    for k in ("parse", "atmospherize", "camera"))

    @staticmethod
    def _has_brand_done(proj) -> bool:
        """Strict: requires brand.json AND a non-versioned logo file."""
        bd = proj / "brand"
        if not bd.exists():
            return False
        if not (bd / "brand.json").exists():
            return False
        return any(p.is_file() and not re.match(r"^logo\.v\d+\.", p.name)
                    for p in bd.glob("logo.*"))

    @staticmethod
    def _has_studio_done(proj) -> bool:
        """Strict: requires studio.json AND all 5 angle files present."""
        sd = proj / "studio"
        if not sd.exists():
            return False
        if not (sd / "studio.json").exists():
            return False
        versioned_re = re.compile(r"\.v\d+\.")
        for angle_key, _ in cfg.STUDIO_ANGLES:
            files = [p for p in sd.glob(f"{angle_key}.*")
                     if p.is_file() and not versioned_re.search(p.name)
                     and p.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp", ".svg")]
            if not files:
                return False
        return True

    def _has_characters_done(self, proj) -> bool:
        """Strict: every character in the step-1 cast has a face seed, all 4
        pose files, and an outfit selected in their params.json."""
        try:
            form = self.main._collect_form()
        except Exception:
            return False
        cast = self._resolve_characters_from_form(form)
        if not cast:
            return False
        cd = proj / "characters"
        if not cd.exists():
            return False
        versioned_re = re.compile(r"\.v\d+\.[a-z0-9]+$", re.IGNORECASE)
        pose_exts = {".png", ".jpg", ".jpeg", ".webp"}
        for char_id, _, _ in cast:
            sub = cd / char_id
            if not sub.is_dir():
                return False
            if not projects.character_face_path(proj, char_id).exists():
                return False
            params = projects.load_character_params(proj, char_id) or {}
            if not params.get("outfit_style"):
                return False
            for pose_key, _ in cfg.CHARACTER_POSES:
                files = [p for p in sub.glob(f"{pose_key}.*")
                         if p.is_file() and not versioned_re.search(p.name)
                         and p.suffix.lower() in pose_exts]
                if not files:
                    return False
        return True

    @staticmethod
    def _has_audience_done(proj) -> bool:
        """Strict: audience.json present AND all defined pose images saved."""
        ad = proj / "audience"
        if not ad.exists():
            return False
        if not (ad / "audience.json").exists():
            return False
        for pose_key, _ in cfg.AUDIENCE_POSES:
            files = [p for p in ad.glob(f"{pose_key}.*")
                     if p.is_file()
                     and p.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp")]
            if not files:
                return False
        return True

    def _has_voices_done_strict(self, proj) -> bool:
        """Strict: every cast character from step-1 form has a non-empty
        voice_id persisted in voices.json."""
        try:
            form = self.main._collect_form()
        except Exception:
            return False
        cast = self._resolve_characters_from_form(form)
        if not cast:
            return False
        vp = proj / "audio" / "voices.json"
        if not vp.exists():
            return False
        try:
            data = json.loads(vp.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return False
        voices = data.get("voices") or {}
        for char_id, _, _ in cast:
            entry = voices.get(char_id) or {}
            if not entry.get("voice_id"):
                return False
        return True

    @staticmethod
    def _has_timeline_done(proj) -> bool:
        tp = proj / "timeline.json"
        if not tp.exists():
            return False
        try:
            data = json.loads(tp.read_text(encoding="utf-8"))
            return bool(data.get("clips"))
        except (json.JSONDecodeError, OSError):
            return False

    def _do_silent_save(self, kind: str):
        setattr(self, f"_autosave_after_{kind}", None)
        if self.main._autosave_paused or not self.main.current_project:
            return
        try:
            proj = self.main.current_project
            if kind == "brand":
                projects.save_brand(proj, self._collect_brand())
            elif kind == "studio":
                projects.save_studio(proj, self._collect_studio())
            elif kind == "audience":
                projects.save_audience(proj, self._collect_audience())
            elif kind == "camera_plan":
                projects.save_camera_plan(proj, self._collect_camera_plan())
            elif kind == "voices":
                if self.current_voice_char_id:
                    self._voice_form_state[self.current_voice_char_id] = \
                        self._collect_voice_form()
                projects.save_voices(proj, {"voices": self._voice_form_state})
            elif kind == "characters":
                if self.current_char_id:
                    projects.save_character_params(
                        proj, self.current_char_id,
                        self._collect_character_form())
            elif kind == "storyboard":
                projects.save_storyboard(proj, {
                    "beats": self._beats,
                    "pass_statuses": self._pass_statuses})
            elif kind == "timeline":
                if self._timeline:
                    projects.save_timeline(proj, self._timeline)
            self.main._mark_autosaved()
            self.main._refresh_all_tab_marks()
        except Exception as e:
            from debug_log import DEBUG_LOG
            DEBUG_LOG.log_exception(f"autosave.{kind}", e)

    def apply_storyboard(self, project_path):
        """Load storyboard.json into state. Called by MainWindow on project open."""
        self._beats = []
        self._pass_statuses = {"parse": "pending",
                                "atmospherize": "pending",
                                "camera": "pending"}
        if project_path:
            data = projects.load_storyboard(project_path)
            self._beats = data.get("beats", []) or []
            loaded_status = data.get("pass_statuses") or {}
            for k in self._pass_statuses:
                if k in loaded_status:
                    self._pass_statuses[k] = loaded_status[k]
        # Make sure every beat carries a `parts` array — legacy storyboards
        # saved before the splitter existed don't have one, so populate
        # on the fly.
        if self._beats:
            self._split_beats_into_parts()
        if hasattr(self, "beats_tree"):
            self._refresh_beats_tree()
            self._refresh_pass_status_labels()
        # Pull the project's script.txt into the read-only preview so the
        # user sees what the pipeline is about to parse.
        self._load_script_preview()
        # If Voices tab is already built, refresh its lines list — beats just
        # changed and the per-character view depends on them.
        if hasattr(self, "lines_tree"):
            self._refresh_character_lines()
        # Talking heads cards need the new beats too.
        if hasattr(self, "th_inner"):
            self._refresh_talking_heads_cards()

    # ── 🎥 Camera plan sub-tab ──────────────────────────────────────
    # ── CAMERA PLAN — data lives in StringVars on self, edited via popup ─
    def _collect_camera_plan(self) -> dict:
        try:
            r = int(self._cam_reaction_pct_var.get())
        except (tk.TclError, ValueError):
            r = cfg.DEFAULT_CAMERA_PLAN["reaction_pct"]
        try:
            a = int(self._cam_audience_pct_var.get())
        except (tk.TclError, ValueError):
            a = cfg.DEFAULT_CAMERA_PLAN["audience_pct"]
        try:
            d = float(self._cam_avg_duration_var.get())
        except (tk.TclError, ValueError):
            d = cfg.DEFAULT_CAMERA_PLAN["avg_shot_duration"]
        return {
            "preset":             self._cam_preset_var.get(),
            "reaction_pct":       r,
            "audience_pct":       a,
            "avg_shot_duration":  d,
            "default_transition": self._cam_transition_var.get(),
            "wide_frequency":     self._cam_wide_freq_var.get(),
            "custom_rules":       self._cam_custom_rules,
        }

    def apply_camera_plan(self, data: dict):
        if not data:
            return
        if data.get("preset"):
            self._cam_preset_var.set(data["preset"])
        if "reaction_pct" in data:
            try:
                self._cam_reaction_pct_var.set(int(data["reaction_pct"]))
            except (TypeError, ValueError):
                pass
        if "audience_pct" in data:
            try:
                self._cam_audience_pct_var.set(int(data["audience_pct"]))
            except (TypeError, ValueError):
                pass
        if "avg_shot_duration" in data:
            try:
                self._cam_avg_duration_var.set(float(data["avg_shot_duration"]))
            except (TypeError, ValueError):
                pass
        if data.get("default_transition"):
            self._cam_transition_var.set(data["default_transition"])
        if data.get("wide_frequency"):
            self._cam_wide_freq_var.set(data["wide_frequency"])
        if "custom_rules" in data:
            self._cam_custom_rules = data["custom_rules"] or ""

    def _save_camera_plan(self):
        """Persist the current camera-plan StringVars to disk. Called by the
        popup's Save button and by the silent autosave dispatcher."""
        if not self.main.current_project:
            return None
        return projects.save_camera_plan(
            self.main.current_project, self._collect_camera_plan())

    def _open_camera_plan_dialog(self):
        if not self.main.current_project:
            messagebox.showwarning("⚠ No project",
                "Open or save a project first — camera plan is stored inside the project folder.",
                parent=self)
            return
        CameraPlanDialog(self, self)

    # ── 🗣 Talking heads sub-tab ────────────────────────────────────
    def _build_talking_heads_tab(self, parent):
        # Per-card widget + state refs: {beat_idx: {... ,"current_part": int}}
        self._th_cards: dict = {}
        self._th_thumb_refs: dict = {}
        self._th_ensemble_photo = None

        # Two-column layout: LEFT (1/3) / RIGHT (2/3)
        cols = ttk.Frame(parent); cols.pack(fill="both", expand=True)
        cols.columnconfigure(0, weight=1, uniform="th_cols")
        cols.columnconfigure(1, weight=2, uniform="th_cols")
        cols.rowconfigure(0, weight=1)
        left = ttk.Frame(cols); left.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        right = ttk.Frame(cols); right.grid(row=0, column=1, sticky="nsew")

        ens = SectionFrame(left, "🛋 Ensemble shot")
        ens.pack(fill="x", pady=(0, 8))
        self.th_ensemble_canvas = tk.Canvas(ens, height=240,
                                              background="#f4f4f4",
                                              highlightthickness=1,
                                              highlightbackground="#ddd")
        self.th_ensemble_canvas.pack(fill="x")
        self.th_ensemble_canvas.create_text(180, 120, text="🚧 Not rendered",
                                              fill="#999", font=("", 10))
        self.th_ensemble_canvas.bind("<Button-1>",
            lambda _e: self._show_ensemble_popup())
        self.th_ensemble_canvas.configure(cursor="hand2")
        ens_btns = ttk.Frame(ens); ens_btns.pack(fill="x", pady=(6, 0))
        gen_ens_btn = ttk.Button(ens_btns, text="🎬 Generate",
                                   command=self._generate_ensemble_shot)
        gen_ens_btn.pack(side="left")
        Tooltip(gen_ens_btn,
            "Render the wide ensemble shot using each cast member's seated "
            "pose as identity reference + the cam2_guests studio backdrop. "
            "Reference image only — not used in the timeline.")
        retry_ens_btn = ttk.Button(ens_btns, text="🔄 Re-render",
                                     command=self._generate_ensemble_shot)
        retry_ens_btn.pack(side="left", padx=(6, 0))
        Tooltip(retry_ens_btn,
            "Re-render with the current prompt. Previous file rotates as .v<N>.")

        pf = SectionFrame(left, "📝 Prompt for this shot")
        pf.pack(fill="x", pady=(0, 8))
        self.th_arrangement = tk.Text(pf, height=5, wrap="word", font=("", 9))
        self.th_arrangement.pack(fill="both", expand=False)
        self.th_arrangement.insert("1.0",
            "Hosts at the table on the left; heroine at the centre of the "
            "sofa; friends on either side; expert beside them; antagonist "
            "at the far end. Camera POV: cam2_guests facing the sofa.")
        ttk.Label(pf,
            text="ℹ The cast list (names + roles) is appended automatically.",
            foreground="grey", wraplength=380, font=("", 8, "italic")
        ).pack(anchor="w", pady=(2, 0))

        gf = SectionFrame(left, "⚙ Generation settings")
        gf.pack(fill="x", pady=(0, 8))
        ttk.Label(gf, text="Image engine (keyframes + ensemble):",
                  foreground="#444", font=("", 9)).pack(anchor="w")
        ModelPicker(gf, kind="image", main_window=self.main,
                     label_text="",
                     exclude_slugs=["recraft/recraft-v4.1-vector"]
                     ).pack(anchor="w", pady=(0, 6))
        ttk.Label(gf, text="Text engine (narrative style analysis):",
                  foreground="#444", font=("", 9)).pack(anchor="w")
        ModelPicker(gf, kind="text", main_window=self.main,
                     label_text="").pack(anchor="w")

        af = SectionFrame(left, "🎭 Narrative style analysis")
        af.pack(fill="x", pady=(0, 8))
        ttk.Label(af,
            text="One LLM call per act (4 total). For each speaking part the "
                 "model proposes 3 physical-performance descriptions — head "
                 "movements, posture, gestures. The Style dropdown becomes "
                 "enabled afterwards.",
            foreground="grey", wraplength=380, font=("", 9)
        ).pack(anchor="w", pady=(0, 4))
        an_btn_row = ttk.Frame(af); an_btn_row.pack(fill="x", pady=(0, 4))
        analyze_btn = ttk.Button(an_btn_row, text="🎭 Analyze narrative style",
                                   command=self._run_narrative_style_analysis)
        analyze_btn.pack(side="left")
        Tooltip(analyze_btn,
            "Runs 4 sequential LLM calls (one per act) using the text engine "
            "above. Output: 3 style options per speaking part, stored in "
            "storyboard.json.")
        self.th_analyze_status_var = tk.StringVar(value="(not analyzed)")
        ttk.Label(af, textvariable=self.th_analyze_status_var,
                  foreground="grey", wraplength=380,
                  font=("", 9)).pack(anchor="w", pady=(2, 0))

        self.th_status_var = tk.StringVar(value="")
        ttk.Label(left, textvariable=self.th_status_var,
                  foreground="grey", wraplength=380,
                  font=("", 9)).pack(anchor="w", pady=(4, 0))

        # ── RIGHT ─────────────────────────────────────────────────
        list_hdr = ttk.Frame(right); list_hdr.pack(fill="x", pady=(0, 4))
        self.th_lines_title_var = tk.StringVar(value="(loading beats…)")
        ttk.Label(list_hdr, textvariable=self.th_lines_title_var,
                  font=("", 10, "bold")).pack(side="left")
        HelpIcon(list_hdr,
            "Speaking beats from the storyboard, in their natural order. "
            "Narrator beats are hidden. Each card shows the per-part "
            "keyframe + line text + audio + head orientation + Style picker. "
            "Beats split into multiple parts use ◀ / ▶ to navigate."
        ).pack(side="left")
        batch_kf_btn = ttk.Button(list_hdr, text="🎬 Render all missing keyframes",
                                    command=self._render_all_missing_keyframes)
        batch_kf_btn.pack(side="right")
        Tooltip(batch_kf_btn,
            "Batch-render every speaking part that doesn't yet have a "
            "keyframe file. Skips parts already on disk.")
        batch_tts_btn = ttk.Button(list_hdr, text="🎙 Generate missing voices",
                                     command=self._render_all_missing_voices)
        batch_tts_btn.pack(side="right", padx=(0, 6))
        Tooltip(batch_tts_btn,
            "Batch-render TTS for every speaking part that doesn't yet have "
            "an audio file. Mirrors the Voices tab's batch action, but runs "
            "for all characters at once.")

        list_frame = ttk.Frame(right); list_frame.pack(fill="both", expand=True)
        self.th_canvas = tk.Canvas(list_frame, background="#fafafa",
                                     highlightthickness=0)
        self.th_canvas.pack(side="left", fill="both", expand=True)
        th_scroll = ttk.Scrollbar(list_frame, orient="vertical",
                                    command=self.th_canvas.yview)
        th_scroll.pack(side="right", fill="y")
        self.th_canvas.configure(yscrollcommand=th_scroll.set)
        self.th_inner = ttk.Frame(self.th_canvas)
        self.th_inner_id = self.th_canvas.create_window(
            (0, 0), window=self.th_inner, anchor="nw")
        self.th_canvas.bind("<Configure>",
            lambda e: self.th_canvas.itemconfigure(
                self.th_inner_id, width=e.width))
        self.th_inner.bind("<Configure>",
            lambda _e: self.th_canvas.configure(
                scrollregion=self.th_canvas.bbox("all")))
        self.th_canvas.bind("<Enter>",
            lambda _e: self._bind_th_mousewheel(True))
        self.th_canvas.bind("<Leave>",
            lambda _e: self._bind_th_mousewheel(False))

        self._refresh_talking_heads_cards()
        self._reload_ensemble_thumbnail()

    def _bind_th_mousewheel(self, on: bool):
        if on:
            self.th_canvas.bind_all("<MouseWheel>", self._on_th_mousewheel)
        else:
            try:
                self.th_canvas.unbind_all("<MouseWheel>")
            except tk.TclError:
                pass

    def _on_th_mousewheel(self, event):
        try:
            self.th_canvas.yview_scroll(int(-event.delta / 120), "units")
        except tk.TclError:
            pass

    def apply_talking_heads(self, project_path):
        if hasattr(self, "th_inner"):
            self._refresh_talking_heads_cards()
            self._reload_ensemble_thumbnail()

    def _has_talking_heads_done(self, proj) -> bool:
        if not self._beats:
            return False
        if not projects.ensemble_shot_path(proj).exists():
            ens_versioned = list(projects.keyframe_dir(proj).glob("ensemble_seated.*"))
            if not any(p.is_file() and p.suffix.lower() in
                        (".png", ".jpg", ".jpeg", ".webp") for p in ens_versioned):
                return False
        speaker_map = self._build_speaker_to_char_map()
        kf_dir = projects.keyframe_dir(proj)
        versioned_re = re.compile(r"\.v\d+\.[a-z0-9]+$", re.IGNORECASE)
        for i, beat in enumerate(self._beats):
            if beat.get("type") not in ("line", "host_interjection"):
                continue
            speaker = beat.get("speaker") or ""
            if not speaker.strip():
                continue
            char_id = self._resolve_char_id_from_speaker(speaker, speaker_map)
            if char_id == "narrator":
                continue
            slug = projects.speaker_slugify(speaker)
            for p_zero, _part in enumerate(beat.get("parts") or []):
                part_idx = p_zero + 1
                files = [p for p in kf_dir.glob(
                            f"beat_{i:04}_{slug}_p{part_idx}.*")
                         if p.is_file() and not versioned_re.search(p.name)
                         and p.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp")]
                if not files:
                    return False
        return True

    def _talking_heads_speaking_beats(self):
        speaker_map = self._build_speaker_to_char_map()
        out = []
        for i, b in enumerate(self._beats):
            if b.get("type") not in ("line", "host_interjection"):
                continue
            speaker = (b.get("speaker") or "").strip()
            if not speaker:
                continue
            if self._resolve_char_id_from_speaker(speaker, speaker_map) == "narrator":
                continue
            out.append((i, b))
        return out

    def _refresh_talking_heads_cards(self):
        if not hasattr(self, "th_inner"):
            return
        for child in self.th_inner.winfo_children():
            child.destroy()
        self._th_cards.clear()
        self._th_thumb_refs.clear()

        speaking = self._talking_heads_speaking_beats()
        if not speaking:
            self.th_lines_title_var.set(
                "0 speaking beats — run Storyboard → Parse first.")
            ttk.Label(self.th_inner,
                text="🚧 No beats to render yet. Run the Storyboard pipeline first.",
                foreground="#999", padding=20).pack(anchor="w")
            self._refresh_analyze_status()
            return

        rendered_parts = 0
        total_parts = 0
        for beat_idx, beat in speaking:
            parts = beat.get("parts") or []
            total_parts += len(parts)
            slug = projects.speaker_slugify(beat.get("speaker") or "")
            for p_zero in range(len(parts)):
                if self._current_keyframe_path(beat_idx, slug, p_zero + 1):
                    rendered_parts += 1
        self.th_lines_title_var.set(
            f"{len(speaking)} beat(s) / {total_parts} part(s) — "
            f"{rendered_parts} rendered, {total_parts - rendered_parts} missing")

        speaker_map = self._build_speaker_to_char_map()
        for beat_idx, beat in speaking:
            self._build_beat_card(self.th_inner, beat_idx, beat, speaker_map)
        self._refresh_analyze_status()

    def _refresh_analyze_status(self):
        if not hasattr(self, "th_analyze_status_var"):
            return
        speaking = self._talking_heads_speaking_beats()
        total = sum(len(b.get("parts") or []) for _i, b in speaking)
        analyzed = 0
        for _i, b in speaking:
            for part in b.get("parts") or []:
                if part.get("style_options"):
                    analyzed += 1
        if not total:
            self.th_analyze_status_var.set("(no parts to analyze)")
        elif analyzed == 0:
            self.th_analyze_status_var.set(
                "(not analyzed — click 🎭 Analyze)")
        elif analyzed < total:
            self.th_analyze_status_var.set(
                f"({analyzed}/{total} parts analyzed)")
        else:
            self.th_analyze_status_var.set(
                f"✅ All {total} parts analyzed")

    def _current_keyframe_path(self, beat_idx: int, speaker_slug: str,
                                 part_idx: int):
        if not self.main.current_project:
            return None
        kf_dir = projects.keyframe_dir(self.main.current_project)
        if not kf_dir.exists():
            return None
        versioned_re = re.compile(r"\.v\d+\.[a-z0-9]+$", re.IGNORECASE)
        for p in kf_dir.glob(f"beat_{beat_idx:04}_{speaker_slug}_p{part_idx}.*"):
            if (p.is_file() and not versioned_re.search(p.name)
                    and p.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp")):
                return p
        return None

    def _current_video_path(self, beat_idx: int, speaker_slug: str,
                              part_idx: int):
        if not self.main.current_project:
            return None
        vp = projects.video_beat_path(
            self.main.current_project, beat_idx, speaker_slug, part_idx)
        return vp if vp.exists() else None

    def _default_thumb_path_for_part(self, beat_idx: int, beat: dict,
                                       part_idx: int):
        if not self.main.current_project:
            return None, None
        speaker = beat.get("speaker") or ""
        slug = projects.speaker_slugify(speaker)
        vp = self._current_video_path(beat_idx, slug, part_idx)
        if vp:
            return vp, "video"
        kf = self._current_keyframe_path(beat_idx, slug, part_idx)
        if kf:
            return kf, "keyframe"
        speaker_map = self._build_speaker_to_char_map()
        char_id = self._resolve_char_id_from_speaker(speaker, speaker_map)
        if not char_id:
            return None, None
        cd = projects.character_dir(self.main.current_project, char_id)
        if not cd.exists():
            return None, None
        versioned_re = re.compile(r"\.v\d+\.[a-z0-9]+$", re.IGNORECASE)
        for candidate in ("seated", "portrait"):
            files = [p for p in cd.glob(f"{candidate}.*")
                     if p.is_file() and not versioned_re.search(p.name)
                     and p.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp")]
            if files:
                return files[0], "pose"
        return None, None

    def _build_beat_card(self, parent, beat_idx: int, beat: dict, speaker_map: dict):
        parts = beat.get("parts") or []
        part_count = len(parts)
        speaker = beat.get("speaker") or "(unknown)"
        char_id = self._resolve_char_id_from_speaker(speaker, speaker_map)
        role = cfg.role_for_char_id(char_id) if char_id else cfg.DEFAULT_ROLE
        shot = beat.get("shot") or "—"
        duration = beat.get("duration") or 0.0
        transition = beat.get("transition") or "—"

        card = ttk.Frame(parent, padding=8, borderwidth=1, relief="solid")
        card.pack(fill="x", padx=4, pady=4)

        hdr = ttk.Frame(card); hdr.pack(fill="x")
        ttk.Label(hdr, text=f"#{beat_idx + 1}",
                  foreground="#888", width=5).pack(side="left")
        ttk.Label(hdr, text=speaker, font=("", 10, "bold")).pack(
            side="left", padx=(2, 6))
        ttk.Label(hdr, text=f"· {role}", foreground="#888").pack(side="left")
        ttk.Label(hdr, text=f"· shot: {shot}", foreground="#888").pack(
            side="left", padx=(8, 0))
        ttk.Label(hdr, text=f"· {duration:.1f}s · {transition}",
                  foreground="#888").pack(side="left", padx=(8, 0))

        part_nav = ttk.Frame(card); part_nav.pack(fill="x", pady=(4, 0))
        part_label_var = tk.StringVar(
            value=(f"Part 1/{part_count}" if part_count > 1 else ""))
        if part_count > 1:
            prev_btn = ttk.Button(part_nav, text="◀", width=3,
                command=lambda b=beat_idx: self._th_prev_part(b))
            prev_btn.pack(side="left")
            ttk.Label(part_nav, textvariable=part_label_var,
                      foreground="#444",
                      font=("", 9, "bold")).pack(side="left", padx=(6, 6))
            next_btn = ttk.Button(part_nav, text="▶", width=3,
                command=lambda b=beat_idx: self._th_next_part(b))
            next_btn.pack(side="left")

        body = ttk.Frame(card); body.pack(fill="x", pady=(6, 0))
        body.columnconfigure(1, weight=1)

        thumb = tk.Canvas(body, width=200, height=150,
                           background="#f4f4f4",
                           highlightthickness=1, highlightbackground="#ddd")
        thumb.grid(row=0, column=0, rowspan=6, sticky="nw", padx=(0, 8))
        thumb.bind("<Button-1>",
            lambda _e, b=beat_idx: self._show_part_thumb_popup(b))
        thumb.configure(cursor="hand2")

        text_lbl = ttk.Label(body, text="", wraplength=600, justify="left",
                              foreground="#222")
        text_lbl.grid(row=0, column=1, sticky="ew")

        audio_row = ttk.Frame(body); audio_row.grid(
            row=1, column=1, sticky="w", pady=(6, 0))
        play_btn = ttk.Button(audio_row, text="▶ Play audio",
                               command=lambda b=beat_idx:
                                   self._th_play_part_audio(b))
        play_btn.pack(side="left")
        gen_audio_btn = ttk.Button(audio_row, text="🔄 Generate audio",
                                     command=lambda b=beat_idx:
                                         self._th_generate_part_audio(b))
        gen_audio_btn.pack(side="left", padx=(6, 0))
        Tooltip(gen_audio_btn,
            "Render the current part's TTS audio inline (same as Voices tab).")

        head_var = tk.StringVar(value=cfg.DEFAULT_HEAD_ORIENTATION)
        head_custom_var = tk.StringVar(value="")
        radio_row = ttk.Frame(body); radio_row.grid(
            row=2, column=1, sticky="w", pady=(8, 0))
        ttk.Label(radio_row, text="Head:",
                  foreground="#444").pack(side="left", padx=(0, 6))
        for o in cfg.TALKING_HEAD_ORIENTATIONS:
            rb = ttk.Radiobutton(radio_row, text=o["label"],
                                  variable=head_var, value=o["key"],
                                  command=lambda b=beat_idx:
                                      self._th_save_part_state(b))
            rb.pack(side="left", padx=(0, 6))
        head_row2 = ttk.Frame(body); head_row2.grid(
            row=3, column=1, sticky="ew", pady=(2, 0))
        ttk.Label(head_row2, text="Custom head:",
                  foreground="#888", font=("", 8)).pack(side="left")
        head_custom_entry = ttk.Entry(head_row2, textvariable=head_custom_var)
        head_custom_entry.pack(side="left", fill="x", expand=True, padx=(4, 6))
        Tooltip(head_custom_entry,
            "Free-form text overrides the radio above when non-empty.")
        head_custom_var.trace_add("write",
            lambda *_a, b=beat_idx: self._th_save_part_state(b))

        style_row = ttk.Frame(body); style_row.grid(
            row=4, column=1, sticky="ew", pady=(4, 0))
        ttk.Label(style_row, text="Style:",
                  foreground="#444").pack(side="left", padx=(0, 6))
        style_var = tk.StringVar(value="(run 🎭 Analyze to populate)")
        style_combo = ttk.Combobox(style_row, textvariable=style_var,
                                     state="readonly", width=60)
        style_combo.pack(side="left", fill="x", expand=True)
        style_combo.bind("<<ComboboxSelected>>",
            lambda _e, b=beat_idx: self._th_save_part_state(b))
        Tooltip(style_combo,
            "Picks the physical-performance description that will be passed "
            "to the talking-head video render. Populated by 🎭 Analyze.")

        style_row2 = ttk.Frame(body); style_row2.grid(
            row=5, column=1, sticky="ew", pady=(2, 0))
        ttk.Label(style_row2, text="Custom style:",
                  foreground="#888", font=("", 8)).pack(side="left")
        style_custom_var = tk.StringVar(value="")
        style_custom_entry = ttk.Entry(style_row2,
            textvariable=style_custom_var)
        style_custom_entry.pack(side="left", fill="x", expand=True, padx=(4, 6))
        Tooltip(style_custom_entry,
            "Free-form text overrides the Style dropdown when non-empty.")
        style_custom_var.trace_add("write",
            lambda *_a, b=beat_idx: self._th_save_part_state(b))
        rerender_btn = ttk.Button(style_row2, text="🔄 Re-render keyframe",
                                    command=lambda b=beat_idx:
                                        self._rerender_keyframe(b))
        rerender_btn.pack(side="left")
        Tooltip(rerender_btn,
            "Re-render this part's keyframe with the selected head + style.")

        self._th_cards[beat_idx] = {
            "card":            card,
            "thumb":           thumb,
            "text_label":      text_lbl,
            "part_label_var":  part_label_var,
            "head_var":        head_var,
            "head_custom_var": head_custom_var,
            "style_var":       style_var,
            "style_combo":     style_combo,
            "style_custom_var": style_custom_var,
            "current_part":    1,
        }
        self._show_part(beat_idx, 1)

    def _show_part(self, beat_idx: int, part_idx: int):
        card = self._th_cards.get(beat_idx)
        if not card:
            return
        beat = self._beats[beat_idx]
        parts = beat.get("parts") or []
        if part_idx < 1 or part_idx > len(parts):
            part_idx = 1
        part = parts[part_idx - 1] if parts else {}
        card["current_part"] = part_idx
        card["part_label_var"].set(
            f"Part {part_idx}/{len(parts)}" if len(parts) > 1 else "")
        card["text_label"].configure(text=part.get("text") or "")

        orient = part.get("head_orientation") or cfg.DEFAULT_HEAD_ORIENTATION
        head_custom = part.get("head_custom") or ""
        card["head_var"].set(orient)
        card["head_custom_var"].set(head_custom)

        options = part.get("style_options") or []
        if options:
            card["style_combo"].configure(state="readonly", values=options)
            sel = int(part.get("style_selected_idx") or 0)
            if not (0 <= sel < len(options)):
                sel = 0
            card["style_var"].set(options[sel])
        else:
            card["style_combo"].configure(state="disabled", values=[])
            card["style_var"].set("(run 🎭 Analyze to populate)")
        card["style_custom_var"].set(part.get("style_custom") or "")

        path, kind = self._default_thumb_path_for_part(beat_idx, beat, part_idx)
        if path:
            self._render_th_thumb_path(beat_idx, path,
                overlay_play=(kind == "video"))
        else:
            self._paint_th_thumb_placeholder(beat_idx)

    def _render_th_thumb_path(self, beat_idx: int, original_path,
                                overlay_play: bool = False):
        card = self._th_cards.get(beat_idx)
        if not card:
            return
        try:
            cw = max(card["thumb"].winfo_width(), 200)
            ch = max(card["thumb"].winfo_height(), 150)
        except tk.TclError:
            cw, ch = 200, 150
        self._th_thumb_refs[beat_idx] = display_image_path_on_canvas(
            card["thumb"], original_path, self.main.current_project, cw, ch)
        if overlay_play:
            try:
                card["thumb"].create_text(cw // 2, ch // 2,
                    text="▶", fill="#fff", font=("", 32, "bold"))
            except tk.TclError:
                pass

    def _paint_th_thumb_placeholder(self, beat_idx: int):
        card = self._th_cards.get(beat_idx)
        if not card:
            return
        c = card["thumb"]
        c.delete("all")
        c.create_text(100, 75, text="🚧 No image",
                       fill="#999", font=("", 9))

    def _th_prev_part(self, beat_idx: int):
        card = self._th_cards.get(beat_idx)
        if not card:
            return
        cur = card["current_part"]
        if cur > 1:
            self._show_part(beat_idx, cur - 1)

    def _th_next_part(self, beat_idx: int):
        card = self._th_cards.get(beat_idx)
        if not card:
            return
        cur = card["current_part"]
        parts = self._beats[beat_idx].get("parts") or []
        if cur < len(parts):
            self._show_part(beat_idx, cur + 1)

    def _th_save_part_state(self, beat_idx: int):
        card = self._th_cards.get(beat_idx)
        if not card:
            return
        part_idx = card["current_part"]
        parts = self._beats[beat_idx].get("parts") or []
        if part_idx < 1 or part_idx > len(parts):
            return
        part = parts[part_idx - 1]
        part["head_orientation"] = card["head_var"].get()
        part["head_custom"] = card["head_custom_var"].get()
        part["style_custom"] = card["style_custom_var"].get()
        options = part.get("style_options") or []
        cur_val = card["style_var"].get()
        try:
            part["style_selected_idx"] = options.index(cur_val) if options else 0
        except ValueError:
            part["style_selected_idx"] = 0
        if self.main.current_project:
            try:
                projects.save_storyboard(self.main.current_project, {
                    "beats": self._beats,
                    "pass_statuses": self._pass_statuses,
                })
            except OSError:
                pass

    def _show_part_thumb_popup(self, beat_idx: int):
        card = self._th_cards.get(beat_idx)
        if not card:
            return
        part_idx = card["current_part"]
        beat = self._beats[beat_idx]
        path, _kind = self._default_thumb_path_for_part(beat_idx, beat, part_idx)
        if path:
            show_image_popup(self, path)

    def _show_ensemble_popup(self):
        if not self.main.current_project:
            return
        path = projects.ensemble_shot_path(self.main.current_project)
        if path.exists():
            show_image_popup(self, path)

    def _th_play_part_audio(self, beat_idx: int):
        card = self._th_cards.get(beat_idx)
        if not card:
            return
        part_idx = card["current_part"]
        if not self.main.current_project:
            return
        beat = self._beats[beat_idx]
        slug = projects.speaker_slugify(beat.get("speaker") or "")
        path = projects.audio_beat_path(
            self.main.current_project, beat_idx, slug, part_idx=part_idx)
        if not path.exists():
            self.th_status_var.set(
                f"ℹ No audio for #{beat_idx + 1}.{part_idx} — "
                f"click 🔄 Generate audio.")
            return
        try:
            import audio_player
            audio_player.play(path)
            self.th_status_var.set(f"▶ Playing #{beat_idx + 1}.{part_idx}")
        except RuntimeError as e:
            self.th_status_var.set(
                f"❌ {e}".replace("\n", " ").replace("  ", " ")[:300])

    def _th_generate_part_audio(self, beat_idx: int):
        if not self._require_project():
            return
        if not self.main.settings.get("elevenlabs_api_key"):
            messagebox.showwarning("⚠ Missing API key",
                "ElevenLabs API key is not set.", parent=self)
            return
        card = self._th_cards.get(beat_idx)
        if not card:
            return
        part_idx = card["current_part"]
        self.th_status_var.set(
            f"🔄 Rendering audio for #{beat_idx + 1}.{part_idx}…")

        def worker():
            try:
                self._render_single_part_sync(beat_idx, part_idx)
                self.after(0, lambda: self.th_status_var.set(
                    f"✅ Audio #{beat_idx + 1}.{part_idx} rendered."))
                self.after(0, lambda: self._th_play_part_audio(beat_idx))
            except Exception as e:
                err = str(e)
                self.after(0, lambda: self.th_status_var.set(
                    f"❌ Audio render failed: {err[:240]}"))

        threading.Thread(target=worker, daemon=True).start()

    def _build_head_orientation_phrase_for_part(self, beat_idx: int,
                                                   part_idx: int) -> str:
        beat = self._beats[beat_idx]
        parts = beat.get("parts") or []
        if part_idx < 1 or part_idx > len(parts):
            return cfg.head_orientation_description(cfg.DEFAULT_HEAD_ORIENTATION)
        part = parts[part_idx - 1]
        custom = (part.get("head_custom") or "").strip()
        if custom:
            return custom
        return cfg.head_orientation_description(
            part.get("head_orientation") or cfg.DEFAULT_HEAD_ORIENTATION)

    def _validate_image_engine(self) -> bool:
        provider = self.main.image_provider_var.get()
        if provider != "openrouter":
            messagebox.showwarning("⚠ Provider not wired",
                f"Image provider '{provider}' is not wired yet. "
                "Switch to 'openrouter' in the engine picker.", parent=self)
            return False
        model_slug = self.main.image_model_slug_var.get()
        if not model_slug or model_slug == "recraft/recraft-v4.1-vector":
            messagebox.showwarning("⚠ Wrong model",
                "Pick a raster image model in the engine picker.",
                parent=self)
            return False
        return True

    def _do_keyframe_render(self, beat_idx: int, part_idx: int,
                              identity_ref: bytes) -> tuple:
        beat = self._beats[beat_idx]
        speaker = beat.get("speaker") or "(unknown)"
        speaker_map = self._build_speaker_to_char_map()
        char_id = self._resolve_char_id_from_speaker(speaker, speaker_map)
        role = cfg.role_for_char_id(char_id) if char_id else cfg.DEFAULT_ROLE
        params = self._character_form_state.get(char_id) or {}
        if not params and self.main.current_project and char_id:
            params = projects.load_character_params(
                self.main.current_project, char_id) or {}
        gender = params.get("gender") or "Any"
        shot = beat.get("shot") or cfg.DEFAULT_KEYFRAME_SHOT
        framing = cfg.KEYFRAME_FRAMING_BY_SHOT.get(
            shot, cfg.KEYFRAME_FRAMING_BY_SHOT[cfg.DEFAULT_KEYFRAME_SHOT])
        head_phrase = self._build_head_orientation_phrase_for_part(beat_idx, part_idx)

        # ── DIALOGUE & KEYFRAME PRE-ANALYSIS AGENT (Sprint 2.1) ──────
        parts = beat.get("parts") or []
        part = parts[part_idx - 1] if 1 <= part_idx <= len(parts) else {}
        dialogue_text = part.get("text") or ""
        
        # Determine chosen performance/emotional style
        style_custom = part.get("style_custom") or ""
        style_options = part.get("style_options") or []
        style_selected_idx = part.get("style_selected_idx") or 0
        if style_custom.strip():
            style_guideline = style_custom.strip()
        elif style_options and 0 <= style_selected_idx < len(style_options):
            style_guideline = style_options[style_selected_idx].strip()
        else:
            style_guideline = "Neutral expression, professional talk-show guest posture."

        # Run the Dialogue Pre-Analysis Agent pass using LLM to generate starting visual description
        try:
            from debug_log import DEBUG_LOG
            DEBUG_LOG.log_info("keyframe_pre_analysis",
                               f"Running dialogue analysis for beat {beat_idx + 1}.{part_idx}")
            client = self.main._build_client()
            sys_template = PROMPT_STORE.get_active_template("keyframe_pre_analysis_system")
            user_prompt = PROMPT_STORE.render("keyframe_pre_analysis_user",
                character_name=speaker,
                role=role,
                gender=gender,
                framing=framing,
                head_orientation=head_phrase,
                dialogue_text=dialogue_text,
                style_guideline=style_guideline)
            visual_pose_description = client.complete(
                system=sys_template, user=user_prompt, max_tokens=1000, temperature=0.6)
            visual_pose_description = visual_pose_description.strip()
            DEBUG_LOG.log_info("keyframe_pre_analysis",
                               f"Analysis result: {visual_pose_description}")
        except Exception as e:
            from debug_log import DEBUG_LOG
            DEBUG_LOG.log_exception("keyframe_pre_analysis_failed", e)
            visual_pose_description = style_guideline

        prompt = PROMPT_STORE.render("keyframe_prompt",
            shot_label=shot,
            character_name=speaker,
            role=role,
            gender=gender,
            framing=framing,
            head_orientation=head_phrase,
            visual_pose_description=visual_pose_description)
        model_slug = self.main.image_model_slug_var.get()
        from llm_clients import OpenRouterClient
        client = OpenRouterClient(
            self.main.settings.get("openrouter_api_key", ""), model_slug)
        return client.generate_image(prompt, model=model_slug,
            aspect_ratio="16:9",
            reference_image_bytes=[identity_ref])

    def _rerender_keyframe(self, beat_idx: int):
        if not self._require_project():
            return
        if not self._validate_image_engine():
            return
        card = self._th_cards.get(beat_idx)
        if not card:
            return
        part_idx = card["current_part"]
        self._th_save_part_state(beat_idx)

        beat = self._beats[beat_idx]
        speaker = beat.get("speaker") or "(unknown)"
        speaker_map = self._build_speaker_to_char_map()
        char_id = self._resolve_char_id_from_speaker(speaker, speaker_map)
        identity_ref = self._read_keyframe_identity_ref(
            self.main.current_project, char_id, "seated")
        if identity_ref is None:
            messagebox.showwarning("⚠ No identity reference",
                f"No seated / portrait pose for '{speaker}' (char_id '{char_id}'). "
                "Generate poses on the Characters tab first.", parent=self)
            return

        speaker_slug = projects.speaker_slugify(speaker)
        self.th_status_var.set(
            f"🔄 Re-rendering keyframe for #{beat_idx + 1}.{part_idx}…")

        def worker():
            try:
                img_bytes, ext = self._do_keyframe_render(
                    beat_idx, part_idx, identity_ref)
                proj = self.main.current_project
                kf_dir = projects.keyframe_dir(proj)
                kf_dir.mkdir(parents=True, exist_ok=True)
                stem = f"beat_{beat_idx:04}_{speaker_slug}_p{part_idx}"
                versioned_re = re.compile(rf"^{re.escape(stem)}\.v\d+\.")
                import thumbnails as _th
                for old in kf_dir.glob(f"{stem}.*"):
                    if old.is_file() and not versioned_re.match(old.name):
                        n = 1
                        while (kf_dir / f"{stem}.v{n}{old.suffix}").exists():
                            n += 1
                        rotated = kf_dir / f"{stem}.v{n}{old.suffix}"
                        try:
                            old.rename(rotated)
                            _th.rotate_thumbnail(proj, old, rotated)
                        except OSError:
                            pass
                target = projects.keyframe_path(
                    proj, beat_idx, speaker_slug, ext=ext, part_idx=part_idx)
                target.write_bytes(img_bytes)
                try:
                    _th.ensure_thumbnail(proj, target)
                except Exception:
                    pass
                self.after(0, lambda: self._show_part(beat_idx, part_idx))
                self.after(0, lambda: self.th_status_var.set(
                    f"✅ Keyframe saved: {target.name}"))
                self.after(0, self.main._refresh_all_tab_marks)
            except Exception as e:
                err = str(e)
                self.after(0, lambda: self.th_status_var.set(
                    f"❌ Keyframe failed: {err[:240]}"))

        threading.Thread(target=worker, daemon=True).start()

    def _render_all_missing_keyframes(self):
        if not self._require_project():
            return
        if not self._validate_image_engine():
            return
        speaker_map = self._build_speaker_to_char_map()
        proj = self.main.current_project
        missing: list = []
        for beat_idx, beat in self._talking_heads_speaking_beats():
            slug = projects.speaker_slugify(beat.get("speaker") or "")
            for p_zero in range(len(beat.get("parts") or [])):
                part_idx = p_zero + 1
                if self._current_keyframe_path(beat_idx, slug, part_idx) is None:
                    missing.append((beat_idx, part_idx))
        if not missing:
            self.th_status_var.set("ℹ Already rendered — no missing keyframes.")
            return
        total = len(missing)
        self.th_status_var.set(f"🔄 Rendering {total} missing keyframe(s)…")

        def worker():
            done = 0
            failed = 0
            for n, (beat_idx, part_idx) in enumerate(missing):
                beat = self._beats[beat_idx]
                speaker = beat.get("speaker") or "(unknown)"
                char_id = self._resolve_char_id_from_speaker(speaker, speaker_map)
                identity_ref = self._read_keyframe_identity_ref(
                    proj, char_id, "seated")
                if identity_ref is None:
                    failed += 1
                    self.after(0, lambda b=beat_idx, q=part_idx, s=speaker:
                        self.th_status_var.set(
                            f"⚠ Skip #{b + 1}.{q} — no seated/portrait for '{s}'"))
                    continue
                try:
                    img_bytes, ext = self._do_keyframe_render(
                        beat_idx, part_idx, identity_ref)
                    speaker_slug = projects.speaker_slugify(speaker)
                    target = projects.keyframe_path(
                        proj, beat_idx, speaker_slug, ext=ext,
                        part_idx=part_idx)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(img_bytes)
                    try:
                        import thumbnails as _th
                        _th.ensure_thumbnail(proj, target)
                    except Exception:
                        pass
                    done += 1
                    self.after(0, lambda b=beat_idx, q=part_idx:
                        self._show_part(b, q))
                    self.after(0, lambda n_=n, t=total, b=beat_idx, q=part_idx:
                        self.th_status_var.set(
                            f"🔄 Rendered #{b + 1}.{q} ({n_ + 1}/{t})"))
                except Exception as e:
                    failed += 1
                    self.after(0, lambda b=beat_idx, q=part_idx, m=str(e):
                        self.th_status_var.set(
                            f"⚠ #{b + 1}.{q}: {m[:160]}"))
            self.after(0, lambda: self.th_status_var.set(
                f"✅ Keyframe batch done — {done} rendered, {failed} failed."))
            self.after(0, self._refresh_talking_heads_cards)
            self.after(0, self.main._refresh_all_tab_marks)

        threading.Thread(target=worker, daemon=True).start()

    def _render_all_missing_voices(self):
        if not self._require_project():
            return
        if not self.main.settings.get("elevenlabs_api_key"):
            messagebox.showwarning("⚠ Missing API key",
                "ElevenLabs API key is not set. Add it in ⚙ Settings.",
                parent=self)
            return
        proj = self.main.current_project
        missing: list = []
        for beat_idx, beat in self._talking_heads_speaking_beats():
            slug = projects.speaker_slugify(beat.get("speaker") or "")
            for p_zero, part in enumerate(beat.get("parts") or []):
                part_idx = p_zero + 1
                if not (part.get("text") or "").strip():
                    continue
                path = projects.audio_beat_path(
                    proj, beat_idx, slug, part_idx=part_idx)
                if not path.exists():
                    missing.append((beat_idx, part_idx))
        if not missing:
            self.th_status_var.set("ℹ Already rendered — no missing audio.")
            return
        total = len(missing)
        self.th_status_var.set(f"🔄 Rendering {total} missing audio file(s)…")

        def worker():
            done = 0
            failed = 0
            for n, (beat_idx, part_idx) in enumerate(missing):
                try:
                    self._render_single_part_sync(beat_idx, part_idx)
                    done += 1
                    self.after(0, lambda b=beat_idx, q=part_idx, n_=n, t=total:
                        self.th_status_var.set(
                            f"🔄 Audio #{b + 1}.{q} ({n_ + 1}/{t})"))
                except Exception as e:
                    failed += 1
                    self.after(0, lambda b=beat_idx, q=part_idx, m=str(e):
                        self.th_status_var.set(
                            f"⚠ #{b + 1}.{q}: {m[:160]}"))
            self.after(0, lambda: self.th_status_var.set(
                f"✅ Audio batch done — {done} rendered, {failed} failed."))
            self.after(0, self._refresh_talking_heads_cards)
            self.after(0, self.main._refresh_all_tab_marks)

        threading.Thread(target=worker, daemon=True).start()

    def _run_narrative_style_analysis(self):
        if not self._require_project():
            return
        speaking = self._talking_heads_speaking_beats()
        if not speaking:
            messagebox.showinfo("🎭 Analyze",
                "No speaking beats — run Storyboard → Parse / Atmospherize first.",
                parent=self)
            return
        try:
            form = self.main._collect_form()
        except Exception:
            form = {}
        niche = form.get("niche", "")
        tone = form.get("tone", "")
        cast_names = self._cast_names_for_prompt()
        acts = sorted(set(b.get("act", 1) for _i, b in speaking))
        self.th_analyze_status_var.set(f"🔄 Analyzing {len(acts)} act(s)…")

        def worker():
            client = self.main._build_client()
            system = PROMPT_STORE.get_active_template("narrative_style_system")
            for act_num in acts:
                act_parts = []
                for beat_idx, beat in speaking:
                    if beat.get("act") != act_num:
                        continue
                    speaker = beat.get("speaker") or "(unknown)"
                    for p_zero, part in enumerate(beat.get("parts") or []):
                        part_idx = p_zero + 1
                        text = (part.get("text") or "").strip().replace("\n", " ")
                        text_trunc = text if len(text) <= 240 else text[:237] + "…"
                        act_parts.append(
                            f"{beat_idx}.{part_idx} [{speaker}]: \"{text_trunc}\"")
                if not act_parts:
                    continue
                parts_block = "\n".join(act_parts)
                prior = self._prior_summary_for_acts(acts[:acts.index(act_num)])
                user = PROMPT_STORE.render("narrative_style_user",
                    act_number=act_num,
                    niche=niche,
                    tone=tone,
                    cast_names=cast_names,
                    prior_summary=prior,
                    parts_block=parts_block)
                self.after(0, lambda a=act_num, n=len(acts):
                    self.th_analyze_status_var.set(
                        f"🔄 Analyzing act {a}/{n}…"))
                try:
                    raw = client.complete(system=system, user=user,
                        max_tokens=6000, temperature=0.6)
                except Exception as e:
                    err = str(e)
                    self.after(0, lambda a=act_num, m=err:
                        self.th_analyze_status_var.set(
                            f"❌ Act {a} failed: {m[:200]}"))
                    return
                try:
                    parsed = self._extract_styles_json(raw)
                except RuntimeError as e:
                    err = str(e)
                    self.after(0, lambda a=act_num, m=err:
                        self.th_analyze_status_var.set(
                            f"❌ Act {a} parse failed: {m[:200]}"))
                    return
                for entry in parsed:
                    try:
                        b_idx = int(entry["beat_idx"])
                        p_idx = int(entry["part_idx"])
                    except (KeyError, TypeError, ValueError):
                        continue
                    if not (0 <= b_idx < len(self._beats)):
                        continue
                    parts = self._beats[b_idx].get("parts") or []
                    if not (1 <= p_idx <= len(parts)):
                        continue
                    opts = entry.get("options") or []
                    opts = [str(o).strip() for o in opts if str(o).strip()]
                    if not opts:
                        continue
                    parts[p_idx - 1]["style_options"] = opts[:3]
                    parts[p_idx - 1].setdefault("style_selected_idx", 0)
            if self.main.current_project:
                try:
                    projects.save_storyboard(self.main.current_project, {
                        "beats": self._beats,
                        "pass_statuses": self._pass_statuses,
                    })
                except OSError:
                    pass
            self.after(0, self._refresh_talking_heads_cards)
            self.after(0, lambda: self.th_analyze_status_var.set(
                "✅ Analysis complete."))

        threading.Thread(target=worker, daemon=True).start()

    @staticmethod
    def _extract_styles_json(raw: str) -> list:
        candidates: list = []
        m = re.search(r"<styles>\s*(.*?)\s*</styles>", raw,
                       re.DOTALL | re.IGNORECASE)
        if m:
            candidates.append(m.group(1).strip())
        m = re.search(r"```(?:json)?\s*(\[.*?\])\s*```", raw, re.DOTALL)
        if m:
            candidates.append(m.group(1).strip())
        s, e = raw.find("["), raw.rfind("]")
        if s >= 0 and e > s:
            candidates.append(raw[s : e + 1])
        for c in candidates:
            try:
                data = json.loads(c)
                if isinstance(data, list):
                    return data
            except json.JSONDecodeError:
                continue
        raise RuntimeError(
            f"Could not parse narrative-style JSON. First 300 chars: {raw[:300]}…")

    def _generate_ensemble_shot(self):
        if not self._require_project():
            return
        if not self._validate_image_engine():
            return
        try:
            form = self.main._collect_form()
        except Exception:
            form = {}
        cast = self._resolve_characters_from_form(form)
        if not cast:
            messagebox.showinfo("⚠ Empty cast",
                "No cast members in step 1. Fill the form first.",
                parent=self)
            return
        proj = self.main.current_project
        refs = []
        cast_lines = []
        missing = []
        for char_id, _label, display_name in cast:
            ref = self._read_keyframe_identity_ref(proj, char_id, "seated")
            if ref is None:
                missing.append(display_name or char_id)
                continue
            refs.append(ref)
            role = cfg.role_for_char_id(char_id)
            cast_lines.append(f"  • {display_name} ({role})")
        if missing:
            messagebox.showwarning("⚠ Missing identity references",
                "Some cast members have no seated/portrait pose yet — generate "
                "them on the Characters tab before rendering the ensemble shot:\n\n"
                "  " + ", ".join(missing), parent=self)
            return
        studio_ref = self._read_keyframe_studio_ref(proj, "cam2_guests")
        if studio_ref is not None:
            refs.append(studio_ref)
        arrangement = self.th_arrangement.get("1.0", "end").strip()
        prompt = PROMPT_STORE.render("ensemble_shot_prompt",
            cast_lines="\n".join(cast_lines),
            arrangement=arrangement or "All cast members visible on the studio sofa.")
        model_slug = self.main.image_model_slug_var.get()
        self.th_status_var.set(
            f"🔄 Rendering ensemble shot with {len(cast)} characters…")

        def worker():
            try:
                from llm_clients import OpenRouterClient
                client = OpenRouterClient(
                    self.main.settings.get("openrouter_api_key", ""), model_slug)
                img_bytes, ext = client.generate_image(prompt, model=model_slug,
                    aspect_ratio="16:9", reference_image_bytes=refs)
                kf_dir = projects.keyframe_dir(self.main.current_project)
                kf_dir.mkdir(parents=True, exist_ok=True)
                versioned_re = re.compile(r"^ensemble_seated\.v\d+\.")
                for old in kf_dir.glob("ensemble_seated.*"):
                    if old.is_file() and not versioned_re.match(old.name):
                        n = 1
                        while (kf_dir /
                                f"ensemble_seated.v{n}{old.suffix}").exists():
                            n += 1
                        try:
                            old.rename(kf_dir /
                                f"ensemble_seated.v{n}{old.suffix}")
                        except OSError:
                            pass
                target = projects.ensemble_shot_path(
                    self.main.current_project, ext=ext)
                target.write_bytes(img_bytes)
                try:
                    import thumbnails as _th
                    _th.ensure_thumbnail(self.main.current_project, target)
                except Exception:
                    pass
                self.after(0,
                    lambda t=target: self._render_ensemble_thumbnail_path(t))
                self.after(0, lambda: self.th_status_var.set(
                    f"✅ Ensemble shot saved: {target.name}"))
                self.after(0, self.main._refresh_all_tab_marks)
            except Exception as e:
                err = str(e)
                self.after(0, lambda: self.th_status_var.set(
                    f"❌ Ensemble shot failed: {err[:240]}"))

        threading.Thread(target=worker, daemon=True).start()

    def _render_ensemble_thumbnail_path(self, original_path):
        try:
            cw = max(self.th_ensemble_canvas.winfo_width(), 320)
            ch = max(self.th_ensemble_canvas.winfo_height(), 180)
        except tk.TclError:
            cw, ch = 320, 180
        self._th_ensemble_photo = display_image_path_on_canvas(
            self.th_ensemble_canvas, original_path,
            self.main.current_project, cw, ch)

    def _reload_ensemble_thumbnail(self):
        if not self.main.current_project or not hasattr(self, "th_ensemble_canvas"):
            return
        path = projects.ensemble_shot_path(self.main.current_project)
        if not path.exists():
            kf_dir = projects.keyframe_dir(self.main.current_project)
            cand = [p for p in kf_dir.glob("ensemble_seated.*")
                    if p.is_file() and not re.search(r"\.v\d+\.", p.name)
                    and p.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp")]
            if not cand:
                return
            path = cand[0]
        self._render_ensemble_thumbnail_path(path)

    # Helper used by Talking heads keyframe render (kept after Generate cleanup).
    def _read_keyframe_identity_ref(self, proj, char_id: str, pose_key: str):
        """Return bytes of identity-reference image (seated → portrait →
        face_seed cascade) or None."""
        if not char_id:
            return None
        cd = projects.character_dir(proj, char_id)
        if not cd.exists():
            return None
        versioned_re = re.compile(r"\.v\d+\.[a-z0-9]+$", re.IGNORECASE)
        for candidate in (pose_key, "portrait"):
            files = [p for p in cd.glob(f"{candidate}.*")
                     if p.is_file() and not versioned_re.search(p.name)
                     and p.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp")]
            if files:
                try:
                    return files[0].read_bytes()
                except OSError:
                    pass
        face = projects.character_face_path(proj, char_id)
        if face.exists():
            try:
                return face.read_bytes()
            except OSError:
                pass
        return None

    def _read_keyframe_studio_ref(self, proj, studio_key: str):
        sd = proj / "studio"
        if not sd.exists():
            return None
        versioned_re = re.compile(r"\.v\d+\.[a-z0-9]+$", re.IGNORECASE)
        files = [p for p in sd.glob(f"{studio_key}.*")
                 if p.is_file() and not versioned_re.search(p.name)
                 and p.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp")]
        if not files:
            return None
        try:
            return files[0].read_bytes()
        except OSError:
            return None

    # ----- Media stage helpers --------------------------------------
    def _count_speaking_beats(self) -> int:
        return sum(1 for b in self._beats
                    if b.get("type") in ("line", "host_interjection"))

    def _count_reaction_beats(self) -> int:
        return sum(1 for b in self._beats
                    if b.get("type") not in ("line", "host_interjection"))

    # Speaker tags the LLM parse pass tends to emit for off-screen voiceover
    # — used to route those beats to the dedicated "narrator" voice slot.
    _NARRATOR_SPEAKER_SYNONYMS = (
        "narrator", "voiceover", "voice-over", "voice over", "vo",
        "narration", "off-screen", "off screen", "off-camera", "announcer",
        "voice", "v.o.", "v/o",
    )

    def _build_speaker_to_char_map(self) -> dict:
        """Map speaker name → char_id. Aggressive: every WORD ≥3 chars of
        each cast display name routes to its char_id, plus canonical role
        labels ('antagonist', 'expert', 'host', 'host 1', 'heroine', 'friend',
        'narrator' synonyms…). This lets us catch beats where the LLM-parsed
        speaker is just one part of the cast name (e.g. cast = 'Big food
        industry lobbyist' but beat speaker = 'LOBBYIST' or 'ANTAGONIST')."""
        try:
            form = self.main._collect_form()
        except Exception:
            return {}
        cast = self._resolve_characters_from_form(form)
        out: dict = {}
        for char_id, _, display_name in cast:
            if not display_name:
                continue
            norm = display_name.strip().lower()
            out[norm] = char_id
            # Every word (≥3 chars) of the display name → char_id
            for word in re.split(r"[^\w]+", norm):
                if len(word) >= 3:
                    out.setdefault(word, char_id)
        # Canonical role-as-speaker labels — handle scripts where the LLM
        # uses the role itself as the speaker tag ("ANTAGONIST:", "HOST 1:").
        canonical = (
            ("antagonist", "antagonist"),
            ("villain", "antagonist"),
            ("opponent", "antagonist"),
            ("expert", "expert"),
            ("doctor", "expert"),
            ("specialist", "expert"),
            ("scientist", "expert"),
            ("heroine", "heroine"),
            ("hero", "heroine"),
            ("guest", "heroine"),
            ("host", "host1"),  # ambiguous "HOST:" → default to host1
            ("host 1", "host1"),
            ("host1", "host1"),
            ("host #1", "host1"),
            ("host one", "host1"),
            ("host 2", "host2"),
            ("host2", "host2"),
            ("host #2", "host2"),
            ("host two", "host2"),
            ("friend", "friend1"),
            ("friend 1", "friend1"),
            ("friend1", "friend1"),
            ("friend #1", "friend1"),
            ("friend 2", "friend2"),
            ("friend2", "friend2"),
            ("friend #2", "friend2"),
            ("friend 3", "friend3"),
            ("friend3", "friend3"),
            ("friend #3", "friend3"),
        )
        for key, cid in canonical:
            out.setdefault(key, cid)
        # Narrator synonyms (resolved last so they win over conflicting
        # canonical entries — narrator is voice-only and explicit).
        for syn in self._NARRATOR_SPEAKER_SYNONYMS:
            out[syn] = "narrator"
        return out

    def _resolve_char_id_from_speaker(self, speaker: str,
                                        speaker_map: dict) -> str:
        if not speaker:
            return ""
        s = speaker.strip().lower()
        if s in speaker_map:
            return speaker_map[s]
        # Try exact word matches
        words = [w for w in re.split(r"[^\w]+", s) if w]
        for w in words:
            if w in speaker_map:
                return speaker_map[w]
        # Prefix fallback — useful for abbreviations like "PHARMA" matching
        # cast key "pharmaceutical" or "REGULATOR" matching "regulatory".
        for w in words:
            if len(w) < 4:
                continue
            for key, char_id in speaker_map.items():
                if len(key) < 4:
                    continue
                if w.startswith(key[:4]) or key.startswith(w[:4]):
                    return char_id
        return ""

    def _read_keyframe_identity_ref(self, proj, char_id: str,
                                      pose_key: str):
        """Return bytes of identity reference image, or None if no usable
        character image exists. Falls back: requested pose → portrait → face_seed."""
        if not char_id:
            return None
        cd = projects.character_dir(proj, char_id)
        if not cd.exists():
            return None
        versioned_re = re.compile(r"\.v\d+\.[a-z0-9]+$", re.IGNORECASE)
        for candidate in (pose_key, "portrait"):
            files = [p for p in cd.glob(f"{candidate}.*")
                     if p.is_file() and not versioned_re.search(p.name)
                     and p.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp")]
            if files:
                try:
                    return files[0].read_bytes()
                except OSError:
                    pass
        face = projects.character_face_path(proj, char_id)
        if face.exists():
            try:
                return face.read_bytes()
            except OSError:
                pass
        return None

    def _read_keyframe_studio_ref(self, proj, studio_key: str):
        sd = proj / "studio"
        if not sd.exists():
            return None
        versioned_re = re.compile(r"\.v\d+\.[a-z0-9]+$", re.IGNORECASE)
        files = [p for p in sd.glob(f"{studio_key}.*")
                 if p.is_file() and not versioned_re.search(p.name)
                 and p.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp")]
        if not files:
            return None
        try:
            return files[0].read_bytes()
        except OSError:
            return None

    # ── 🎞 Timeline sub-tab ─────────────────────────────────────────
    def _build_timeline_tab(self, parent):
        wrap = ttk.Frame(parent); wrap.pack(fill="both", expand=True)

        # ── Actions ────────────────────────────────────────────────
        af = SectionFrame(wrap, "▶ Actions")
        af.pack(fill="x", pady=(0, 10))

        btn_row = ttk.Frame(af); btn_row.pack(fill="x")
        build_btn = ttk.Button(btn_row, text="🔨 Build timeline from beats",
                                command=self._build_timeline_from_beats)
        build_btn.pack(side="left")
        Tooltip(build_btn,
            "Walk the Storyboard beats and assemble a structured clip list — absolute start times, "
            "media file paths, transitions, shot types. Overwrites the current timeline.")

        save_btn = ttk.Button(btn_row, text="💾 Save timeline",
                               command=self._save_timeline)
        save_btn.pack(side="left", padx=(6, 0))
        Tooltip(save_btn,
            "Persist the timeline JSON to <project>/timeline.json. "
            "This is the main artifact step 3 (broadcast inserts) and step 4 (editing) read.")

        export_btn = ttk.Button(btn_row, text="🎬 Export preview mp4",
                                 command=self._export_timeline_preview)
        export_btn.pack(side="left", padx=(6, 0))
        Tooltip(export_btn,
            "Render a preview mp4 by stitching generated clips with ffmpeg. "
            "Useful sanity check before steps 3 and 4. Currently stubbed — wired in step 4.")

        clear_btn = ttk.Button(btn_row, text="🗑 Clear",
                                command=self._clear_timeline)
        clear_btn.pack(side="left", padx=(6, 0))
        Tooltip(clear_btn,
            "Wipe the current timeline JSON. Media files on disk are kept — only the timeline structure is reset.")

        self.tl_status_var = tk.StringVar(value="")
        ttk.Label(af, textvariable=self.tl_status_var, foreground="grey",
                  wraplength=900).pack(anchor="w", pady=(8, 0))

        # ── Summary ────────────────────────────────────────────────
        sf = SectionFrame(wrap, "📊 Summary")
        sf.pack(fill="x", pady=(0, 10))
        self.tl_summary_var = tk.StringVar(value="(no timeline built yet)")
        ttk.Label(sf, textvariable=self.tl_summary_var,
                  font=("Consolas", 10)).pack(anchor="w")

        # ── Clip list ──────────────────────────────────────────────
        cl = SectionFrame(wrap, "🎞 Clips")
        cl.pack(fill="both", expand=True)

        cols = ("idx", "type", "char", "start", "dur", "shot", "trans", "path", "act")
        self.timeline_tree = ttk.Treeview(cl, columns=cols, show="headings",
                                           height=14, selectmode="browse")
        headings = {
            "idx": "#", "type": "Type", "char": "Character",
            "start": "Start", "dur": "Dur",
            "shot": "Shot", "trans": "Trans",
            "path": "Media path", "act": "Act",
        }
        widths = {
            "idx": 40, "type": 120, "char": 130, "start": 70, "dur": 50,
            "shot": 110, "trans": 80, "path": 300, "act": 40,
        }
        for c in cols:
            self.timeline_tree.heading(c, text=headings[c])
            self.timeline_tree.column(c, width=widths[c],
                anchor="w" if c in ("type", "char", "shot", "path") else "center")
        tree_scroll = ttk.Scrollbar(cl, orient="vertical",
                                     command=self.timeline_tree.yview)
        self.timeline_tree.configure(yscrollcommand=tree_scroll.set)
        self.timeline_tree.pack(side="left", fill="both", expand=True)
        tree_scroll.pack(side="right", fill="y")

        # Initial paint (empty)
        self._refresh_timeline_view()

    # ── TIMELINE ACTIONS ────────────────────────────────────────────
    @staticmethod
    def _fmt_seconds(seconds: float) -> str:
        m = int(seconds // 60)
        s = seconds - m * 60
        return f"{m:02d}:{s:05.2f}"

    def _speaker_to_char_id(self, speaker: str) -> str:
        """Map a speaker display name back to a char_id by matching cast names from step 1."""
        if not speaker:
            return ""
        try:
            form = self.main._collect_form()
        except Exception:
            return ""
        mapping = {
            form.get("host1_name", ""): "host1",
            form.get("host2_name", ""): "host2",
            form.get("heroine_name", ""): "heroine",
        }
        for i, f in enumerate(form.get("friend_results", []) or []):
            if f:
                mapping[f.split(",")[0].strip()] = f"friend{i+1}"
        mapping["Expert"] = "expert"
        if form.get("antagonist_type"):
            mapping[form["antagonist_type"]] = "antagonist"
        return mapping.get(speaker, "")

    def _build_timeline_from_beats(self):
        if not self._beats:
            messagebox.showinfo("⚠ No beats",
                "Run the Storyboard pipeline first (or open a project with saved beats) — "
                "there are no beats to assemble.",
                parent=self)
            return

        beat_to_clip_type = {
            "line":              "speaking",
            "host_interjection": "speaking",
            "audience":          "audience",
            "entrance":          "entrance",
            "pause":             "pause",
        }

        clips = []
        cursor = 0.0
        for i, beat in enumerate(self._beats):
            clip_type = beat_to_clip_type.get(beat.get("type"), "speaking")
            idx = i + 1
            clip_id = f"c{idx:03d}"
            speaker = beat.get("speaker", "")
            char_id = self._speaker_to_char_id(speaker)
            duration = float(beat.get("duration") or 0.0)

            video_path = ""
            audio_path = ""
            keyframe_path = ""
            if clip_type == "speaking":
                video_path = f"video/{clip_id}.mp4"
                audio_path = f"audio/line_{clip_id}.mp3"
                keyframe_path = f"video/frame_{clip_id}.png"
            elif clip_type == "audience":
                text_l = (beat.get("text") or "").lower()
                if "applau" in text_l or "cheer" in text_l:
                    pose = "applauding"
                elif "boo" in text_l:
                    pose = "disapproving"
                elif "laugh" in text_l:
                    pose = "laughing"
                else:
                    pose = "attentive"
                video_path = f"audience/{pose}.png"
                audio_path = f"audio/crowd_{pose}_{clip_id}.mp3"
            elif clip_type == "entrance":
                cid = char_id or "unknown"
                video_path = f"video/entrance_{cid}.mp4"
                audio_path = f"audio/crowd_applauding_{clip_id}.mp3"
                keyframe_path = f"characters/{cid}/entrance.png"
            # 'pause' has no media

            clips.append({
                "id": clip_id,
                "type": clip_type,
                "character_id": char_id,
                "speaker": speaker,
                "act": int(beat.get("act") or 1),
                "start": round(cursor, 2),
                "duration": round(duration, 2),
                "video_path": video_path,
                "audio_path": audio_path,
                "keyframe_path": keyframe_path,
                "transition_in": beat.get("transition", "") or "hard cut",
                "shot": beat.get("shot", ""),
                "text": beat.get("text", ""),
                "beat_idx": i,
            })
            cursor += duration

        self._timeline = {
            "version": 1,
            "total_duration": round(cursor, 2),
            "clips": clips,
        }
        self._refresh_timeline_view()
        self.tl_status_var.set(
            f"✅ Timeline built: {len(clips)} clips, runtime {self._fmt_seconds(cursor)}.")
        self._schedule_silent_save("timeline")

    def _refresh_timeline_view(self):
        for iid in self.timeline_tree.get_children():
            self.timeline_tree.delete(iid)

        clips = (self._timeline or {}).get("clips", [])
        if not clips:
            self.tl_summary_var.set("(no timeline built yet)")
            return

        speaking = sum(1 for c in clips if c["type"] == "speaking")
        audience = sum(1 for c in clips if c["type"] == "audience")
        entrance = sum(1 for c in clips if c["type"] == "entrance")
        pause = sum(1 for c in clips if c["type"] == "pause")
        total_dur = self._timeline.get("total_duration", 0.0)

        self.tl_summary_var.set(
            f"Total clips: {len(clips):<4}  Runtime: {self._fmt_seconds(total_dur)}    "
            f"💬 Speaking: {speaking}   👥 Audience: {audience}   "
            f"🚪 Entrance: {entrance}   ⏸ Pause: {pause}"
        )

        type_emoji = {
            "speaking": "💬", "audience": "👥",
            "entrance": "🚪", "pause": "⏸",
        }
        for i, c in enumerate(clips):
            emoji = type_emoji.get(c["type"], "•")
            media = c.get("video_path") or c.get("audio_path") or "—"
            if len(media) > 60:
                media = media[:57] + "…"
            self.timeline_tree.insert("", "end", iid=str(i), values=(
                i + 1,
                f"{emoji} {c['type']}",
                c.get("speaker") or "—",
                self._fmt_seconds(c.get("start", 0)),
                f"{c.get('duration', 0):.1f}",
                c.get("shot", "") or "—",
                c.get("transition_in", "") or "—",
                media,
                c.get("act", ""),
            ))

    def _save_timeline(self):
        if not self._require_project():
            return
        if not self._timeline:
            messagebox.showinfo("⚠ No timeline",
                "Build the timeline first — click 🔨 Build timeline from beats.",
                parent=self)
            return
        path = projects.save_timeline(self.main.current_project, self._timeline)
        self.tl_status_var.set(f"✅ Timeline saved: {path}")

    def _export_timeline_preview(self):
        if not self._timeline:
            messagebox.showinfo("⚠ No timeline",
                "Build the timeline first — click 🔨 Build timeline from beats.",
                parent=self)
            return
        messagebox.showinfo(
            "🚧 Preview export",
            "Preview mp4 export via ffmpeg is wired in step 4 (Editing). "
            "For now the structured timeline.json is the primary artifact that "
            "step 3 (broadcast inserts) and step 4 (editing) consume.",
            parent=self,
        )
        self.tl_status_var.set("🚧 Preview mp4 export deferred to step 4.")

    def _clear_timeline(self):
        if self._timeline and not messagebox.askyesno(
            "🗑 Clear timeline",
            "Discard the current timeline JSON? Media files on disk are kept.",
            parent=self,
        ):
            return
        self._timeline = None
        self._refresh_timeline_view()
        self.tl_status_var.set("🗑 Timeline cleared.")

    def apply_timeline(self, project_path):
        """Load timeline.json into state. Called by MainWindow on project open."""
        self._timeline = None
        if not project_path:
            return
        data = projects.load_timeline(project_path)
        if data:
            self._timeline = data
        if hasattr(self, "timeline_tree"):
            self._refresh_timeline_view()


# ─────────────────────────────────────────────────────────────────────
# Camera-plan settings dialog (opened from the Storyboard tab's ⚙ button)
# ─────────────────────────────────────────────────────────────────────
class CameraPlanDialog(tk.Toplevel):
    """Popup for the director-level camera preferences (preset, reaction %,
    audience %, avg shot duration, default transition, wide-shot frequency,
    custom rules). The data lives in StringVars/IntVars on the StudioShootTab
    so the popup can be opened/closed without losing edits. On Save, the
    values are persisted to <project>/camera_plan.json via _save_camera_plan."""

    def __init__(self, parent, studio_tab):
        super().__init__(parent)
        self.title("🎥 Camera plan — Storyboard director preferences")
        self.transient(parent.winfo_toplevel())
        self.grab_set()
        self.studio_tab = studio_tab
        self.resizable(False, False)

        body = ttk.Frame(self, padding=14); body.pack(fill="both", expand=True)

        pf = SectionFrame(body, "🎬 Director preset")
        pf.pack(fill="x", pady=(0, 8))
        preset_combo = ttk.Combobox(pf, values=list(cfg.CAMERA_PRESETS),
            textvariable=studio_tab._cam_preset_var, state="readonly", width=42)
        preset_combo.pack(fill="x")
        Tooltip(preset_combo,
            "High-level directing style. 'Classic talk show' is balanced; "
            "'fast cuts' is high-energy daytime; 'static two-shot' is minimal "
            "cut; 'documentary' uses long takes; 'daytime drama' is "
            "reaction-heavy.")

        sf = SectionFrame(body, "🎚 Pacing & coverage")
        sf.pack(fill="x", pady=(0, 8))
        self._slider_row(sf, "Reaction shot %",
            studio_tab._cam_reaction_pct_var, from_=0, to=100, step=5,
            suffix="%",
            tip="Percentage of beats where the camera shows a non-speaking "
                "character reacting instead of the speaker.")
        self._slider_row(sf, "Audience cutaway %",
            studio_tab._cam_audience_pct_var, from_=0, to=100, step=5,
            suffix="%",
            tip="Percentage of beats where the camera cuts to the audience "
                "instead of the stage.")
        self._slider_row(sf, "Avg shot duration",
            studio_tab._cam_avg_duration_var, from_=2.0, to=10.0, step=0.5,
            suffix="s", is_float=True,
            tip="Target average length of a single shot. Lower = more cuts.")

        tf = SectionFrame(body, "✂ Transitions & framing")
        tf.pack(fill="x", pady=(0, 8))
        tgrid = ttk.Frame(tf); tgrid.pack(fill="x")
        for c in range(2):
            tgrid.columnconfigure(c, weight=1)
        ttk.Label(tgrid, text="Default transition:").grid(
            row=0, column=0, sticky="w", padx=(0, 4))
        trans_combo = ttk.Combobox(tgrid,
            values=list(cfg.CAMERA_DEFAULT_TRANSITIONS),
            textvariable=studio_tab._cam_transition_var,
            state="readonly")
        trans_combo.grid(row=1, column=0, sticky="ew", padx=(0, 6))
        ttk.Label(tgrid, text="Wide-shot frequency:").grid(
            row=0, column=1, sticky="w", padx=(4, 0))
        wide_combo = ttk.Combobox(tgrid,
            values=list(cfg.WIDE_SHOT_FREQUENCIES),
            textvariable=studio_tab._cam_wide_freq_var,
            state="readonly")
        wide_combo.grid(row=1, column=1, sticky="ew")

        cf = SectionFrame(body, "📝 Custom rules (optional)")
        cf.pack(fill="x", pady=(0, 8))
        self._custom_text = tk.Text(cf, height=4, width=70, wrap="word")
        self._custom_text.pack(fill="x")
        self._custom_text.insert("1.0", studio_tab._cam_custom_rules or "")
        ttk.Label(cf,
            text="Free-form directives fed to the Camera pass on top of the "
                 "structured rules above. One rule per line works best.",
            foreground="grey", font=("", 9, "italic"),
            wraplength=540).pack(anchor="w", pady=(2, 0))

        btn_row = ttk.Frame(body); btn_row.pack(fill="x", pady=(6, 0))
        save_btn = ttk.Button(btn_row, text="💾 Save and close",
                               command=self._on_save)
        save_btn.pack(side="right")
        reset_btn = ttk.Button(btn_row, text="↩ Reset to defaults",
                                command=self._on_reset)
        reset_btn.pack(side="left")
        cancel_btn = ttk.Button(btn_row, text="✖ Cancel",
                                 command=self.destroy)
        cancel_btn.pack(side="right", padx=(0, 6))

        self.bind("<Escape>", lambda _e: self.destroy())
        self.update_idletasks()
        try:
            px = parent.winfo_toplevel().winfo_rootx()
            py = parent.winfo_toplevel().winfo_rooty()
            self.geometry(f"+{px + 80}+{py + 60}")
        except tk.TclError:
            pass

    def _slider_row(self, parent, label, var, *, from_, to, step,
                     suffix="", is_float=False, tip=""):
        row = ttk.Frame(parent); row.pack(fill="x", pady=(2, 2))
        ttk.Label(row, text=label, width=18).pack(side="left")
        scale = ttk.Scale(row, from_=from_, to=to, variable=var,
                           orient="horizontal")
        scale.pack(side="left", fill="x", expand=True, padx=(4, 6))
        val_var = tk.StringVar()
        def _update_label(*_):
            try:
                v = var.get()
            except tk.TclError:
                v = 0
            if is_float:
                val_var.set(f"{float(v):.1f}{suffix}")
            else:
                val_var.set(f"{int(v)}{suffix}")
        var.trace_add("write", _update_label); _update_label()
        ttk.Label(row, textvariable=val_var, width=8,
                  foreground="#444").pack(side="left")
        if tip:
            Tooltip(scale, tip)

    def _on_reset(self):
        self.studio_tab.apply_camera_plan(cfg.DEFAULT_CAMERA_PLAN)
        try:
            self._custom_text.delete("1.0", "end")
            self._custom_text.insert("1.0",
                cfg.DEFAULT_CAMERA_PLAN["custom_rules"] or "")
        except tk.TclError:
            pass

    def _on_save(self):
        try:
            self.studio_tab._cam_custom_rules = self._custom_text.get(
                "1.0", "end").strip()
        except tk.TclError:
            pass
        path = self.studio_tab._save_camera_plan()
        if path is not None:
            try:
                self.studio_tab.story_status_var.set(
                    f"✅ Camera plan saved: {path.name}")
            except (tk.TclError, AttributeError):
                pass
        self.destroy()


# ─────────────────────────────────────────────────────────────────────
# Add-custom-voice dialog (opened from the Voices tab's ➕ Add button)
# ─────────────────────────────────────────────────────────────────────
class AddCustomVoiceDialog(tk.Toplevel):
    """Popup for attaching a custom ElevenLabs voice_id to the user's voice
    list. Gender defaults to the currently-picked character's gender and is
    overridable via the radio buttons.

    On Add, the dialog calls studio_tab._add_custom_voice_with_args() and
    closes on success. Esc cancels; Enter triggers Add."""

    def __init__(self, parent, studio_tab):
        super().__init__(parent)
        self.title("➕ Add custom voice")
        self.transient(parent.winfo_toplevel())
        self.grab_set()
        self.studio_tab = studio_tab
        self.resizable(False, False)

        # Initial gender from the current character
        cur_g = (studio_tab._current_voice_character_gender() or "any").lower()
        if cur_g not in ("male", "female"):
            cur_g = "any"

        body = ttk.Frame(self, padding=14); body.pack(fill="both", expand=True)

        ttk.Label(body, text="Name (shown in dropdown):").grid(
            row=0, column=0, sticky="w", pady=(0, 2))
        self.name_var = tk.StringVar()
        nm_entry = ttk.Entry(body, textvariable=self.name_var, width=44)
        nm_entry.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(0, 8))

        ttk.Label(body, text="voice_id (from ElevenLabs Voice Library):").grid(
            row=2, column=0, sticky="w", pady=(0, 2))
        self.voice_id_var = tk.StringVar()
        vid_entry = ttk.Entry(body, textvariable=self.voice_id_var, width=44)
        vid_entry.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(0, 8))

        ttk.Label(body, text="Gender:").grid(row=4, column=0, sticky="w",
                                              pady=(0, 2))
        self.gender_var = tk.StringVar(value=cur_g)
        g_row = ttk.Frame(body); g_row.grid(row=5, column=0, columnspan=2,
                                              sticky="w", pady=(0, 8))
        for g, label in (("male", "Male"), ("female", "Female"),
                          ("any", "Any (unisex)")):
            ttk.Radiobutton(g_row, text=label, variable=self.gender_var,
                             value=g).pack(side="left", padx=(0, 12))

        ttk.Label(body,
            text="ℹ Gender controls which character dropdowns the voice "
                 "appears in (filter on the Characters tab's Gender setting).",
            foreground="grey", wraplength=400, font=("", 9)
        ).grid(row=6, column=0, columnspan=2, sticky="w", pady=(0, 12))

        btn_row = ttk.Frame(body); btn_row.grid(row=7, column=0, columnspan=2,
                                                  sticky="ew")
        lib_btn = ttk.Button(btn_row, text="🔗 Voice Library",
                              command=self._open_library)
        lib_btn.pack(side="left")
        Tooltip(lib_btn,
            "Open the ElevenLabs voice library in your default browser. "
            "Find a voice, copy its voice_id, and paste it above.")
        cancel_btn = ttk.Button(btn_row, text="✖ Cancel",
                                 command=self.destroy)
        cancel_btn.pack(side="right")
        add_btn = ttk.Button(btn_row, text="➕ Add and close",
                              command=self._on_add)
        add_btn.pack(side="right", padx=(0, 6))

        # Keys
        self.bind("<Return>", lambda _e: self._on_add())
        self.bind("<KP_Enter>", lambda _e: self._on_add())
        self.bind("<Escape>", lambda _e: self.destroy())

        body.columnconfigure(0, weight=1)

        # Centre over the parent window
        self.update_idletasks()
        try:
            px = parent.winfo_toplevel().winfo_rootx()
            py = parent.winfo_toplevel().winfo_rooty()
            self.geometry(f"+{px + 80}+{py + 80}")
        except tk.TclError:
            pass
        nm_entry.focus_set()

    def _open_library(self):
        import webbrowser
        webbrowser.open(cfg.ELEVENLABS_VOICE_LIBRARY_URL)

    def _on_add(self):
        ok, msg = self.studio_tab._add_custom_voice_with_args(
            self.name_var.get(), self.voice_id_var.get(),
            self.gender_var.get())
        if ok:
            try:
                self.studio_tab.voice_status_var.set(
                    f"➕ {msg}. Click 🔉 Demo to generate a demo clip "
                    f"(one-time API call).")
            except tk.TclError:
                pass
            self.destroy()
        else:
            messagebox.showinfo("➕ Add voice", msg, parent=self)


# ─────────────────────────────────────────────────────────────────────
# Generic stub used by the placeholder sub-tabs
# ─────────────────────────────────────────────────────────────────────
def _build_stub(parent, title: str, desc: str):
    wrap = ttk.Frame(parent, padding=40); wrap.pack(expand=True)
    ttk.Label(wrap, text=title, font=("", 18, "bold")).pack(pady=(20, 8))
    ttk.Label(wrap, text=desc, foreground="#333",
              wraplength=600, justify="center",
              font=("", 11)).pack(pady=(0, 16))
    ttk.Label(wrap, text="🚧  Coming next iteration  🚧",
              foreground="#a0660b", font=("", 11, "bold")).pack()
