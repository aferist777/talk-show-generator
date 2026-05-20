"""
Unified LLM client interface for OpenRouter / Ollama / Anthropic Direct.

All clients expose the same .complete(system, user, max_tokens) -> str method,
and a .test_connection() -> (bool, str) method for the settings dialog.
"""
import base64
import json
import re
import time
import urllib.request
import urllib.error
from abc import ABC, abstractmethod

from debug_log import DEBUG_LOG
import pricing


def _usage_extra(model: str, in_tokens: int, out_tokens: int) -> dict:
    """Build the {tokens + cost} block that we attach to every successful log_response."""
    cost = pricing.estimate_cost(model, in_tokens, out_tokens)
    return {
        "in_tokens": in_tokens,
        "out_tokens": out_tokens,
        "total_tokens": in_tokens + out_tokens,
        "cost_usd": round(cost, 6),
    }


# ── Image response extraction helpers ─────────────────────────────────
# MIME subtype can be e.g. 'png', 'jpeg', 'svg+xml', 'vnd.adobe.photoshop',
# 'x-icon' — allow word chars, '+', '.', '-' in the subtype.
_DATA_URL_RE = re.compile(r"data:image/([\w.+-]+);base64,(.+)", re.DOTALL)


def _normalize_mime_to_ext(mime_subtype: str) -> str:
    """Convert e.g. 'svg+xml' → 'svg', 'jpeg' → 'jpg', 'x-png' → 'png'."""
    s = (mime_subtype or "").lower()
    if "svg" in s:
        return "svg"
    if s in ("jpeg", "x-jpeg"):
        return "jpg"
    if s.startswith("x-"):
        return s[2:]
    # Strip any '+xml' / '+...' suffix
    return s.split("+", 1)[0]


def _bytes_from_url_or_data(url: str) -> tuple:
    """Decode a base64 data URL or fetch a plain http(s) URL. Returns
    (bytes, ext) or (None, None) if the string isn't recognised."""
    if not isinstance(url, str):
        return None, None
    url = url.strip()
    if not url:
        return None, None
    m = _DATA_URL_RE.match(url)
    if m:
        try:
            return base64.b64decode(m.group(2)), _normalize_mime_to_ext(m.group(1))
        except (ValueError, binascii_error()):
            return None, None
    if url.startswith(("http://", "https://")):
        try:
            with urllib.request.urlopen(url, timeout=60) as resp:
                blob = resp.read()
                ct = resp.headers.get("Content-Type", "")
        except urllib.error.URLError:
            return None, None
        ext = "png"
        if "jpeg" in ct or "jpg" in ct:
            ext = "jpg"
        elif "svg" in ct:
            ext = "svg"
        elif "webp" in ct:
            ext = "webp"
        elif "gif" in ct:
            ext = "gif"
        return blob, ext
    return None, None


def binascii_error():
    """Late import — binascii.Error not always reachable directly."""
    import binascii
    return binascii.Error


def _reference_image_to_png_b64(image_bytes: bytes) -> str:
    """Normalise arbitrary image bytes (SVG / PNG / JPEG / WebP / …) to a
    base64-encoded PNG string suitable for embedding in a data URL for the
    reference-image slot of a multimodal request. Raises on failure."""
    head = image_bytes[:200].lstrip()
    if head.startswith(b"<svg") or head.startswith(b"<?xml"):
        from ui.widgets import _svg_bytes_to_png
        image_bytes = _svg_bytes_to_png(image_bytes, target_width=1024)
    else:
        from io import BytesIO
        from PIL import Image
        img = Image.open(BytesIO(image_bytes))
        # Re-encode through PIL → guaranteed valid PNG, strips weird metadata.
        if img.mode not in ("RGB", "RGBA"):
            img = img.convert("RGBA")
        buf = BytesIO()
        img.save(buf, format="PNG")
        image_bytes = buf.getvalue()
    return base64.b64encode(image_bytes).decode("ascii")


