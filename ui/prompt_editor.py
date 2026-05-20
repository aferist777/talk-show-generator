"""
PromptEditor — modal dialog to inspect / fork / edit a named system prompt.

Features:
  • dropdown of all saved versions (default + user)
  • description of the selected version
  • editable template area with {placeholder} markers in bold blue
  • a free-form 'additions' field
  • Implement button → LLM merges additions into the template (preserves placeholders,
    doesn't remove anything from the original unless asked)
  • Save as new version  /  Restore default  /  Delete version  /  Close
"""
import re
import threading
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog

from prompt_store import STORE
from ui.widgets import Tooltip, HelpIcon


_PLACEHOLDER_RE = re.compile(r"\{(\w+)\}")


_MERGE_SYSTEM = (
    "You are editing a system prompt for an LLM-driven application. "
    "Take the ORIGINAL prompt and integrate the USER ADDITIONS carefully. "
    "Rules:\n"
    "1. Do NOT remove anything from the ORIGINAL unless the USER explicitly asks.\n"
    "2. Preserve all {placeholder} markers EXACTLY as written.\n"
    "3. Maintain the structure, tone, and section ordering of the ORIGINAL.\n"
    "4. Output ONLY the integrated prompt — no preamble, no explanation, no code fences."
)


class PromptEditor(tk.Toplevel):
    def __init__(self, parent, prompt_name: str, main_window=None):
        super().__init__(parent)
        self.prompt_name = prompt_name
        self.spec = STORE.spec(prompt_name)
        self.main = main_window  # for LLM client access (Implement)

        self.title(f"⚙ {self.spec.display_name}")
        self.geometry("900x780")
        self.transient(parent)
        self.grab_set()

        self._build_ui()
        self._refresh_versions()
        self._load_version(STORE.get_active_version_name(prompt_name))

    def _build_ui(self):
        wrap = ttk.Frame(self, padding=14); wrap.pack(fill="both", expand=True)

        # Header / description
        ttk.Label(wrap, text=self.spec.description,
                  foreground="#444", wraplength=860, justify="left").pack(anchor="w")

        # Version dropdown row
        v_row = ttk.Frame(wrap); v_row.pack(fill="x", pady=(10, 4))
        ttk.Label(v_row, text="Version:", font=("", 10, "bold")).pack(side="left")
        HelpIcon(v_row,
            "Default = original built-in template. User-saved versions persist to "
            "~/.talkshow_generator/prompts/<this prompt>/."
        ).pack(side="left")
        self.version_var = tk.StringVar()
        self.version_combo = ttk.Combobox(v_row, textvariable=self.version_var,
                                           state="readonly", width=44)
        self.version_combo.pack(side="left", padx=(8, 6))
        self.version_combo.bind("<<ComboboxSelected>>", lambda _e: self._on_version_pick())

        activate_btn = ttk.Button(v_row, text="✅ Use this version",
                                   command=self._activate_version)
        activate_btn.pack(side="left", padx=(2, 0))
        Tooltip(activate_btn,
            "Mark the selected version as 'active' — every future call from the app uses it. "
            "Persists for this session.")

        del_btn = ttk.Button(v_row, text="🗑", width=3, command=self._delete_version)
        del_btn.pack(side="left", padx=(2, 0))
        Tooltip(del_btn, "Delete the selected version. Cannot delete 'default'.")

        # Description of selected version
        self.version_desc_var = tk.StringVar(value="")
        ttk.Label(wrap, textvariable=self.version_desc_var,
                  foreground="#888", font=("", 9, "italic"),
                  wraplength=860, justify="left").pack(anchor="w", pady=(0, 8))

        # Param legend
        if self.spec.param_docs:
            lf = ttk.LabelFrame(wrap, text=" 🧩 Placeholders (these inject data — keep them in the template) ",
                                 padding=8)
            lf.pack(fill="x", pady=(0, 8))
            legend = ttk.Frame(lf); legend.pack(fill="x")
            cols = 2
            items = list(self.spec.param_docs.items())
            for i, (k, doc) in enumerate(items):
                r, c = divmod(i, cols)
                cell = ttk.Frame(legend)
                cell.grid(row=r, column=c, sticky="w", padx=(0 if c == 0 else 12, 0), pady=1)
                ttk.Label(cell, text=f"{{{k}}}", foreground="#1d4e89",
                          font=("Consolas", 9, "bold")).pack(side="left")
                ttk.Label(cell, text=f" — {doc}", foreground="#444").pack(side="left")

        # Active template (editable)
        ttk.Label(wrap, text="Active template (edit freely — bold placeholders are injected by the app, do not break them):",
                  font=("", 10, "bold")).pack(anchor="w")
        tpl_box = ttk.Frame(wrap); tpl_box.pack(fill="both", expand=True, pady=(2, 8))
        self.template_text = tk.Text(tpl_box, wrap="word",
                                      font=("Consolas", 9), background="#fafafa",
                                      padx=6, pady=4)
        self.template_text.pack(side="left", fill="both", expand=True)
        tpl_scroll = ttk.Scrollbar(tpl_box, orient="vertical",
                                    command=self.template_text.yview)
        self.template_text.configure(yscrollcommand=tpl_scroll.set)
        tpl_scroll.pack(side="right", fill="y")
        self.template_text.tag_configure("placeholder",
            font=("Consolas", 9, "bold"), foreground="#1d4e89", background="#e0eaf7")
        self.template_text.bind("<<Modified>>", self._on_template_modified)

        # User addition
        ttk.Label(wrap, text="Your additions (plain language — the 'Implement' button will weave them in via LLM):",
                  font=("", 10, "bold")).pack(anchor="w")
        self.addition_text = tk.Text(wrap, height=4, wrap="word",
                                      font=("", 9), padx=6, pady=4)
        self.addition_text.pack(fill="x", pady=(2, 8))

        # Buttons
        btn_row = ttk.Frame(wrap); btn_row.pack(fill="x")
        impl_btn = ttk.Button(btn_row, text="✨ Implement (LLM merge)",
                               command=self._implement)
        impl_btn.pack(side="left")
        Tooltip(impl_btn,
            "Ask the LLM to carefully integrate the 'additions' field into the active template. "
            "Original content is preserved; placeholder markers are kept exactly.")

        save_btn = ttk.Button(btn_row, text="💾 Save as new version",
                               command=self._save_as_new)
        save_btn.pack(side="left", padx=(6, 0))
        Tooltip(save_btn, "Persist the current active template as a named user version on disk.")

        restore_btn = ttk.Button(btn_row, text="↩ Restore default",
                                  command=self._restore_default)
        restore_btn.pack(side="left", padx=(6, 0))
        Tooltip(restore_btn, "Reset the active template area back to the built-in default. Does not delete saved versions.")

        close_btn = ttk.Button(btn_row, text="✖ Close", command=self.destroy)
        close_btn.pack(side="right")
        Tooltip(close_btn, "Close the dialog. Unsaved changes are discarded.")

        self.status_var = tk.StringVar(value="")
        ttk.Label(wrap, textvariable=self.status_var,
                  foreground="grey", wraplength=860).pack(anchor="w", pady=(8, 0))

    # ── Versions ────────────────────────────────────────────────────
    def _refresh_versions(self):
        versions = STORE.list_versions(self.prompt_name)
        active = STORE.get_active_version_name(self.prompt_name)
        labels = []
        self._version_map: dict = {}
        for v in versions:
            mark = " ★" if v.name == active else ""
            label = f"{v.name}{mark}" + (" (default)" if v.is_default else "")
            labels.append(label)
            self._version_map[label] = v
        self.version_combo["values"] = labels
        if labels:
            current = next((l for l, v in self._version_map.items()
                            if v.name == active), labels[0])
            self.version_var.set(current)
            self._update_version_desc()

    def _selected_version(self):
        return self._version_map.get(self.version_var.get())

    def _update_version_desc(self):
        v = self._selected_version()
        if not v:
            self.version_desc_var.set("")
            return
        active_mark = " — currently ACTIVE" if v.name == STORE.get_active_version_name(self.prompt_name) else ""
        when = f" (saved {v.created_at})" if v.created_at else ""
        self.version_desc_var.set(f"ℹ {v.addition_summary}{when}{active_mark}")

    def _on_version_pick(self):
        v = self._selected_version()
        if v:
            self._load_version(v.name)

    def _load_version(self, version_name: str):
        for v in STORE.list_versions(self.prompt_name):
            if v.name == version_name:
                self.template_text.delete("1.0", "end")
                self.template_text.insert("1.0", v.template)
                self._highlight_placeholders()
                self._update_version_desc()
                self.status_var.set(f"Loaded version: {version_name}")
                return

    def _activate_version(self):
        v = self._selected_version()
        if not v:
            return
        STORE.set_active_version(self.prompt_name, v.name)
        self._refresh_versions()
        # Reselect the same label (now with ★)
        for label, ver in self._version_map.items():
            if ver.name == v.name:
                self.version_var.set(label)
                break
        self.status_var.set(f"✅ Activated: {v.name} — future calls will use this version.")

    def _delete_version(self):
        v = self._selected_version()
        if not v:
            return
        if v.is_default:
            messagebox.showinfo("⚠ Reserved",
                "Cannot delete the default version.", parent=self)
            return
        if not messagebox.askyesno("🗑 Delete version",
            f"Delete version '{v.name}' from disk?", parent=self):
            return
        STORE.delete_version(self.prompt_name, v.name)
        if STORE.get_active_version_name(self.prompt_name) == v.name:
            STORE.set_active_version(self.prompt_name, "default")
        self._refresh_versions()
        self._load_version("default")
        self.status_var.set(f"🗑 Deleted: {v.name}")

    # ── Template area ───────────────────────────────────────────────
    def _on_template_modified(self, _e=None):
        # Re-highlight on edit
        try:
            if self.template_text.edit_modified():
                self._highlight_placeholders()
                self.template_text.edit_modified(False)
        except tk.TclError:
            pass

    def _highlight_placeholders(self):
        self.template_text.tag_remove("placeholder", "1.0", "end")
        text = self.template_text.get("1.0", "end-1c")
        for m in _PLACEHOLDER_RE.finditer(text):
            start_idx = f"1.0 + {m.start()} chars"
            end_idx = f"1.0 + {m.end()} chars"
            self.template_text.tag_add("placeholder", start_idx, end_idx)

    def _restore_default(self):
        self.template_text.delete("1.0", "end")
        self.template_text.insert("1.0", self.spec.default_template)
        self._highlight_placeholders()
        self.status_var.set("↩ Active template reset to default (not saved).")

    # ── Save / Implement ────────────────────────────────────────────
    def _save_as_new(self):
        template = self.template_text.get("1.0", "end").strip()
        if not template:
            messagebox.showwarning("⚠ Empty", "Template is empty.", parent=self)
            return
        addition_summary = self.addition_text.get("1.0", "end").strip()
        if not addition_summary:
            addition_summary = simpledialog.askstring(
                "💾 Save version",
                "Short description of what's different in this version:\n"
                "(shown in tooltips and the version dropdown)",
                parent=self) or "(no description)"
        name = simpledialog.askstring("💾 Save version", "Version name:", parent=self)
        if not name:
            return
        if name.lower() == "default":
            messagebox.showerror("❌ Reserved", "'default' is a reserved name.", parent=self)
            return
        try:
            path = STORE.save_version(self.prompt_name, name, template, addition_summary)
        except ValueError as e:
            messagebox.showerror("❌ Save failed", str(e), parent=self)
            return
        STORE.set_active_version(self.prompt_name, name)
        self._refresh_versions()
        for label, ver in self._version_map.items():
            if ver.name == name:
                self.version_var.set(label)
                break
        self.addition_text.delete("1.0", "end")
        self.status_var.set(f"✅ Saved & activated: {path}")

    def _implement(self):
        addition = self.addition_text.get("1.0", "end").strip()
        if not addition:
            messagebox.showinfo("⚠ Empty additions",
                "Type your additions in the box below first.", parent=self)
            return
        if not self.main:
            self.status_var.set(
                "🚧 LLM-merge needs main-window context; opened in detached mode. "
                "Edit the template directly and Save as new version.")
            return
        original = self.template_text.get("1.0", "end").strip()
        self.status_var.set("🔄 Asking LLM to carefully integrate your additions…")

        def worker():
            try:
                client = self.main._build_client()
                user_msg = (
                    f"ORIGINAL PROMPT:\n```\n{original}\n```\n\n"
                    f"USER ADDITIONS (instructions in plain language):\n{addition}\n\n"
                    "Now output the integrated prompt."
                )
                result = client.complete(
                    system=_MERGE_SYSTEM, user=user_msg,
                    max_tokens=4000, temperature=0.3,
                )
                self.after(0, lambda: self._apply_merged(result))
            except Exception as e:
                err = str(e)
                self.after(0, lambda: self.status_var.set(f"❌ Merge failed: {err[:200]}"))

        threading.Thread(target=worker, daemon=True).start()

    def _apply_merged(self, merged: str):
        merged = (merged or "").strip()
        # Strip code fences if present
        if merged.startswith("```"):
            lines = merged.split("\n")
            if lines and lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].startswith("```"):
                lines = lines[:-1]
            merged = "\n".join(lines).strip()
        self.template_text.delete("1.0", "end")
        self.template_text.insert("1.0", merged)
        self._highlight_placeholders()
        self.status_var.set(
            "✅ Additions integrated. Review the active template, then click 💾 Save as new version.")
