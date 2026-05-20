"""
DebugPanel — collapsible right-side log of all API requests/responses
and unhandled exceptions. Subscribes to debug_log.DEBUG_LOG.
"""
import re
import tkinter as tk
from tkinter import ttk

from debug_log import DEBUG_LOG, LogEntry
from ui.widgets import Tooltip


_PLACEHOLDER_RE = re.compile(r"\{(\w+)\}")

_KIND_ICONS = {
    "request":   "📤",
    "response":  "📥",
    "exception": "💥",
    "info":      "ℹ",
}

_KIND_COLORS = {
    "request":   "#7ab0ff",
    "response":  "#7ade7a",
    "exception": "#ff7a7a",
    "info":      "#dddddd",
}


class DebugPanel(ttk.Frame):
    def __init__(self, parent):
        super().__init__(parent, padding=(4, 0, 0, 0))
        self._expanded = False
        self._entries: list = []
        self._build_ui()
        DEBUG_LOG.add_listener(self._on_log_entry)

    # ── UI ──────────────────────────────────────────────────────────
    def _build_ui(self):
        # Toggle bar (always visible)
        bar = ttk.Frame(self); bar.pack(side="top", fill="x")
        self.toggle_btn = ttk.Button(bar, text="🐞 Show debug ▶",
                                      width=18, command=self.toggle)
        self.toggle_btn.pack(side="left")
        Tooltip(self.toggle_btn,
            "Toggle the debug log: all API requests/responses with bolded "
            "placeholders, plus any unhandled application exceptions.")

        # Body (visible when expanded)
        self.body = ttk.Frame(self)

        # Toolbar inside body
        toolbar = ttk.Frame(self.body); toolbar.pack(fill="x", pady=(6, 4))
        clear_btn = ttk.Button(toolbar, text="🧹 Clear", width=10,
                                command=self._clear)
        clear_btn.pack(side="left")
        Tooltip(clear_btn, "Clear all log entries from this view (and the backing log).")

        self.summary_var = tk.StringVar(value="0 entries")
        ttk.Label(toolbar, textvariable=self.summary_var,
                  foreground="grey").pack(side="right")

        # Entries list (Treeview)
        list_frame = ttk.Frame(self.body); list_frame.pack(fill="both", expand=True)
        cols = ("time", "kind", "name", "summary")
        self.tree = ttk.Treeview(list_frame, columns=cols, show="headings",
                                  height=14, selectmode="browse")
        for c, w in zip(cols, [70, 30, 130, 180]):
            self.tree.heading(c, text=c.title())
            self.tree.column(c, width=w, anchor="w")
        tree_scroll = ttk.Scrollbar(list_frame, orient="vertical",
                                     command=self.tree.yview)
        self.tree.configure(yscrollcommand=tree_scroll.set)
        self.tree.pack(side="left", fill="both", expand=True)
        tree_scroll.pack(side="right", fill="y")
        self.tree.bind("<<TreeviewSelect>>", lambda _e: self._on_select())

        # Detail
        ttk.Label(self.body, text="Details:",
                  font=("", 9, "bold")).pack(anchor="w", pady=(6, 0))
        det_box = ttk.Frame(self.body); det_box.pack(fill="both", expand=True)
        self.detail_text = tk.Text(det_box, wrap="word", height=18,
                                    font=("Consolas", 8),
                                    background="#1a1a1a", foreground="#dddddd",
                                    padx=6, pady=4,
                                    insertbackground="#dddddd",
                                    selectbackground="#446")
        self.detail_text.pack(side="left", fill="both", expand=True)
        det_scroll = ttk.Scrollbar(det_box, orient="vertical",
                                    command=self.detail_text.yview)
        self.detail_text.configure(yscrollcommand=det_scroll.set)
        det_scroll.pack(side="right", fill="y")
        # Tags
        self.detail_text.tag_configure("placeholder",
            font=("Consolas", 8, "bold"), foreground="#7ab0ff")
        for k, color in _KIND_COLORS.items():
            self.detail_text.tag_configure(f"kind_{k}",
                font=("Consolas", 9, "bold"), foreground=color)
        self.detail_text.tag_configure("section",
            font=("Consolas", 8, "bold"), foreground="#888888")
        # Keep widget editable (state="normal") so user can select + Ctrl+C.
        # Edits get overwritten on the next selection anyway. Also bind
        # Ctrl+A and right-click → context menu.
        self.detail_text.bind("<Control-a>", self._select_all_detail)
        self.detail_text.bind("<Control-A>", self._select_all_detail)
        self.detail_text.bind("<Button-3>", self._show_detail_context_menu)
        self._detail_context_menu = tk.Menu(self.detail_text, tearoff=0)
        self._detail_context_menu.add_command(label="📋 Copy",
            command=self._copy_detail_selection)
        self._detail_context_menu.add_command(label="📋 Copy all",
            command=self._copy_detail_all)
        self._detail_context_menu.add_separator()
        self._detail_context_menu.add_command(label="✅ Select all",
            command=lambda: self._select_all_detail(None))

    def toggle(self):
        if self._expanded:
            self.body.pack_forget()
            self.toggle_btn.config(text="🐞 Show debug ▶")
            self._expanded = False
            try:
                self.configure(width=160)
            except tk.TclError:
                pass
        else:
            self.body.pack(side="top", fill="both", expand=True)
            self.toggle_btn.config(text="🐞 Hide debug ◀")
            self._expanded = True
            try:
                self.configure(width=460)
            except tk.TclError:
                pass
            self._refresh()

    # ── Sync ────────────────────────────────────────────────────────
    def _refresh(self):
        self._entries = DEBUG_LOG.entries()
        for iid in self.tree.get_children():
            self.tree.delete(iid)
        # Newest first: iterate from end → start, inserting at "end" so the
        # most-recent entry sits at row 0 and oldest is at the bottom.
        for i in range(len(self._entries) - 1, -1, -1):
            e = self._entries[i]
            icon = _KIND_ICONS.get(e.kind, "•")
            self.tree.insert("", "end", iid=str(i), values=(
                e.time_str, icon, e.name, self._summary(e),
            ))
        self.summary_var.set(f"{len(self._entries)} entries")
        # Scroll to top — newest is row 0
        try:
            self.tree.yview_moveto(0)
        except tk.TclError:
            pass

    @staticmethod
    def _summary(e: LogEntry) -> str:
        if e.kind == "request":
            return (e.details.get("user") or "")[:50]
        if e.kind == "response":
            err = e.details.get("error")
            if err:
                return f"❌ {err[:40]}"
            base = f"{e.details.get('status', '')} · {e.details.get('duration_s', 0):.2f}s"
            in_t = e.details.get("in_tokens")
            out_t = e.details.get("out_tokens")
            cost = e.details.get("cost_usd")
            if in_t is not None or out_t is not None:
                base += f" · {in_t or 0}→{out_t or 0} tok"
            if cost is not None and cost > 0:
                base += f" · ${cost:.4f}"
            return base
        if e.kind == "exception":
            return e.details.get("message", "")[:50]
        return e.details.get("message", "")[:50]

    def _on_log_entry(self, entry):
        # Listeners run from any thread — bounce to UI thread.
        try:
            self.after(0, self._refresh)
        except tk.TclError:
            pass  # window destroyed

    def _on_select(self):
        sel = self.tree.selection()
        if not sel:
            return
        try:
            idx = int(sel[0])
        except ValueError:
            return
        if idx >= len(self._entries):
            return
        self._render_detail(self._entries[idx])

    def _render_detail(self, e: LogEntry):
        self.detail_text.delete("1.0", "end")

        header = f"[{e.time_str}]  {_KIND_ICONS.get(e.kind,'•')}  {e.kind.upper()}  ·  {e.name}\n"
        self.detail_text.insert("end", header, f"kind_{e.kind}")

        for k, v in e.details.items():
            if v is None or v == "":
                continue
            self.detail_text.insert("end", f"\n— {k}:\n", "section")
            text = str(v)
            if k in ("system", "user", "response"):
                self._insert_with_placeholders(text)
            else:
                self.detail_text.insert("end", text + "\n")
        # State left as "normal" — keeps the text selectable + copyable.

    # ── Copy helpers (context menu + Ctrl+A) ────────────────────────
    def _show_detail_context_menu(self, event):
        try:
            self._detail_context_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self._detail_context_menu.grab_release()

    def _copy_detail_selection(self):
        try:
            text = self.detail_text.selection_get()
        except tk.TclError:
            return
        self.clipboard_clear()
        self.clipboard_append(text)

    def _copy_detail_all(self):
        text = self.detail_text.get("1.0", "end-1c")
        self.clipboard_clear()
        self.clipboard_append(text)

    def _select_all_detail(self, _event):
        self.detail_text.tag_add("sel", "1.0", "end-1c")
        return "break"

    def _insert_with_placeholders(self, text: str):
        last = 0
        for m in _PLACEHOLDER_RE.finditer(text):
            self.detail_text.insert("end", text[last:m.start()])
            self.detail_text.insert("end", m.group(0), "placeholder")
            last = m.end()
        self.detail_text.insert("end", text[last:] + "\n")

    def _clear(self):
        DEBUG_LOG.clear()
        self.detail_text.config(state="normal")
        self.detail_text.delete("1.0", "end")
        self.detail_text.config(state="disabled")
        self._refresh()
