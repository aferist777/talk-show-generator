"""
Reusable Tkinter widgets used across the application.
"""
import re
import tkinter as tk
from tkinter import ttk, colorchooser


class Tooltip:
    """Hover tooltip attached to any widget. Appears after `delay` ms."""

    def __init__(self, widget, text, delay=350, wraplength=360):
        self.widget = widget
        self.text = text
        self.delay = delay
        self.wraplength = wraplength
        self._tip = None
        self._scheduled = None
        widget.bind("<Enter>", self._schedule, add="+")
        widget.bind("<Leave>", self._hide, add="+")
        widget.bind("<ButtonPress>", self._hide, add="+")

    def _schedule(self, _event=None):
        self._unschedule()
        self._scheduled = self.widget.after(self.delay, self._show)

    def _unschedule(self):
        if self._scheduled:
            try:
                self.widget.after_cancel(self._scheduled)
            except tk.TclError:
                pass
            self._scheduled = None

    def _show(self):
        if self._tip or not self.text:
            return
        try:
            widget_x = self.widget.winfo_rootx()
            widget_y = self.widget.winfo_rooty()
            widget_w = self.widget.winfo_width()
            widget_h = self.widget.winfo_height()
            screen_w = self.widget.winfo_screenwidth()
            screen_h = self.widget.winfo_screenheight()
        except tk.TclError:
            return

        self._tip = tk.Toplevel(self.widget)
        self._tip.wm_overrideredirect(True)
        # Create off-screen so the user doesn't see the pre-measure flash.
        self._tip.wm_geometry("+-2000+-2000")
        tk.Label(self._tip, text=self.text, justify="left",
                 background="#ffffe0", foreground="#222",
                 relief="solid", borderwidth=1,
                 font=("", 9), wraplength=self.wraplength,
                 padx=8, pady=5).pack()

        # Now measure the real size, then orient the tooltip toward the
        # screen centre so it doesn't run off the edge.
        try:
            self._tip.update_idletasks()
            tip_w = self._tip.winfo_reqwidth()
            tip_h = self._tip.winfo_reqheight()
        except tk.TclError:
            tip_w, tip_h = 200, 0

        widget_center_x = widget_x + widget_w / 2
        if widget_center_x < screen_w / 2:
            # Widget is in the left half — tooltip extends to the right.
            x = widget_x + 18
        else:
            # Widget is in the right half — tooltip extends to the left so
            # it points back toward the centre of the interface.
            x = widget_x + widget_w - tip_w - 18
        # Clamp horizontally to keep the whole tooltip on-screen.
        x = max(8, min(int(x), screen_w - tip_w - 8))

        y_above = widget_y - tip_h - 4
        if y_above >= 0:
            y = y_above                            # preferred: above
        else:
            y = widget_y + widget_h + 4            # fallback: below
        # Clamp vertically too — in case the widget is near the bottom edge.
        y = max(8, min(int(y), screen_h - tip_h - 8))

        try:
            self._tip.wm_geometry(f"+{x}+{y}")
        except tk.TclError:
            pass

    def _hide(self, _event=None):
        self._unschedule()
        if self._tip:
            try:
                self._tip.destroy()
            except tk.TclError:
                pass
            self._tip = None


class HelpIcon(ttk.Label):
    """A subtle ❓ glyph that shows a tooltip on hover."""

    def __init__(self, parent, text, **kwargs):
        super().__init__(parent, text=" ❓", cursor="question_arrow",
                         foreground="#5e8ad6", **kwargs)
        Tooltip(self, text)