def _extract_image_from_response(data: dict) -> tuple:
    """Try several known OpenRouter image-response shapes. Returns (bytes, ext).
    Raises RuntimeError if no shape matches.
    """
    # Shape A: choices[0].message.images = [{type, image_url: {url}}, ...]
    try:
        images = data["choices"][0]["message"].get("images", [])
        for img in images or []:
            url = ""
            if isinstance(img, dict):
                iu = img.get("image_url")
                if isinstance(iu, dict):
                    url = iu.get("url", "")
                elif isinstance(iu, str):
                    url = iu
                else:
                    url = img.get("url", "") or img.get("b64_json", "")
            elif isinstance(img, str):
                url = img
            blob, ext = _bytes_from_url_or_data(url)
            if blob:
                return blob, ext
    except (KeyError, IndexError, TypeError):
        pass

    # Shape B: choices[0].message.content as data URL, raw SVG, or plain URL
    try:
        content = data["choices"][0]["message"]["content"]
        if isinstance(content, str):
            stripped = content.lstrip()
            if stripped.startswith("<svg") or stripped.startswith("<?xml"):
                return stripped.encode("utf-8"), "svg"
            blob, ext = _bytes_from_url_or_data(stripped)
            if blob:
                return blob, ext
        elif isinstance(content, list):
            for part in content:
                if isinstance(part, dict):
                    url = (part.get("image_url") or {}).get("url") or part.get("url") or ""
                    blob, ext = _bytes_from_url_or_data(url)
                    if blob:
                        return blob, ext
    except (KeyError, IndexError, TypeError):
        pass

    # Shape C: OpenAI-images-style: data[0].url or data[0].b64_json
    try:
        d0 = data["data"][0]
        if d0.get("b64_json"):
            return base64.b64decode(d0["b64_json"]), "png"
        url = d0.get("url", "")
        blob, ext = _bytes_from_url_or_data(url)
        if blob:
            return blob, ext
    except (KeyError, IndexError, TypeError):
        pass

    raise RuntimeError(
        f"Could not extract image from response. Full body:\n"
        f"{json.dumps(data, ensure_ascii=False)[:16000]}")


class LLMClient(ABC):
    @abstractmethod
    def complete(self, system: str, user: str, max_tokens: int = 4000, temperature: float = 0.85) -> str:
        """Send a chat completion request and return the assistant's text."""

    @abstractmethod
    def test_connection(self) -> tuple:
        """Return (ok: bool, message: str). Tries a minimal ping."""


