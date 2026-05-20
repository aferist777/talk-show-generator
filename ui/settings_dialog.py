"""
Settings dialog: API keys, provider/model defaults, kie.ai connection.
"""
import threading
import tkinter as tk
from tkinter import ttk, messagebox

import settings
from llm_clients import (
    OpenRouterClient, OllamaClient, AnthropicClient, KieClient, ElevenLabsClient
)
import config as cfg
from ui.widgets import Tooltip, HelpIcon


class SettingsDialog(tk.Toplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.title("⚙ Settings")
        self.geometry("620x520")
        self.transient(parent)
        self.grab_set()

        self.current = settings.load_settings()

        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True, padx=10, pady=10)

        self._build_api_tab(nb)
        self._build_ollama_tab(nb)
        self._build_defaults_tab(nb)

        btn_row = ttk.Frame(self)
        btn_row.pack(fill="x", padx=10, pady=(0, 10))
        save_btn = ttk.Button(btn_row, text="💾 Save", command=self._save)
        save_btn.pack(side="right")
        Tooltip(save_btn, "Write current values to ~/.talkshow_generator/config.json and close.")
        cancel_btn = ttk.Button(btn_row, text="✖ Cancel", command=self.destroy)
        cancel_btn.pack(side="right", padx=(0, 6))
        Tooltip(cancel_btn, "Discard changes and close without saving.")

    # ── API KEYS TAB ────────────────────────────────────────────────
    def _build_api_tab(self, parent):
        f = ttk.Frame(parent, padding=14)
        parent.add(f, text="🔑 API Keys")

        # OpenRouter
        or_label = ttk.Frame(f); or_label.pack(anchor="w", fill="x")
        ttk.Label(or_label, text="🌐 OpenRouter API Key", font=("", 10, "bold")).pack(side="left")
        HelpIcon(or_label,
            "API key for OpenRouter — a meta-provider that routes to many LLMs (Claude, GPT, Gemini, etc.) with a single key. Recommended default."
        ).pack(side="left")
        ttk.Label(f, text="https://openrouter.ai/keys", foreground="grey").pack(anchor="w")
        row = ttk.Frame(f); row.pack(fill="x", pady=(2, 4))
        self.openrouter_var = tk.StringVar(value=self.current.get("openrouter_api_key", ""))
        e = ttk.Entry(row, textvariable=self.openrouter_var, show="*")
        e.pack(side="left", fill="x", expand=True)
        or_test = ttk.Button(row, text="🧪 Test", width=10, command=self._test_openrouter)
        or_test.pack(side="left", padx=(6, 0))
        Tooltip(or_test,
            "Send a tiny ping to the model selected below to verify the OpenRouter key works.")
        or_save = ttk.Button(row, text="💾 Save", width=10,
            command=lambda: self._save_single_key("openrouter_api_key",
                                                   self.openrouter_var.get(), "OpenRouter"))
        or_save.pack(side="left", padx=(4, 0))
        Tooltip(or_save,
            "Save just the OpenRouter key to disk now — no need to click the dialog's Save button.")

        ttk.Label(f,
            text=("ℹ Model selection lives per-tab now — pick text/image models "
                  "in the relevant sub-tabs (Input data, Storyboard, Logo & "
                  "Brand, Studio design, Characters, Audience, B-rolls, "
                  "Graphics, Composition plan). The 🧪 Test button above uses "
                  "whichever text model is currently active."),
            foreground="#444", font=("", 9, "italic"),
            wraplength=560, justify="left").pack(anchor="w", pady=(4, 0))

        ttk.Separator(f, orient="horizontal").pack(fill="x", pady=10)

        # Anthropic
        an_label = ttk.Frame(f); an_label.pack(anchor="w", fill="x")
        ttk.Label(an_label, text="🤖 Anthropic Direct API Key", font=("", 10, "bold")).pack(side="left")
        HelpIcon(an_label,
            "API key for Anthropic's direct Claude API. Use this for Claude-only workflows or when OpenRouter is unavailable."
        ).pack(side="left")
        ttk.Label(f, text="https://console.anthropic.com/settings/keys",
                  foreground="grey").pack(anchor="w")
        row = ttk.Frame(f); row.pack(fill="x", pady=(2, 4))
        self.anthropic_var = tk.StringVar(value=self.current.get("anthropic_api_key", ""))
        ttk.Entry(row, textvariable=self.anthropic_var, show="*").pack(
            side="left", fill="x", expand=True)
        an_test = ttk.Button(row, text="🧪 Test", width=10, command=self._test_anthropic)
        an_test.pack(side="left", padx=(6, 0))
        Tooltip(an_test, "Send a tiny test request to verify the Anthropic key works.")
        an_save = ttk.Button(row, text="💾 Save", width=10,
            command=lambda: self._save_single_key("anthropic_api_key",
                                                   self.anthropic_var.get(), "Anthropic"))
        an_save.pack(side="left", padx=(4, 0))
        Tooltip(an_save,
            "Save just the Anthropic key to disk now — no need to click the dialog's Save button.")
        ttk.Separator(f, orient="horizontal").pack(fill="x", pady=10)

        # kie.ai
        kie_label = ttk.Frame(f); kie_label.pack(anchor="w", fill="x")
        ttk.Label(kie_label, text="🎨 kie.ai API Key (visual & lip-sync generation)",
                  font=("", 10, "bold")).pack(side="left")
        HelpIcon(kie_label,
            "API key for kie.ai — used in step 2 for image generation, character renders, and lip-sync video. Not needed for step 1 (script only)."
        ).pack(side="left")
        ttk.Label(f, text="https://kie.ai/dashboard", foreground="grey").pack(anchor="w")
        row = ttk.Frame(f); row.pack(fill="x", pady=(2, 4))
        self.kie_var = tk.StringVar(value=self.current.get("kie_api_key", ""))
        ttk.Entry(row, textvariable=self.kie_var, show="*").pack(
            side="left", fill="x", expand=True)
        kie_test = ttk.Button(row, text="🧪 Test", width=10, command=self._test_kie)
        kie_test.pack(side="left", padx=(6, 0))
        Tooltip(kie_test, "Send a tiny test request to verify the kie.ai key works.")
        kie_save = ttk.Button(row, text="💾 Save", width=10,
            command=lambda: self._save_single_key("kie_api_key",
                                                   self.kie_var.get(), "kie.ai"))
        kie_save.pack(side="left", padx=(4, 0))
        Tooltip(kie_save,
            "Save just the kie.ai key to disk now — no need to click the dialog's Save button.")
        ttk.Separator(f, orient="horizontal").pack(fill="x", pady=10)

        # ElevenLabs
        el_label = ttk.Frame(f); el_label.pack(anchor="w", fill="x")
        ttk.Label(el_label, text="🔊 ElevenLabs API Key (voices & crowd SFX)",
                  font=("", 10, "bold")).pack(side="left")
        HelpIcon(el_label,
            "API key for ElevenLabs — used in step 2 for character TTS voices and crowd reactions via text-to-SFX. "
            "Not needed for step 1 (script only)."
        ).pack(side="left")
        ttk.Label(f, text="https://elevenlabs.io/app/settings/api-keys",
                  foreground="grey").pack(anchor="w")
        row = ttk.Frame(f); row.pack(fill="x", pady=(2, 4))
        self.elevenlabs_var = tk.StringVar(value=self.current.get("elevenlabs_api_key", ""))
        ttk.Entry(row, textvariable=self.elevenlabs_var, show="*").pack(
            side="left", fill="x", expand=True)
        el_test = ttk.Button(row, text="🧪 Test", width=10, command=self._test_elevenlabs)
        el_test.pack(side="left", padx=(6, 0))
        Tooltip(el_test, "Send a tiny test request to verify the ElevenLabs key and see your subscription tier.")
        el_save = ttk.Button(row, text="💾 Save", width=10,
            command=lambda: self._save_single_key("elevenlabs_api_key",
                                                   self.elevenlabs_var.get(), "ElevenLabs"))
        el_save.pack(side="left", padx=(4, 0))
        Tooltip(el_save,
            "Save just the ElevenLabs key to disk now — no need to click the dialog's Save button.")

        # Status line
        self.status_var = tk.StringVar(value="")
        ttk.Label(f, textvariable=self.status_var, foreground="grey",
                  wraplength=560, justify="left").pack(anchor="w", pady=(20, 0))

    # ── OLLAMA TAB ──────────────────────────────────────────────────
    def _build_ollama_tab(self, parent):
        f = ttk.Frame(parent, padding=14)
        parent.add(f, text="🦙 Ollama (Local)")

        ttk.Label(f, text="Ollama runs models on your machine. Free, private, offline.",
                  foreground="grey", wraplength=560).pack(anchor="w", pady=(0, 10))

        oh_label = ttk.Frame(f); oh_label.pack(anchor="w", fill="x")
        ttk.Label(oh_label, text="Ollama host").pack(side="left")
        HelpIcon(oh_label,
            "URL where Ollama is running. Default http://localhost:11434 is correct unless you've reconfigured Ollama or are pointing at a remote machine."
        ).pack(side="left")
        self.ollama_host_var = tk.StringVar(
            value=self.current.get("ollama_host", "http://localhost:11434"))
        ttk.Entry(f, textvariable=self.ollama_host_var).pack(fill="x", pady=(2, 8))

        row = ttk.Frame(f); row.pack(fill="x")
        ol_test = ttk.Button(row, text="🧪 Test connection", command=self._test_ollama)
        ol_test.pack(side="left")
        Tooltip(ol_test, "Ping the Ollama server at the host above. Reports success/failure in a popup.")
        ol_refresh = ttk.Button(row, text="🔄 Refresh model list", command=self._refresh_ollama_models)
        ol_refresh.pack(side="left", padx=(6, 0))
        Tooltip(ol_refresh, "Fetch the list of locally-installed Ollama models. Populates the box below.")

        ttk.Label(f, text="📦 Models installed:", font=("", 10, "bold")).pack(
            anchor="w", pady=(16, 4))
        self.ollama_models_text = tk.Text(f, height=8, wrap="word", state="disabled")
        self.ollama_models_text.pack(fill="both", expand=True)

    # ── DEFAULTS TAB ────────────────────────────────────────────────
    def _build_defaults_tab(self, parent):
        f = ttk.Frame(parent, padding=14)
        parent.add(f, text="⚙ Defaults")

        dp_label = ttk.Frame(f); dp_label.pack(anchor="w", fill="x")
        ttk.Label(dp_label, text="Default provider").pack(side="left")
        HelpIcon(dp_label,
            "Provider selected by default in the main window's bottom panel on app launch."
        ).pack(side="left")
        self.default_provider_var = tk.StringVar(
            value=self.current.get("default_provider", "openrouter"))
        ttk.Combobox(f, textvariable=self.default_provider_var,
                     values=cfg.PROVIDERS, state="readonly").pack(fill="x", pady=(2, 10))

        dm_label = ttk.Frame(f); dm_label.pack(anchor="w", fill="x")
        ttk.Label(dm_label, text="Default model").pack(side="left")
        HelpIcon(dm_label,
            "Model id selected by default. Format depends on the provider — see the example line below."
        ).pack(side="left")
        self.default_model_var = tk.StringVar(
            value=self.current.get("default_model", "anthropic/claude-sonnet-4"))
        ttk.Entry(f, textvariable=self.default_model_var).pack(fill="x", pady=(2, 10))
        ttk.Label(f, text="For OpenRouter use the full model id (e.g. anthropic/claude-sonnet-4). "
                  "For Ollama use the local model name (e.g. qwen2.5:32b). "
                  "For Anthropic Direct use the model string (e.g. claude-sonnet-4-6).",
                  foreground="grey", wraplength=540).pack(anchor="w")

    # ── ACTIONS ─────────────────────────────────────────────────────
    def _save(self):
        new = self.current.copy()
        new.update({
            "openrouter_api_key": self.openrouter_var.get().strip(),
            "anthropic_api_key": self.anthropic_var.get().strip(),
            "kie_api_key": self.kie_var.get().strip(),
            "elevenlabs_api_key": self.elevenlabs_var.get().strip(),
            "ollama_host": self.ollama_host_var.get().strip() or "http://localhost:11434",
            "default_provider": self.default_provider_var.get().strip() or "openrouter",
            "default_model": self.default_model_var.get().strip() or "anthropic/claude-sonnet-4",
        })
        settings.save_settings(new)
        self.destroy()

    def _set_status(self, msg, ok=None):
        prefix = "" if ok is None else ("✅ " if ok else "❌ ")
        self.status_var.set(prefix + msg)

    def _save_single_key(self, settings_key: str, value: str, label: str):
        """Persist one API key to ~/.talkshow_generator/config.json immediately."""
        settings.set_setting(settings_key, value.strip())
        self._set_status(f"{label} key saved to disk.", ok=True)

    def _test_openrouter(self):
        # Use whichever text model is currently active (set from the per-tab
        # ModelPickers and persisted to settings).
        slug = settings.load_settings().get("openrouter_test_model",
            cfg.DEFAULT_CONFIG["openrouter_test_model"])
        self._set_status(f"🔄 Testing OpenRouter with model {slug}…")
        def worker():
            client = OpenRouterClient(self.openrouter_var.get(), slug)
            ok, msg = client.test_connection()
            self.after(0, lambda: self._set_status(msg, ok))
        threading.Thread(target=worker, daemon=True).start()

    def _test_anthropic(self):
        self._set_status("🔄 Testing Anthropic...")
        def worker():
            client = AnthropicClient(self.anthropic_var.get(), "claude-haiku-4-5-20251001")
            ok, msg = client.test_connection()
            self.after(0, lambda: self._set_status(msg, ok))
        threading.Thread(target=worker, daemon=True).start()

    def _test_kie(self):
        self._set_status("🔄 Testing kie.ai...")
        def worker():
            client = KieClient(self.kie_var.get())
            ok, msg = client.test_connection()
            self.after(0, lambda: self._set_status(msg, ok))
        threading.Thread(target=worker, daemon=True).start()

    def _test_elevenlabs(self):
        self._set_status("🔄 Testing ElevenLabs...")
        def worker():
            client = ElevenLabsClient(self.elevenlabs_var.get())
            ok, msg = client.test_connection()
            self.after(0, lambda: self._set_status(msg, ok))
        threading.Thread(target=worker, daemon=True).start()

    def _test_ollama(self):
        def worker():
            client = OllamaClient(self.ollama_host_var.get(), "")
            ok, msg = client.test_connection()
            self.after(0, lambda: messagebox.showinfo(
                "🦙 Ollama", f"{'✅ OK' if ok else '❌ Failed'}\n\n{msg}", parent=self))
        threading.Thread(target=worker, daemon=True).start()

    def _refresh_ollama_models(self):
        def worker():
            client = OllamaClient(self.ollama_host_var.get(), "")
            models = client.list_models()
            text = "\n".join(models) if models else "(none found)"
            def update():
                self.ollama_models_text.config(state="normal")
                self.ollama_models_text.delete("1.0", "end")
                self.ollama_models_text.insert("1.0", text)
                self.ollama_models_text.config(state="disabled")
            self.after(0, update)
        threading.Thread(target=worker, daemon=True).start()