def bind_autosave(widget, callback):
    """Attach `callback()` to fire whenever `widget`'s value changes by user
    interaction. Supports LabeledEntry / LabeledCombobox / LabeledText /
    LabeledSlider / ColorSwatch and plain ttk Entries / Comboboxes.

    Trace-based widgets (those backed by tk.StringVar/DoubleVar) ALSO fire when
    set programmatically. Use `main_window._autosave_paused` to suppress this
    during project load.
    """
    if isinstance(widget, (LabeledEntry, LabeledCombobox, LabeledSlider, ColorSwatch)):
        widget.var.trace_add("write", lambda *_: callback())
    elif isinstance(widget, LabeledText):
        # KeyRelease fires only on real user typing — programmatic .set()
        # does NOT trigger it, which is exactly what we want.
        widget.text.bind("<KeyRelease>", lambda _e: callback(), add="+")
    elif isinstance(widget, ttk.Combobox):
        widget.bind("<<ComboboxSelected>>", lambda _e: callback(), add="+")
    elif isinstance(widget, (ttk.Entry, tk.Entry)):
        widget.bind("<KeyRelease>", lambda _e: callback(), add="+")
    elif isinstance(widget, (tk.IntVar, tk.StringVar, tk.DoubleVar, tk.BooleanVar)):
        widget.trace_add("write", lambda *_: callback())


class GearButton(ttk.Button):
    """⚙ button that opens the PromptEditor for a named system prompt."""

    def __init__(self, parent, prompt_name: str, main_window=None, **kwargs):
        super().__init__(parent, text="⚙", width=3,
                         command=lambda: self._open(prompt_name, main_window),
                         **kwargs)
        Tooltip(self,
            f"Tune the system prompt used by this action ('{prompt_name}'). "
            f"Edit, version, and merge user additions via the LLM.")
        self._main_window = main_window

    @staticmethod
    def _open(prompt_name: str, main_window):
        # Lazy import to avoid circular dependency (prompt_editor imports widgets)
        from ui.prompt_editor import PromptEditor
        PromptEditor(main_window, prompt_name, main_window=main_window)