# ─────────────────────────────────────────────────────────────────────
# OpenRouter
# ─────────────────────────────────────────────────────────────────────
class OpenRouterClient(LLMClient):
    BASE_URL = "https://openrouter.ai/api/v1/chat/completions"

    def __init__(self, api_key: str, model: str):
        self.api_key = api_key.strip()
        self.model = model

    def complete(self, system: str, user: str, max_tokens: int = 4000, temperature: float = 0.85) -> str:
        if not self.api_key:
            raise ValueError("OpenRouter API key is not set. Open Settings to add it.")

        DEBUG_LOG.log_request("OpenRouter.complete",
            model=self.model, system=system, user=user,
            url=self.BASE_URL, method="POST",
            extra={"max_tokens": max_tokens, "temperature": temperature})
        start = time.time()

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        req = urllib.request.Request(
            self.BASE_URL,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
                "HTTP-Referer": "https://localhost/talkshow-generator",
                "X-Title": "TalkShow Generator",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=180) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="ignore")
            DEBUG_LOG.log_response("OpenRouter.complete",
                status=f"HTTP {e.code}", duration=time.time() - start,
                error=body[:16000])
            raise RuntimeError(f"OpenRouter HTTP {e.code}: {body[:2000]}") from e
        except urllib.error.URLError as e:
            DEBUG_LOG.log_response("OpenRouter.complete",
                status="URLError", duration=time.time() - start, error=str(e.reason))
            raise RuntimeError(f"OpenRouter connection error: {e.reason}") from e

        try:
            result = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError) as e:
            DEBUG_LOG.log_response("OpenRouter.complete",
                status="bad_shape", duration=time.time() - start,
                error=f"Unexpected response: {json.dumps(data)[:500]}")
            raise RuntimeError(f"Unexpected OpenRouter response: {json.dumps(data)[:500]}") from e

        usage = data.get("usage") or {}
        in_tok = int(usage.get("prompt_tokens", 0) or 0)
        out_tok = int(usage.get("completion_tokens", 0) or 0)
        DEBUG_LOG.log_response("OpenRouter.complete",
            status="200", duration=time.time() - start,
            response=result[:2000],
            extra=_usage_extra(self.model, in_tok, out_tok))
        return result

    def test_connection(self) -> tuple:
        if not self.api_key:
            return (False, "No API key set.")
        try:
            txt = self.complete("You are a test.", "Reply with the single word: pong",
                                max_tokens=10, temperature=0)
            return (True, f"OK. Response: {txt.strip()[:60]}")
        except Exception as e:
            return (False, str(e)[:300])

    def generate_image(self, prompt: str, model: str = "",
                        max_tokens: int = 2048,
                        modalities: list = None,
                        aspect_ratio: str = "",
                        reference_image_bytes: bytes = None) -> tuple:
        """Send a chat-completions request to an image-capable OpenRouter
        model and return (image_bytes, ext).

        `ext` ∈ {'png','jpg','jpeg','svg','webp','gif'}.

        modalities defaults to ['image']. Without explicitly requesting image
        output, /chat/completions returns a text reply (a description of what
        the model 'would' generate) — not an actual image. ['image'] forces
        OpenRouter to route to an image-capable endpoint for the chosen model.
        For multimodal chat models (GPT-5.4 Image) you can pass
        ['image','text'] to get both back, but for pure t2i (Recraft, Flux)
        that yields 404. ['image'] alone works for every image model.
        """
        if not self.api_key:
            raise ValueError("OpenRouter API key is not set. Open Settings to add it.")
        use_model = (model or self.model).strip()
        if not use_model:
            raise ValueError("No image model specified.")

        if not modalities:
            modalities = ["image"]

        # Normalise reference image(s) to a list. Accept None / bytes / list of bytes.
        if reference_image_bytes is None:
            ref_list = []
        elif isinstance(reference_image_bytes, (bytes, bytearray)):
            ref_list = [bytes(reference_image_bytes)]
        elif isinstance(reference_image_bytes, list):
            ref_list = [b for b in reference_image_bytes if b]
        else:
            ref_list = []

        # Compose user-message content. With reference image(s) we send
        # multi-part content (text + N × image_url); otherwise a plain string.
        user_content = prompt
        if ref_list:
            parts = [{"type": "text", "text": prompt}]
            for ref in ref_list:
                try:
                    b64 = _reference_image_to_png_b64(ref)
                    parts.append({"type": "image_url",
                                   "image_url": {"url": f"data:image/png;base64,{b64}"}})
                except Exception as e:
                    DEBUG_LOG.log_info("OpenRouter.generate_image",
                        f"One reference image discarded: {e}")
            if len(parts) > 1:
                user_content = parts

        DEBUG_LOG.log_request("OpenRouter.generate_image",
            model=use_model, user=prompt, url=self.BASE_URL, method="POST",
            extra={"max_tokens": max_tokens, "modalities": modalities,
                    "aspect_ratio": aspect_ratio or "(default)",
                    "has_reference_image": bool(reference_image_bytes)})
        start = time.time()

        payload = {
            "model": use_model,
            "messages": [{"role": "user", "content": user_content}],
            "max_tokens": max_tokens,
            "modalities": modalities,
        }
        if aspect_ratio:
            payload["image_config"] = {"aspect_ratio": aspect_ratio}
        req = urllib.request.Request(
            self.BASE_URL,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
                "HTTP-Referer": "https://localhost/talkshow-generator",
                "X-Title": "TalkShow Generator",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=300) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="ignore")
            DEBUG_LOG.log_response("OpenRouter.generate_image",
                status=f"HTTP {e.code}", duration=time.time() - start,
                error=body[:16000])
            raise RuntimeError(f"OpenRouter HTTP {e.code}: {body[:2000]}") from e
        except urllib.error.URLError as e:
            DEBUG_LOG.log_response("OpenRouter.generate_image",
                status="URLError", duration=time.time() - start,
                error=str(e.reason))
            raise RuntimeError(f"OpenRouter connection error: {e.reason}") from e

        try:
            img_bytes, ext = _extract_image_from_response(data)
        except RuntimeError as e:
            DEBUG_LOG.log_response("OpenRouter.generate_image",
                status="extract_failed", duration=time.time() - start,
                error=str(e)[:16000])
            raise

        usage = data.get("usage") or {}
        in_tok = int(usage.get("prompt_tokens", 0) or 0)
        out_tok = int(usage.get("completion_tokens", 0) or 0)
        DEBUG_LOG.log_response("OpenRouter.generate_image",
            status="200", duration=time.time() - start,
            response=f"{len(img_bytes)} bytes .{ext}",
            extra={**_usage_extra(use_model, in_tok, out_tok),
                   "bytes": len(img_bytes), "ext": ext})
        return img_bytes, ext


