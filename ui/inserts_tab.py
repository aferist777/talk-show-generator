"""
Step 3 — Broadcast inserts.

Raw asset library: b-rolls + graphic inserts + SFX, without placement.
Step 4 (Editing) will compose these onto the timeline from step 2.

Sub-tabs:
  🎞 B-rolls         — video cutaways (lab, kitchen, packshots, etc.)
  🖼 Graphic inserts — static graphics (anatomy, price flash, lower thirds, etc.)
  🎵 SFX             — sound effects (stings, whooshes, ambient)
"""
import threading
import time
import tkinter as tk
from tkinter import ttk, messagebox

import config as cfg
import projects
from ui.widgets import (
    LabeledEntry, LabeledCombobox, LabeledText, SectionFrame,
    Tooltip, HelpIcon, ModelPicker, bind_autosave,
)


# Per-asset-kind config (file extension + duration field + provider hint)
_KIND_CONFIG = {
    "brolls": {
        "label":              "🎞 B-roll video library",
        "categories_const":   "BROLL_CATEGORIES",
        "file_ext":           ".mp4",
        "needs_duration":     True,
        "provider_hint":      "kie.ai",
        "default_duration":   4.0,
    },
    "graphics": {
        "label":              "🖼 Graphic inserts library",
        "categories_const":   "GRAPHIC_CATEGORIES",
        "file_ext":           ".png",
        "needs_duration":     False,
        "provider_hint":      "kie.ai",
        "default_duration":   0.0,
    },
    "sfx": {
        "label":              "🎵 SFX library",
        "categories_const":   "SFX_CATEGORIES",
        "file_ext":           ".mp3",
        "needs_duration":     True,
        "provider_hint":      "ElevenLabs text-to-SFX",
        "default_duration":   2.5,
    },
}


class BroadcastInsertsTab(ttk.Frame):
    """Holds the inner notebook for all step-3 sub-tabs."""

    def __init__(self, parent, main_window):
        super().__init__(parent)
        self.main = main_window

        nb = ttk.Notebook(self, padding=6)
        nb.pack(fill="both", expand=True)
        self._sub_nb = nb

        tab_brolls = ttk.Frame(nb, padding=14)
        tab_graphics = ttk.Frame(nb, padding=14)
        tab_sfx = ttk.Frame(nb, padding=14)

        nb.add(tab_brolls, text="🎞 B-rolls")
        nb.add(tab_graphics, text="🖼 Graphic inserts")
        nb.add(tab_sfx, text="🎵 SFX")
        self._sub_tabs = {"brolls": tab_brolls,
                           "graphics": tab_graphics,
                           "sfx": tab_sfx}
        self._sub_tab_originals = {"brolls": "🎞 B-rolls",
                                    "graphics": "🖼 Graphic inserts",
                                    "sfx": "🎵 SFX"}

        self.brolls_view = AssetLibraryView(tab_brolls, main_window, asset_kind="brolls")
        self.brolls_view.pack(fill="both", expand=True)

        self.graphics_view = AssetLibraryView(tab_graphics, main_window, asset_kind="graphics")
        self.graphics_view.pack(fill="both", expand=True)

        self.sfx_view = AssetLibraryView(tab_sfx, main_window, asset_kind="sfx")
        self.sfx_view.pack(fill="both", expand=True)

    def apply_inserts(self, project_path):
        """Reload all 3 libraries from disk. Called by MainWindow on project open."""
        self.brolls_view.apply_assets(project_path)
        self.graphics_view.apply_assets(project_path)
        self.sfx_view.apply_assets(project_path)

    def refresh_sub_tab_marks(self) -> tuple:
        """Update ✅ marks on each library tab. Returns (all_done, any_done) —
        MainWindow uses this tuple to choose ✅ / ⚠ / nothing on the top-level
        pipeline tab."""
        proj = self.main.current_project
        done_flags = {}
        for key in self._sub_tabs:
            done = False
            if proj:
                lp = projects.inserts_library_path(proj, key)
                if lp.exists():
                    try:
                        import json as _json
                        data = _json.loads(lp.read_text(encoding="utf-8"))
                        done = any(a.get("status") == "generated"
                                    for a in (data.get("assets") or []))
                    except (Exception,):
                        done = False
            done_flags[key] = done

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