class ModelPicker(ttk.Frame):
    """Per-tab Engine picker: provider dropdown + model dropdown.

    Bound to SHARED StringVars in main_window:
        text:  main_window.text_provider_var, .text_model_slug_var
        image: main_window.image_provider_var, .image_model_slug_var

    All instances of the same kind sync automatically — picking a provider
    or model in one tab updates every other tab and persists to settings.
    """

    def __init__(self, parent, *, kind: str, main_window,
                 prompt_name: str | None = None,
                 label_text: str = "Engine:",
                 exclude_slugs: list | None = None,
                 **kwargs):
        super().__init__(parent, **kwargs)
        import config as _cfg
        self._cfg = _cfg
        self.kind = kind
        self.main_window = main_window
        self._prompt_name = prompt_name
        self._exclude_slugs = set(exclude_slugs or [])
        self._suspend_traces = False  # guard against re-entrancy

        if kind == "text":
            self._providers = _cfg.TEXT_PROVIDERS
            self._provider_labels = _cfg.TEXT_PROVIDER_LABELS
            self._provider_var = main_window.text_provider_var
            self._slug_var = main_window.text_model_slug_var
        elif kind == "image":
            self._providers = _cfg.IMAGE_PROVIDERS
            self._provider_labels = _cfg.IMAGE_PROVIDER_LABELS
            self._provider_var = main_window.image_provider_var
            self._slug_var = main_window.image_model_slug_var
        else:
            raise ValueError(f"ModelPicker kind must be 'text' or 'image', got {kind!r}")

        # ── UI ─────────────────────────────────────────────────────
        ttk.Label(self, text=label_text).pack(side="left")
        HelpIcon(self,
            f"Engine for {kind} generation: pick a provider on the left, then a "
            f"model from that provider's catalog on the right. Changing here "
            f"updates every other tab where this engine is used and persists to settings."
        ).pack(side="left")

        # Provider combo
        provider_label_values = [self._provider_labels.get(p, p) for p in self._providers]
        self._provider_label_to_id = dict(zip(provider_label_values, self._providers))
        self._provider_label_var = tk.StringVar(
            value=self._provider_labels.get(self._provider_var.get(), self._providers[0]))
        max_pw = max(len(l) for l in provider_label_values) + 2
        self.provider_combo = ttk.Combobox(self,
            textvariable=self._provider_label_var,
            values=provider_label_values, state="readonly",
            width=max_pw)
        self.provider_combo.pack(side="left", padx=(6, 4))
        self.provider_combo.bind("<<ComboboxSelected>>",
            lambda _e: self._on_provider_change())

        # Model combo (values filled by _refresh_model_values)
        self._label_to_slug: dict = {}
        self._slug_to_label: dict = {}
        self._model_label_var = tk.StringVar()
        self.model_combo = ttk.Combobox(self,
            textvariable=self._model_label_var,
            values=[], state="readonly")
        self.model_combo.pack(side="left", padx=(0, 4))
        self.model_combo.bind("<<ComboboxSelected>>",
            lambda _e: self._on_model_change())

        # Docs button (only when a real docs file exists per slug — works for openrouter)
        docs_btn = ttk.Button(self, text="📄", width=3, command=self._open_docs)
        docs_btn.pack(side="left")
        Tooltip(docs_btn,
            f"Open the locally cached docs for the selected model (model_docs/{kind}/<slug>.md).")

        if self._prompt_name:
            GearButton(self, self._prompt_name, main_window=main_window
                       ).pack(side="left", padx=(2, 0))

        # Cross-instance sync — react when shared vars change
        self._provider_trace = self._provider_var.trace_add("write",
            lambda *_: self._on_shared_provider_var_changed())
        self._slug_trace = self._slug_var.trace_add("write",
            lambda *_: self._on_shared_slug_var_changed())

        # Initial populate
        self._refresh_model_values()

    # ── catalog ────────────────────────────────────────────────────
    def _catalog_for(self, provider: str) -> list:
        # For ollama, fetch live local models.
        if self.kind == "text" and provider == "ollama":
            try:
                from llm_clients import OllamaClient
                host = self.main_window.settings.get("ollama_host", "http://localhost:11434")
                installed = OllamaClient(host, "").list_models() or []
                return [{"slug": s, "label": s, "price_label": "local"} for s in installed]
            except Exception:
                return []
        if self.kind == "text":
            full = self._cfg.get_text_catalog(provider)
        else:
            full = self._cfg.get_image_catalog(provider)
        if self._exclude_slugs:
            return [m for m in full if m["slug"] not in self._exclude_slugs]
        return full

    def _make_model_label(self, entry: dict) -> str:
        if self.kind == "text":
            return f"{entry['label']}  —  {entry.get('price_label', '')}"
        # image: include capability tag
        cap = entry.get("capability", "")
        suffix = f" ({cap})" if cap else ""
        return f"{entry['label']}{suffix}  —  {entry.get('price_label', '')}"

    def _refresh_model_values(self):
        """Populate the model combobox for the current provider and select the
        slug that corresponds to it (either from shared slug var, or from the
        per-provider setting key)."""
        provider = self._provider_var.get()
        catalog = self._catalog_for(provider)
        self._label_to_slug.clear()
        self._slug_to_label.clear()
        labels = []
        for m in catalog:
            lbl = self._make_model_label(m)
            labels.append(lbl)
            self._label_to_slug[lbl] = m["slug"]
            self._slug_to_label[m["slug"]] = lbl

        # Sentinel when provider has no catalog (kie.ai coming soon, ollama empty)
        if not labels:
            placeholder = "(no models available)"
            labels = [placeholder]
            self._label_to_slug[placeholder] = ""

        max_mw = max(len(l) for l in labels) + 2
        self.model_combo.configure(values=labels, width=max_mw)

        # Resolve which slug should be active for this provider.
        # 1. If shared slug_var holds something in this catalog → use it.
        # 2. Else read from settings[f"{kind}_model_{provider}"].
        # 3. Else fall back to first.
        target_slug = self._slug_var.get()
        if target_slug not in self._slug_to_label:
            key = self._settings_key_for(provider)
            target_slug = self.main_window.settings.get(key, "")
        if target_slug not in self._slug_to_label:
            target_slug = next(iter(self._slug_to_label.values()), "")
        self._suspend_traces = True
        try:
            self._slug_var.set(target_slug)
            self._model_label_var.set(self._slug_to_label.get(target_slug, labels[0]))
        finally:
            self._suspend_traces = False

    def _settings_key_for(self, provider: str) -> str:
        provider_slug = provider.replace(".", "").replace("-", "")  # 'kie.ai' → 'kieai'
        # We chose these explicit keys in DEFAULT_CONFIG
        return f"{self.kind}_model_{provider_slug if provider == 'kie.ai' else provider.replace('.ai', '')}"

    # ── event handlers ─────────────────────────────────────────────
    def _on_provider_change(self):
        # User picked a new provider in this picker's combo
        new_provider = self._provider_label_to_id.get(self._provider_label_var.get())
        if not new_provider or new_provider == self._provider_var.get():
            return
        self._provider_var.set(new_provider)  # triggers cross-instance refresh

    def _on_model_change(self):
        slug = self._label_to_slug.get(self._model_label_var.get())
        if slug and slug != self._slug_var.get():
            self._slug_var.set(slug)  # main_window trace persists + cross-sync

    def _on_shared_provider_var_changed(self):
        if self._suspend_traces:
            return
        try:
            label = self._provider_labels.get(self._provider_var.get(),
                                                self._provider_var.get())
            if label != self._provider_label_var.get():
                self._provider_label_var.set(label)
            self._refresh_model_values()
        except tk.TclError:
            pass

    def _on_shared_slug_var_changed(self):
        if self._suspend_traces:
            return
        try:
            new_label = self._slug_to_label.get(self._slug_var.get())
            if new_label and new_label != self._model_label_var.get():
                self._model_label_var.set(new_label)
        except tk.TclError:
            pass

    # ── docs popup ─────────────────────────────────────────────────
    def _open_docs(self):
        import config as _cfg
        slug = self._slug_var.get()
        if not slug:
            from tkinter import messagebox
            messagebox.showinfo("📄 Docs",
                "No model is selected (this provider may not have models available yet).",
                parent=self.winfo_toplevel())
            return
        path = _cfg.model_doc_path(slug, kind=self.kind)
        if not path.exists():
            from tkinter import messagebox
            messagebox.showinfo("📄 Docs not found",
                f"Local docs file is missing:\n{path}",
                parent=self.winfo_toplevel())
            return
        try:
            content = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as e:
            from tkinter import messagebox
            messagebox.showerror("❌ Read failed", str(e),
                                  parent=self.winfo_toplevel())
            return
        top = tk.Toplevel(self.winfo_toplevel())
        top.title(f"📄 {slug}")
        top.geometry("820x640")
        top.transient(self.winfo_toplevel())
        wrap = ttk.Frame(top, padding=10); wrap.pack(fill="both", expand=True)
        box = ttk.Frame(wrap); box.pack(fill="both", expand=True)
        txt = tk.Text(box, wrap="word", font=("Consolas", 9), padx=8, pady=6)
        txt.pack(side="left", fill="both", expand=True)
        sb = ttk.Scrollbar(box, orient="vertical", command=txt.yview)
        txt.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        txt.insert("1.0", content)
        txt.config(state="disabled")
        ttk.Button(wrap, text="✖ Close", command=top.destroy).pack(pady=(8, 0))