# ─────────────────────────────────────────────────────────────────────
# Ollama (local)
# ─────────────────────────────────────────────────────────────────────
class OllamaClient(LLMClient):
    def __init__(self, host: str, model: str):
        self.host = host.rstrip("/")
        self.model = model

    def complete(self, system: str, user: str, max_tokens: int = 4000, temperature: float = 0.85) -> str:
        url = f"{self.host}/api/chat"
        DEBUG_LOG.log_request("Ollama.complete",
            model=self.model, system=system, user=user, url=url, method="POST",
            extra={"max_tokens": max_tokens, "temperature": temperature})
        start = time.time()

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            },
        }
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=600) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="ignore")
            DEBUG_LOG.log_response("Ollama.complete",
                status=f"HTTP {e.code}", duration=time.time() - start, error=body[:16000])
            raise RuntimeError(f"Ollama HTTP {e.code}: {body[:2000]}") from e
        except urllib.error.URLError as e:
            DEBUG_LOG.log_response("Ollama.complete",
                status="URLError", duration=time.time() - start, error=str(e.reason))
            raise RuntimeError(
                f"Ollama connection error: {e.reason}. "
                f"Is Ollama running at {self.host}?"
            ) from e

        try:
            result = data["message"]["content"]
        except KeyError as e:
            DEBUG_LOG.log_response("Ollama.complete",
                status="bad_shape", duration=time.time() - start,
                error=f"Unexpected response: {json.dumps(data)[:500]}")
            raise RuntimeError(f"Unexpected Ollama response: {json.dumps(data)[:500]}") from e

        in_tok = int(data.get("prompt_eval_count", 0) or 0)
        out_tok = int(data.get("eval_count", 0) or 0)
        DEBUG_LOG.log_response("Ollama.complete",
            status="200", duration=time.time() - start, response=result[:2000],
            extra=_usage_extra(self.model, in_tok, out_tok))
        return result

    def test_connection(self) -> tuple:
        url = f"{self.host}/api/tags"
        try:
            with urllib.request.urlopen(url, timeout=5) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            models = [m["name"] for m in data.get("models", [])]
            if not models:
                return (True, "Ollama running, but no models installed.")
            return (True, f"OK. Models: {', '.join(models[:5])}")
        except Exception as e:
            return (False, f"Cannot reach Ollama: {e}"[:300])

    def list_models(self) -> list:
        """List locally available Ollama models."""
        url = f"{self.host}/api/tags"
        try:
            with urllib.request.urlopen(url, timeout=5) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            return [m["name"] for m in data.get("models", [])]
        except Exception:
            return []