class AssetLibraryView(ttk.Frame):
    """Reusable list+editor for one asset kind (brolls / graphics / sfx)."""

    def __init__(self, parent, main_window, *, asset_kind: str):
        super().__init__(parent)
        self.main = main_window
        self.asset_kind = asset_kind
        self.kcfg = _KIND_CONFIG[asset_kind]
        self.categories = getattr(cfg, self.kcfg["categories_const"])

        self._assets: list = []
        self._selected_idx: int | None = None
        self._gen_cancel = threading.Event()
        self._gen_thread = None

        self._build_ui()

    # ── UI ──────────────────────────────────────────────────────────
    def _build_ui(self):
        title = self.kcfg["label"]
        provider = self.kcfg["provider_hint"]

        # ── Actions ────────────────────────────────────────────────
        af = SectionFrame(self, f"▶ Actions — {title}")
        af.pack(fill="x", pady=(0, 10))

        # Image-model picker for brolls / graphics. SFX uses ElevenLabs.
        if self.asset_kind in ("brolls", "graphics"):
            ModelPicker(af, kind="image", main_window=self.main,
                         label_text="Image model:").pack(anchor="w", pady=(0, 6))

        btn_row = ttk.Frame(af); btn_row.pack(fill="x")

        gen_sel_btn = ttk.Button(btn_row, text="🎬 Generate selected",
                                  command=self._generate_selected)
        gen_sel_btn.pack(side="left")
        Tooltip(gen_sel_btn,
            f"Render the currently-selected asset via {provider}. "
            f"Updates only this one asset's status and file.")

        gen_all_btn = ttk.Button(btn_row, text="🚀 Generate all pending",
                                  command=self._generate_all_pending)
        gen_all_btn.pack(side="left", padx=(6, 0))
        Tooltip(gen_all_btn,
            f"Render every asset whose status is 'pending' via {provider}. "
            f"Skips assets already marked 'generated'.")

        cancel_btn = ttk.Button(btn_row, text="⏸ Cancel",
                                 command=self._cancel_generation)
        cancel_btn.pack(side="left", padx=(6, 0))
        Tooltip(cancel_btn,
            "Stop the current batch at the next asset boundary. "
            "Already-generated files are kept.")

        save_btn = ttk.Button(btn_row, text="💾 Save library",
                               command=self._save_library)
        save_btn.pack(side="left", padx=(20, 0))
        Tooltip(save_btn,
            f"Persist the asset list to <project>/inserts/{self.asset_kind}.json.")

        self._status_var = tk.StringVar(value="")
        ttk.Label(af, textvariable=self._status_var,
                  foreground="grey", wraplength=900).pack(anchor="w", pady=(8, 0))

        # ── Assets table ───────────────────────────────────────────
        list_frame = SectionFrame(self, "📋 Assets")
        list_frame.pack(fill="both", expand=True, pady=(0, 10))

        needs_dur = self.kcfg["needs_duration"]
        if needs_dur:
            cols = ("idx", "category", "prompt", "dur", "status", "path")
            widths = {"idx": 40, "category": 150, "prompt": 380,
                      "dur": 50, "status": 80, "path": 240}
        else:
            cols = ("idx", "category", "prompt", "status", "path")
            widths = {"idx": 40, "category": 150, "prompt": 430,
                      "status": 80, "path": 240}
        headings = {"idx": "#", "category": "Category", "prompt": "Prompt",
                    "dur": "Dur", "status": "Status", "path": "File path"}

        self.tree = ttk.Treeview(list_frame, columns=cols, show="headings",
                                  height=10, selectmode="browse")
        for c in cols:
            self.tree.heading(c, text=headings[c])
            self.tree.column(c, width=widths[c],
                anchor="w" if c in ("category", "prompt", "path") else "center")

        tree_scroll = ttk.Scrollbar(list_frame, orient="vertical",
                                     command=self.tree.yview)
        self.tree.configure(yscrollcommand=tree_scroll.set)
        self.tree.pack(side="left", fill="both", expand=True)
        tree_scroll.pack(side="right", fill="y")
        self.tree.bind("<<TreeviewSelect>>", lambda _e: self._on_select())

        # ── Editor ─────────────────────────────────────────────────
        ed = SectionFrame(self, "✏ Edit selected asset")
        ed.pack(fill="x")

        grid = ttk.Frame(ed); grid.pack(fill="x")
        for c in range(3):
            grid.columnconfigure(c, weight=1)

        self.cat_picker = LabeledCombobox(grid, "Category",
            self.categories, self.categories[0],
            help_text=f"Asset category. Used to group and filter — step 4 also reads category to pick fitting inserts for each beat context.")
        self.cat_picker.grid(row=0, column=0, sticky="ew", padx=(0, 8), pady=4)

        if needs_dur:
            self.dur_entry = LabeledEntry(grid, "Duration (s)",
                f"{self.kcfg['default_duration']:.1f}", width=8,
                help_text="Target duration in seconds. Step 4 uses this to know how long to play the asset on the timeline.")
            self.dur_entry.grid(row=0, column=1, sticky="ew", padx=(0, 8), pady=4)
        else:
            self.dur_entry = None

        self.status_picker = LabeledCombobox(grid, "Status",
            cfg.ASSET_STATUSES, cfg.ASSET_STATUSES[0],
            help_text="pending = ready to render; generated = file exists on disk; failed = last render errored.")
        self.status_picker.grid(row=0, column=2, sticky="ew", pady=4)

        self.prompt_text = LabeledText(ed, "Prompt",
            height=3, width=80,
            placeholder="e.g., 'scientist in white coat examining glass test tubes filled with green liquid, soft lab lighting, shallow depth of field'",
            help_text=f"Free-form text fed to {provider}. Detail matters — describe the subject, lighting, framing, mood.")
        self.prompt_text.pack(fill="x", pady=(4, 0))

        # Editor buttons row
        ed_btns = ttk.Frame(ed); ed_btns.pack(fill="x", pady=(8, 0))

        apply_btn = ttk.Button(ed_btns, text="💾 Apply changes",
                                command=self._apply_edit)
        apply_btn.pack(side="left")
        Tooltip(apply_btn,
            "Save the editor fields back into the selected asset. "
            "Switching rows without Apply discards changes.")

        add_btn = ttk.Button(ed_btns, text="➕ Add asset",
                              command=self._add_asset)
        add_btn.pack(side="left", padx=(6, 0))
        Tooltip(add_btn,
            "Insert a new empty asset at the end of the list. Edit it in the form above, then click Apply.")

        del_btn = ttk.Button(ed_btns, text="🗑 Delete",
                              command=self._delete_asset)
        del_btn.pack(side="left", padx=(6, 0))
        Tooltip(del_btn,
            "Remove the selected asset from the library. The generated file on disk (if any) is kept.")

        up_btn = ttk.Button(ed_btns, text="⬆ Up", command=self._move_up)
        up_btn.pack(side="left", padx=(20, 0))
        Tooltip(up_btn, "Move the selected asset one position earlier in the library.")

        down_btn = ttk.Button(ed_btns, text="⬇ Down", command=self._move_down)
        down_btn.pack(side="left", padx=(6, 0))
        Tooltip(down_btn, "Move the selected asset one position later in the library.")

        self._refresh_tree()

    # ── DATA HELPERS ────────────────────────────────────────────────
    def _id_for_index(self, i: int) -> str:
        prefix = {"brolls": "br", "graphics": "gr", "sfx": "sx"}[self.asset_kind]
        return f"{prefix}{i + 1:03d}"

    def _file_path_for(self, asset_id: str) -> str:
        ext = self.kcfg["file_ext"]
        return f"inserts/{self.asset_kind}/{asset_id}{ext}"

    def _refresh_tree(self):
        for iid in self.tree.get_children():
            self.tree.delete(iid)
        for i, a in enumerate(self._assets):
            prompt = (a.get("prompt") or "").replace("\n", " ")
            if len(prompt) > 70:
                prompt = prompt[:67] + "…"
            fp = a.get("file_path") or "—"
            if len(fp) > 50:
                fp = fp[:47] + "…"
            row = [i + 1, a.get("category", "—"), prompt or "—"]
            if self.kcfg["needs_duration"]:
                row.append(f"{a.get('duration', 0):.1f}")
            row.append(a.get("status", "pending"))
            row.append(fp)
            self.tree.insert("", "end", iid=str(i), values=tuple(row))

    def _on_select(self):
        sel = self.tree.selection()
        if not sel:
            return
        idx = int(sel[0])
        if idx >= len(self._assets):
            return
        self._selected_idx = idx
        a = self._assets[idx]
        self.cat_picker.set(a.get("category") or self.categories[0])
        if self.dur_entry:
            self.dur_entry.set(f"{a.get('duration', self.kcfg['default_duration']):.1f}")
        self.status_picker.set(a.get("status") or cfg.ASSET_STATUSES[0])
        self.prompt_text.set(a.get("prompt") or "")

    def _apply_edit(self):
        if self._selected_idx is None:
            return
        idx = self._selected_idx
        a = self._assets[idx]
        a["category"] = self.cat_picker.get()
        a["status"] = self.status_picker.get()
        a["prompt"] = self.prompt_text.get()
        if self.dur_entry:
            try:
                a["duration"] = float(self.dur_entry.get())
            except ValueError:
                a["duration"] = self.kcfg["default_duration"]
        self._refresh_tree()
        self.tree.selection_set(str(idx))
        self._status_var.set(f"✅ Asset #{idx + 1} updated.")
        self._schedule_autosave()

    def _add_asset(self):
        new_id = self._id_for_index(len(self._assets))
        self._assets.append({
            "id": new_id,
            "category": self.categories[0],
            "prompt": "",
            "duration": self.kcfg["default_duration"] if self.kcfg["needs_duration"] else 0.0,
            "status": "pending",
            "file_path": self._file_path_for(new_id),
            "notes": "",
        })
        new_idx = len(self._assets) - 1
        self._refresh_tree()
        self.tree.selection_set(str(new_idx))
        self.tree.see(str(new_idx))
        self._on_select()
        self._schedule_autosave()

    def _delete_asset(self):
        if self._selected_idx is None:
            return
        idx = self._selected_idx
        del self._assets[idx]
        self._selected_idx = None
        self._refresh_tree()
        self._status_var.set(f"🗑 Asset #{idx + 1} removed.")
        self._schedule_autosave()

    def _move_up(self):
        if self._selected_idx is None or self._selected_idx == 0:
            return
        i = self._selected_idx
        self._assets[i - 1], self._assets[i] = self._assets[i], self._assets[i - 1]
        self._selected_idx = i - 1
        self._refresh_tree()
        self.tree.selection_set(str(i - 1))
        self._schedule_autosave()

    def _move_down(self):
        if self._selected_idx is None or self._selected_idx >= len(self._assets) - 1:
            return
        i = self._selected_idx
        self._assets[i + 1], self._assets[i] = self._assets[i], self._assets[i + 1]
        self._selected_idx = i + 1
        self._refresh_tree()
        self.tree.selection_set(str(i + 1))
        self._schedule_autosave()

    # ── PERSISTENCE ─────────────────────────────────────────────────
    def _require_project(self) -> bool:
        if not self.main.current_project:
            messagebox.showwarning(
                "⚠ No project",
                "Open or save a project first — inserts live inside the project folder.",
                parent=self,
            )
            return False
        return True

    def _save_library(self):
        if not self._require_project():
            return
        payload = {"version": 1, "kind": self.asset_kind, "assets": self._assets}
        path = projects.save_inserts_library(self.main.current_project,
                                              self.asset_kind, payload)
        self._status_var.set(f"✅ Library saved: {path}")

    def _schedule_autosave(self):
        """Debounced silent save of the asset list."""
        if self.main._autosave_paused:
            return
        prev = getattr(self, "_autosave_after_id", None)
        if prev:
            try:
                self.after_cancel(prev)
            except tk.TclError:
                pass
        self._autosave_after_id = self.after(300, self._do_autosave)

    def _do_autosave(self):
        self._autosave_after_id = None
        if self.main._autosave_paused or not self.main.current_project:
            return
        try:
            payload = {"version": 1, "kind": self.asset_kind, "assets": self._assets}
            projects.save_inserts_library(self.main.current_project,
                                           self.asset_kind, payload)
            self.main._mark_autosaved()
            self.main._refresh_all_tab_marks()
        except Exception as e:
            from debug_log import DEBUG_LOG
            DEBUG_LOG.log_exception(f"autosave.inserts_{self.asset_kind}", e)

    def apply_assets(self, project_path):
        """Load library from disk into state. Called by MainWindow on project open."""
        self._assets = []
        self._selected_idx = None
        if project_path:
            data = projects.load_inserts_library(project_path, self.asset_kind)
            self._assets = data.get("assets", []) or []
        if hasattr(self, "tree"):
            self._refresh_tree()

    # ── GENERATION STUBS (kie.ai / ElevenLabs SFX) ──────────────────
    def _cancel_generation(self):
        if self._gen_thread and self._gen_thread.is_alive():
            self._gen_cancel.set()
            self._status_var.set("⏸ Cancel requested — stopping at next asset.")
        else:
            self._status_var.set("(nothing running)")

    def _generate_selected(self):
        if self._selected_idx is None:
            messagebox.showinfo("⚠ No selection",
                "Select an asset first by clicking a row in the table.",
                parent=self)
            return
        if self._gen_thread and self._gen_thread.is_alive():
            self._status_var.set("⚠ Generation already running.")
            return
        idx = self._selected_idx
        self._gen_cancel.clear()
        self._gen_thread = threading.Thread(
            target=self._gen_worker, args=([idx],), daemon=True)
        self._gen_thread.start()

    def _generate_all_pending(self):
        if self._gen_thread and self._gen_thread.is_alive():
            self._status_var.set("⚠ Generation already running.")
            return
        pending = [i for i, a in enumerate(self._assets)
                   if a.get("status") == "pending"]
        if not pending:
            self._status_var.set("(no pending assets to generate)")
            return
        self._gen_cancel.clear()
        self._gen_thread = threading.Thread(
            target=self._gen_worker, args=(pending,), daemon=True)
        self._gen_thread.start()

    def _gen_worker(self, indices: list):
        # Engine is read live from main_window — image vs SFX provider
        if self.asset_kind in ("brolls", "graphics"):
            engine = (f"{self.main.image_provider_var.get()} / "
                      f"{self.main.image_model_slug_var.get() or '(no model)'}")
        else:
            engine = "ElevenLabs text-to-SFX"
        total = len(indices)
        for n, idx in enumerate(indices, start=1):
            if self._gen_cancel.is_set():
                self.after(0, lambda: self._status_var.set("⏸ Cancelled."))
                return
            asset = self._assets[idx]
            self.after(0, lambda i=idx, n=n, t=total: self._status_var.set(
                f"🔄 [{n}/{t}] generating {self.asset_kind} #{i + 1} via {engine}…"))
            # Stub: simulate render time
            time.sleep(0.6 if self.asset_kind == "brolls" else 0.3)
            # Mark as 'generated' with a path that's a real placeholder file path
            # (the actual file is NOT written here — only the metadata)
            self._assets[idx]["status"] = "generated"
            self._assets[idx]["file_path"] = self._file_path_for(asset.get("id") or self._id_for_index(idx))
            self.after(0, self._refresh_tree)
        self.after(0, lambda: self._status_var.set(
            f"✅ Done — {total} {self.asset_kind} {'asset' if total == 1 else 'assets'} "
            f"marked generated (rendering via {engine} pending real API wiring)."))