def _label_with_help(parent, label_text, help_text):
    """Row: label + optional inline help icon."""
    row = ttk.Frame(parent)
    ttk.Label(row, text=label_text).pack(side="left")
    if help_text:
        HelpIcon(row, help_text).pack(side="left")
    return row


class LabeledEntry(ttk.Frame):
    """A label + entry pair, vertically stacked. Optional inline help icon."""

    def __init__(self, parent, label, default="", width=30, help_text="", **kwargs):
        super().__init__(parent, **kwargs)
        _label_with_help(self, label, help_text).pack(anchor="w", fill="x")
        self.var = tk.StringVar(value=default)
        self.entry = ttk.Entry(self, textvariable=self.var, width=width)
        self.entry.pack(fill="x")

    def get(self):
        return self.var.get()

    def set(self, value):
        self.var.set(str(value))


class LabeledCombobox(ttk.Frame):
    """A label + combobox pair. Optional inline help icon."""

    def __init__(self, parent, label, values, default=None, width=30,
                 readonly=True, help_text="", **kwargs):
        super().__init__(parent, **kwargs)
        _label_with_help(self, label, help_text).pack(anchor="w", fill="x")
        self.var = tk.StringVar(value=default if default is not None else (values[0] if values else ""))
        state = "readonly" if readonly else "normal"
        self.combo = ttk.Combobox(self, textvariable=self.var, values=values, state=state, width=width)
        self.combo.pack(fill="x")

    def get(self):
        return self.var.get()

    def set(self, value):
        self.var.set(str(value))

    def set_values(self, values):
        self.combo["values"] = values