# ─────────────────────────────────────────────────────────────────────
# Anthropic Direct
# ─────────────────────────────────────────────────────────────────────
class AnthropicClient(LLMClient):
    BASE_URL = "https://api.anthropic.com/v1/messages"
    API_VERSION = "2023-06-01"

    def __init__(self, api_key: str, model: str):
        self.api_key = api_key.strip()
        self.model = model

    def complete(self, system: str, user: str, max_tokens: int = 4000, temperature: float = 0.85) -> str:
        if not self.api_key:
            raise ValueError("Anthropic API key is not set. Open Settings to add it.")

        DEBUG_LOG.log_request("Anthropic.complete",
            model=self.model, system=system, user=user,
            url=self.BASE_URL, method="POST",
            extra={"max_tokens": max_tokens, "temperature": temperature})
        start = time.time()

        payload = {
            "model": self.model,
            "system": system,
            "messages": [{"role": "user", "content": user}],
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        req = urllib.request.Request(
            self.BASE_URL,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "x-api-key": self.api_key,
                "anthropic-version": self.API_VERSION,
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=180) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="ignore")
            DEBUG_LOG.log_response("Anthropic.complete",
                status=f"HTTP {e.code}", duration=time.time() - start, error=body[:16000])
            raise RuntimeError(f"Anthropic HTTP {e.code}: {body[:2000]}") from e
        except urllib.error.URLError as e:
            DEBUG_LOG.log_response("Anthropic.complete",
                status="URLError", duration=time.time() - start, error=str(e.reason))
            raise RuntimeError(f"Anthropic connection error: {e.reason}") from e

        try:
            result = data["content"][0]["text"]
        except (KeyError, IndexError) as e:
            DEBUG_LOG.log_response("Anthropic.complete",
                status="bad_shape", duration=time.time() - start,
                error=f"Unexpected response: {json.dumps(data)[:500]}")
            raise RuntimeError(f"Unexpected Anthropic response: {json.dumps(data)[:500]}") from e

        usage = data.get("usage") or {}
        in_tok = int(usage.get("input_tokens", 0) or 0)
        out_tok = int(usage.get("output_tokens", 0) or 0)
        DEBUG_LOG.log_response("Anthropic.complete",
            status="200", duration=time.time() - start, response=result[:2000],
            extra=_usage_extra(self.model, in_tok, out_tok))
        return result

    def test_connection(self) -> tuple:
        if not self.api_key:
            return (False, "No API key set.")
        try:
            txt = self.complete("You are a test.", "Reply with: pong", max_tokens=10, temperature=0)
            return (True, f"OK. Response: {txt.strip()[:60]}")
        except Exception as e:
            return (False, str(e)[:300])