class LabeledText(ttk.Frame):
    """A label + multi-line Text widget. Optional inline help icon."""

    def __init__(self, parent, label, height=5, width=40, placeholder="",
                 help_text="", **kwargs):
        super().__init__(parent, **kwargs)
        _label_with_help(self, label, help_text).pack(anchor="w", fill="x")
        self.text = tk.Text(self, height=height, width=width, wrap="word")
        self.text.pack(fill="both", expand=True)
        self._placeholder = placeholder
        self._placeholder_active = False
        if placeholder:
            self._set_placeholder()
            self.text.bind("<FocusIn>", self._on_focus_in)
            self.text.bind("<FocusOut>", self._on_focus_out)

    def _set_placeholder(self):
        self.text.insert("1.0", self._placeholder)
        self.text.config(fg="grey")
        self._placeholder_active = True

    def _on_focus_in(self, event):
        if self._placeholder_active:
            self.text.delete("1.0", "end")
            self.text.config(fg="black")
            self._placeholder_active = False

    def _on_focus_out(self, event):
        if not self.text.get("1.0", "end").strip():
            self._set_placeholder()

    def get(self):
        if self._placeholder_active:
            return ""
        return self.text.get("1.0", "end").strip()

    def set(self, value):
        self.text.delete("1.0", "end")
        if value:
            self.text.insert("1.0", value)
            self.text.config(fg="black")
            self._placeholder_active = False
        elif self._placeholder:
            self._set_placeholder()


class SectionFrame(ttk.LabelFrame):
    """A titled section block with consistent padding."""

    def __init__(self, parent, title, **kwargs):
        super().__init__(parent, text=f" {title} ", padding=10, **kwargs)


class LabeledSlider(ttk.Frame):
    """Label + horizontal slider + numeric readout on the right. Optional help icon."""

    def __init__(self, parent, label, from_=0.0, to=1.0, default=0.5,
                 resolution=0.05, help_text="", fmt="{:.2f}", **kwargs):
        super().__init__(parent, **kwargs)
        head = ttk.Frame(self); head.pack(fill="x")
        ttk.Label(head, text=label).pack(side="left")
        if help_text:
            HelpIcon(head, help_text).pack(side="left")
        self.var = tk.DoubleVar(value=default)
        self._fmt = fmt
        self.value_label = ttk.Label(head, text=fmt.format(default), foreground="#555")
        self.value_label.pack(side="right")
        self._resolution = resolution
        self.scale = ttk.Scale(self, from_=from_, to=to, variable=self.var,
                                command=self._on_change, orient="horizontal")
        self.scale.pack(fill="x")

    def _on_change(self, *_):
        val = self.var.get()
        if self._resolution:
            val = round(val / self._resolution) * self._resolution
            self.var.set(val)
        self.value_label.config(text=self._fmt.format(val))

    def get(self) -> float:
        return float(self.var.get())

    def set(self, value):
        try:
            self.var.set(float(value))
        except (ValueError, TypeError):
            return
        self._on_change()


def _svg_bytes_to_png(svg_bytes: bytes, target_width: int = 1024) -> bytes:
    """Rasterise SVG bytes → PNG bytes via svglib + reportlab (pure-Python,
    no native deps). Returns PNG bytes or raises."""
    from io import BytesIO
    from svglib.svglib import svg2rlg
    from reportlab.graphics import renderPM
    drawing = svg2rlg(BytesIO(svg_bytes))
    if drawing is None:
        raise RuntimeError("svglib failed to parse SVG")
    # Scale drawing to target_width to keep raster quality reasonable
    if drawing.width and drawing.width > 0:
        scale = target_width / drawing.width
        drawing.width *= scale
        drawing.height *= scale
        drawing.scale(scale, scale)
    return renderPM.drawToString(drawing, fmt="PNG")


def show_image_popup(parent, image_source, title: str = "🖼 Preview"):
    """Open a modal popup showing the image at full size (scaled to fit screen).

    `image_source` may be a `pathlib.Path`, a string path, or raw bytes.
    Close with Esc or by clicking the image. SVG sources are rasterised via
    the same pipeline as the inline previews.
    """
    from pathlib import Path
    if isinstance(image_source, (str, Path)):
        p = Path(image_source)
        if not p.exists():
            return None
        try:
            image_bytes = p.read_bytes()
        except OSError:
            return None
        title = f"🖼 {p.name}"
    elif isinstance(image_source, (bytes, bytearray)):
        image_bytes = bytes(image_source)
    else:
        return None

    top = tk.Toplevel(parent)
    top.title(title)
    sw = top.winfo_screenwidth() or 1280
    sh = top.winfo_screenheight() or 800
    w = int(sw * 0.82)
    h = int(sh * 0.85)
    top.geometry(f"{w}x{h}+{(sw - w) // 2}+{(sh - h) // 2}")
    try:
        top.transient(parent.winfo_toplevel())
    except tk.TclError:
        pass

    body = ttk.Frame(top, padding=4); body.pack(fill="both", expand=True)
    canvas = tk.Canvas(body, background="#1a1a1a", highlightthickness=0)
    canvas.pack(fill="both", expand=True)
    hint = ttk.Label(body, text="Click image or press Esc to close",
                      foreground="grey")
    hint.pack(pady=(4, 0))

    def render():
        canvas.update_idletasks()
        cw = canvas.winfo_width() or w
        ch = canvas.winfo_height() or h
        photo = display_image_bytes_on_canvas(canvas, image_bytes, cw, ch)
        top._photo_ref = photo  # keep reference alive
    top.after(50, render)

    def close(_e=None):
        try:
            top.destroy()
        except tk.TclError:
            pass
    top.bind("<Escape>", close)
    canvas.bind("<Button-1>", close)
    return top


def display_image_path_on_canvas(canvas, original_path,
                                    project_path,
                                    fit_width: int = 460,
                                    fit_height: int = 180):
    """Thumbnail-aware variant of display_image_bytes_on_canvas. Resolves a
    cached JPEG thumbnail (~30 KB) through thumbnails.ensure_thumbnail and
    hands its bytes to the canvas. Falls back to reading the original when
    no thumbnail can be produced.

    Caller MUST keep a reference to the returned PhotoImage (Tk garbage-
    collects un-referenced ones)."""
    from pathlib import Path
    if not original_path:
        return None
    try:
        path = Path(original_path)
    except TypeError:
        return None
    if not path.exists():
        return None
    target = path
    if project_path:
        try:
            import thumbnails as _th
            target = _th.ensure_thumbnail(project_path, path)
        except Exception:
            target = path
    try:
        data = target.read_bytes()
    except OSError:
        try:
            data = path.read_bytes()
        except OSError:
            return None
    return display_image_bytes_on_canvas(canvas, data,
                                          fit_width=fit_width,
                                          fit_height=fit_height)


def display_image_bytes_on_canvas(canvas, image_bytes: bytes,
                                   fit_width: int = 460,
                                   fit_height: int = 180):
    """Render image bytes (any format including SVG) onto a tk.Canvas,
    scaled to fit. Returns the tk.PhotoImage (caller MUST keep a reference)."""
    canvas.delete("all")
    try:
        from PIL import Image, ImageTk
        import io
    except ImportError:
        canvas.create_text(fit_width // 2, fit_height // 2,
            text="Install Pillow for image preview\n(pip install Pillow)\n\nThe image was saved to disk anyway.",
            fill="#888", justify="center", font=("", 9))
        return None

    # Detect SVG → rasterise first
    head = image_bytes[:200].lstrip()
    if head.startswith(b"<svg") or head.startswith(b"<?xml"):
        try:
            image_bytes = _svg_bytes_to_png(image_bytes,
                                              target_width=max(fit_width * 2, 1024))
        except Exception as e:
            canvas.create_text(fit_width // 2, fit_height // 2,
                text=f"(SVG rasterise failed: {e})\nFile saved to disk.",
                fill="#c84141", font=("", 9), justify="center")
            return None

    try:
        img = Image.open(io.BytesIO(image_bytes))
        ratio = min(fit_width / max(img.width, 1),
                    fit_height / max(img.height, 1))
        new_size = (max(int(img.width * ratio), 1),
                    max(int(img.height * ratio), 1))
        try:
            resample = Image.LANCZOS
        except AttributeError:
            resample = Image.Resampling.LANCZOS
        img = img.resize(new_size, resample)
        photo = ImageTk.PhotoImage(img)
        canvas.create_image(fit_width // 2, fit_height // 2,
                            image=photo, anchor="center")
        return photo
    except Exception as e:
        canvas.create_text(fit_width // 2, fit_height // 2,
            text=f"(failed to decode image: {e})",
            fill="#c84141", font=("", 9))
        return None