# ─────────────────────────────────────────────────────────────────────
# kie.ai (only connection test for now — visuals are out of scope for v1)
# ─────────────────────────────────────────────────────────────────────
class KieClient:
    """
    Stub client for kie.ai. v1 only validates that the API key is set
    and the host is reachable. Visual generation is reserved for v2.
    """
    BASE_URL = "https://api.kie.ai/api/v1"

    def __init__(self, api_key: str):
        self.api_key = api_key.strip()

    def test_connection(self) -> tuple:
        if not self.api_key:
            return (False, "No API key set.")
        # Lightweight check: hit a known endpoint (e.g. account info)
        url = f"{self.BASE_URL}/account"
        req = urllib.request.Request(
            url,
            headers={"Authorization": f"Bearer {self.api_key}"},
            method="GET",
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                resp.read()
            return (True, "Key accepted by kie.ai.")
        except urllib.error.HTTPError as e:
            if e.code == 401:
                return (False, "401 Unauthorized — check the API key.")
            # Some endpoints may not exist; if it's not 401, the key reached the server
            return (True, f"Reachable (HTTP {e.code}). Key may still be valid.")
        except urllib.error.URLError as e:
            return (False, f"Cannot reach kie.ai: {e.reason}")


# ─────────────────────────────────────────────────────────────────────
# ElevenLabs (TTS + crowd SFX)
# ─────────────────────────────────────────────────────────────────────
class ElevenLabsClient:
    """
    ElevenLabs client. Currently only test_connection() is wired; tts() and sfx()
    are placeholders that we'll connect in the Voices generation pass.
    """
    BASE_URL = "https://api.elevenlabs.io/v1"

    def __init__(self, api_key: str):
        self.api_key = api_key.strip()

    def test_connection(self) -> tuple:
        if not self.api_key:
            return (False, "No API key set.")
        # We hit /v1/voices rather than /v1/user. /v1/user requires the
        # 'user_read' permission, which ElevenLabs's restricted-scope keys
        # (the default when you create a key with TTS-only permissions)
        # do NOT have — those return 401 even when the key is perfectly
        # valid for TTS. /v1/voices requires 'voices_read', which is the
        # natural scope for any TTS-grade key and the endpoint we'll be
        # using anyway in the Voices generation pass.
        url = f"{self.BASE_URL}/voices"
        req = urllib.request.Request(
            url,
            headers={"xi-api-key": self.api_key, "Accept": "application/json"},
            method="GET",
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            voices = data.get("voices") or []
            return (True, f"OK. {len(voices)} voice(s) available.")
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="ignore")
            if e.code == 401:
                return (False,
                    "401 Unauthorized — the API key is invalid or doesn't have "
                    "the 'voices_read' permission. Create a key in the "
                    "ElevenLabs dashboard with 'Text-to-Speech' / 'Voices' "
                    f"access. Detail: {body[:200]}")
            return (False, f"HTTP {e.code}: {body[:200]}")
        except urllib.error.URLError as e:
            return (False, f"Cannot reach ElevenLabs: {e.reason}")

    def list_voices(self) -> list:
        """Return the available voices as a list of dicts as returned by
        the ElevenLabs API. Empty list on failure."""
        if not self.api_key:
            return []
        url = f"{self.BASE_URL}/voices"
        req = urllib.request.Request(
            url,
            headers={"xi-api-key": self.api_key, "Accept": "application/json"},
            method="GET",
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            return data.get("voices") or []
        except (urllib.error.HTTPError, urllib.error.URLError, json.JSONDecodeError):
            return []

    def tts(self, voice_id: str, text: str,
             stability: float = 0.5, style: float = 0.0,
             similarity_boost: float = 0.75, speed: float = 1.0,
             model_id: str = "eleven_multilingual_v2") -> bytes:
        """Synthesise speech. Returns raw MP3 bytes. Raises RuntimeError on failure."""
        if not self.api_key:
            raise RuntimeError("ElevenLabs API key is not set.")
        url = f"{self.BASE_URL}/text-to-speech/{voice_id}"
        payload = {
            "text": text,
            "model_id": model_id,
            "voice_settings": {
                "stability": float(stability),
                "similarity_boost": float(similarity_boost),
                "style": float(style),
                "speed": float(speed),
                "use_speaker_boost": True,
            },
        }
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "xi-api-key": self.api_key,
                "Accept": "audio/mpeg",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                return resp.read()
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="ignore")
            raise RuntimeError(f"ElevenLabs TTS HTTP {e.code}: {body[:500]}") from e
        except urllib.error.URLError as e:
            raise RuntimeError(f"Cannot reach ElevenLabs: {e.reason}") from e


# ─────────────────────────────────────────────────────────────────────
# Factory
# ─────────────────────────────────────────────────────────────────────
def make_client(provider: str, settings: dict, model: str) -> LLMClient:
    """Create the right client given the provider name."""
    if provider == "openrouter":
        return OpenRouterClient(settings.get("openrouter_api_key", ""), model)
    if provider == "ollama":
        return OllamaClient(settings.get("ollama_host", "http://localhost:11434"), model)
    if provider == "anthropic":
        return AnthropicClient(settings.get("anthropic_api_key", ""), model)
    raise ValueError(f"Unknown provider: {provider}")