class CollapsibleSection(ttk.Frame):
    """A clickable header that toggles a body frame open/closed.
    Header shows ▶ when collapsed, ▼ when expanded. Body holds a read-only
    text area pre-populated with content_text."""

    def __init__(self, parent, title: str, content_text: str = "",
                 expanded: bool = False, text_height: int = 12, **kwargs):
        super().__init__(parent, **kwargs)
        self._expanded = bool(expanded)
        self._title = title

        self.header_btn = ttk.Button(self, command=self.toggle)
        self.header_btn.pack(fill="x")

        self.body = ttk.Frame(self)
        text_box = ttk.Frame(self.body); text_box.pack(fill="both", expand=True)
        self.text_widget = tk.Text(text_box, wrap="word", font=("Consolas", 10),
                                    padx=8, pady=6, background="#fafafa",
                                    foreground="#222", height=text_height,
                                    state="disabled")
        self.text_widget.pack(side="left", fill="both", expand=True)
        sb = ttk.Scrollbar(text_box, orient="vertical",
                            command=self.text_widget.yview)
        self.text_widget.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")

        if content_text:
            self.set_content(content_text)
        self._update_header()
        if self._expanded:
            self.body.pack(fill="both", expand=True)

    def toggle(self):
        self._expanded = not self._expanded
        if self._expanded:
            self.body.pack(fill="both", expand=True)
        else:
            self.body.pack_forget()
        self._update_header()

    def _update_header(self):
        arrow = "▼" if self._expanded else "▶"
        self.header_btn.config(text=f"{arrow}  {self._title}")

    def set_content(self, text: str):
        self.text_widget.config(state="normal")
        self.text_widget.delete("1.0", "end")
        self.text_widget.insert("1.0", text)
        self.text_widget.config(state="disabled")

    def set_title(self, title: str):
        self._title = title
        self._update_header()


_HEX_RE = re.compile(r"^#?[0-9a-fA-F]{6}$")


class ColorSwatch(ttk.Frame):
    """Color picker: label + colored swatch + hex entry + 🎨 chooser button."""

    def __init__(self, parent, label, default="#888888", help_text="",
                 swatch_width=4, **kwargs):
        super().__init__(parent, **kwargs)
        _label_with_help(self, label, help_text).pack(anchor="w", fill="x")

        row = ttk.Frame(self); row.pack(fill="x")
        self.swatch = tk.Label(row, background=default,
                               width=swatch_width, relief="solid", borderwidth=1)
        self.swatch.pack(side="left", ipady=4)

        self.var = tk.StringVar(value=default)
        self.entry = ttk.Entry(row, textvariable=self.var, width=10)
        self.entry.pack(side="left", padx=(6, 0))
        self.var.trace_add("write", self._on_change)

        btn = ttk.Button(row, text="🎨", width=3, command=self._pick)
        btn.pack(side="left", padx=(4, 0))
        Tooltip(btn, "Open the system color picker.")

    def _on_change(self, *_):
        val = self.var.get().strip()
        if _HEX_RE.match(val):
            if not val.startswith("#"):
                val = "#" + val
            try:
                self.swatch.config(background=val)
            except tk.TclError:
                pass

    def _pick(self):
        try:
            _, hex_val = colorchooser.askcolor(
                initialcolor=self.var.get() or "#888888", parent=self)
        except tk.TclError:
            return
        if hex_val:
            self.var.set(hex_val)

    def get(self) -> str:
        return self.var.get()

    def set(self, value: str):
        if value:
            self.var.set(value)
