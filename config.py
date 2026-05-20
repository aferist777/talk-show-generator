"""
Application paths, constants, and default values.
"""
import os
from pathlib import Path

APP_NAME = "TalkShow Generator"
APP_VERSION = "0.1.0"

# Storage locations
HOME = Path.home()
APP_DIR = HOME / ".talkshow_generator"
CONFIG_FILE = APP_DIR / "config.json"
PRESETS_DIR = APP_DIR / "presets"
PROJECTS_DIR = APP_DIR / "projects"
VOICE_CACHE_DIR = APP_DIR / "voice_cache"
VOICE_CACHE_DIR.mkdir(exist_ok=True)

# Short neutral phrase used to generate a demo clip for a custom voice
# (one ElevenLabs voice library entries don't ship a preview_url for —
# user-provided voice_ids in particular). Generated once and cached.
CUSTOM_VOICE_DEMO_TEXT = (
    "Hello, this is a quick demo of my voice for the TalkShow Generator."
)

# Public ElevenLabs voice library — opened in the browser when the user
# clicks the link button on the Voices tab.
ELEVENLABS_VOICE_LIBRARY_URL = "https://elevenlabs.io/app/voice-library"

# Local copy of OpenRouter model documentation (shipped with the app).
MODEL_DOCS_DIR = Path(__file__).resolve().parent / "model_docs"

# Ensure storage exists
APP_DIR.mkdir(exist_ok=True)
PRESETS_DIR.mkdir(exist_ok=True)
PROJECTS_DIR.mkdir(exist_ok=True)


def model_doc_path(slug: str, kind: str = "text") -> Path:
    """Local file path for a model's cached markdown documentation.

    kind ∈ {'text', 'image'} — docs are organized by category under
    model_docs/text/ and model_docs/image/.
    """
    filename = slug.replace("/", "_").replace(":", "_") + ".md"
    return MODEL_DOCS_DIR / kind / filename

# Defaults
DEFAULT_CONFIG = {
    "openrouter_api_key": "",
    "anthropic_api_key": "",
    "kie_api_key": "",
    "elevenlabs_api_key": "",
    "ollama_host": "http://localhost:11434",

    # ── Per-kind provider/model selection (no more global Provider) ──
    "text_provider":               "openrouter",
    "text_model_openrouter":       "~anthropic/claude-haiku-latest",
    "text_model_anthropic":        "claude-haiku-4-5-20251001",
    "text_model_ollama":           "qwen2.5:32b",

    "image_provider":              "openrouter",
    "image_model_openrouter":      "recraft/recraft-v4.1-vector",
    "image_model_kie":             "",   # coming soon

    "last_save_dir": str(HOME / "Documents"),

    # Path of the project that was open when the app last closed. Drives the
    # "📁 Resume project?" dialog on startup. Empty = no resume prompt.
    "last_project_path": "",

    # Voices cache — list of {voice_id, name, gender, preview_url, source}.
    # Populated on first Voices-tab visit from /v1/voices (premade category) +
    # user-added custom voices. Persists across sessions; no manual refresh.
    "voices_cache": [],
}

# Provider lists used by ModelPicker dropdowns
TEXT_PROVIDERS = ["openrouter", "anthropic", "ollama"]
IMAGE_PROVIDERS = ["openrouter", "kie.ai"]

# Display labels for providers (shown in dropdown).
TEXT_PROVIDER_LABELS = {
    "openrouter": "openrouter",
    "anthropic":  "anthropic (direct)",
    "ollama":     "ollama (local)",
}
IMAGE_PROVIDER_LABELS = {
    "openrouter": "openrouter",
    "kie.ai":     "kie.ai (coming soon)",
}


def get_text_catalog(provider: str) -> list:
    """Returns a list of {slug, label, price_label} dicts for a text provider.
    For 'ollama' returns []  — the widget fetches the live installed list."""
    if provider == "openrouter":
        out = []
        for m in OPENROUTER_TEST_MODELS:
            if m["price_in"] == 0.0 and m["price_out"] == 0.0:
                price = "FREE"
            else:
                price = f"${m['price_in']:.2f} / ${m['price_out']:.2f} per 1M"
            out.append({"slug": m["slug"],
                        "label": m["label"],
                        "price_label": price})
        return out
    if provider == "anthropic":
        return [{"slug": s, "label": s, "price_label": "Anthropic Direct"}
                for s in ANTHROPIC_MODELS]
    # ollama handled in widget (dynamic)
    return []


def get_image_catalog(provider: str) -> list:
    """Returns a list of {slug, label, capability, price_label} dicts."""
    if provider == "openrouter":
        return [{"slug": m["slug"],
                 "label": m["label"],
                 "capability": m["capability"],
                 "price_label": m["price_label"]}
                for m in OPENROUTER_IMAGE_MODELS]
    if provider == "kie.ai":
        return []  # coming soon
    return []

# Curated OpenRouter test models — ordered from most capable to lightest.
# Used by the Settings → OpenRouter dropdown and the 🧪 Test button.
OPENROUTER_TEST_MODELS = [
    {
        "slug": "anthropic/claude-opus-4.7-fast",
        "label": "Claude Opus 4.7 (fast)",
        "price_in": 30.0,
        "price_out": 150.0,
        "description": (
            "Anthropic flagship — fast-mode variant of Opus 4.7 with identical "
            "capabilities at higher output speed. Best for: complex reasoning, "
            "long-form scriptwriting, sophisticated structured outputs. "
            "Premium pricing — overkill for testing."
        ),
    },
    {
        "slug": "~anthropic/claude-haiku-latest",
        "label": "Claude Haiku (latest)",
        "price_in": 1.0,
        "price_out": 5.0,
        "description": (
            "Auto-pointer to the latest Claude Haiku. Anthropic's fast/small "
            "model. Best for: quick responses, cost-sensitive workflows, "
            "high-volume requests. Solid default for connection tests."
        ),
    },
    {
        "slug": "x-ai/grok-4.3",
        "label": "Grok 4.3",
        "price_in": 1.25,
        "price_out": 2.50,
        "description": (
            "xAI frontier model with 1M-token context. Best for: agentic "
            "workflows, instruction-following, applications requiring high "
            "factual accuracy."
        ),
    },
    {
        "slug": "openrouter/owl-alpha",
        "label": "Owl Alpha",
        "price_in": 0.0,
        "price_out": 0.0,
        "description": (
            "OpenRouter alpha model with 1M-token context window. Free during "
            "alpha. Best for: experimenting with long-context workflows "
            "without paying."
        ),
    },
    {
        "slug": "google/gemini-3.1-flash-lite",
        "label": "Gemini 3.1 Flash Lite",
        "price_in": 0.25,
        "price_out": 1.50,
        "description": (
            "Google's lightweight fast model. Best for: low-latency, "
            "high-volume workloads, simple data extraction, cost-efficient "
            "lightweight agentic workflows."
        ),
    },
    {
        "slug": "perceptron/perceptron-mk1",
        "label": "Perceptron MK1",
        "price_in": 0.15,
        "price_out": 1.50,
        "description": (
            "Vision-language model. Best for: video understanding, image "
            "grounding, OCR, object detection, embodied reasoning. Not "
            "ideal for text-only scriptwriting."
        ),
    },
    {
        "slug": "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free",
        "label": "Nemotron 3 Nano Omni 30B",
        "price_in": 0.0,
        "price_out": 0.0,
        "description": (
            "Open 30B-A3B multimodal model from NVIDIA. Designed as a "
            "perception/context sub-agent in enterprise agent systems. Free."
        ),
    },
    {
        "slug": "baidu/cobuddy:free",
        "label": "Baidu CoBuddy",
        "price_in": 0.0,
        "price_out": 0.0,
        "description": (
            "Baidu code-generation model optimized for coding tasks and AI "
            "Agent workflows with native tool calling and reasoning support. "
            "Free."
        ),
    },
]

# Curated OpenRouter image-generation models — ordered most-capable → lightest.
# capability ∈ {"t2i", "i2i", "t2i+i2i"}.
# price_label is shown next to the dropdown entry (each model prices differently:
# per-token vs per-image vs per-megapixel — so a free-form label is friendlier
# than two columns).
OPENROUTER_IMAGE_MODELS = [
    {
        "slug": "openai/gpt-5.4-image-2",
        "label": "GPT-5.4 Image 2",
        "capability": "t2i+i2i",
        "price_label": "$8 / $15 per 1M tok",
        "description": (
            "OpenAI flagship multimodal — GPT-5.4 reasoning + GPT Image 2 generation. "
            "Best for: prompts that need reasoning before generating (complex scene "
            "composition, dense product mock-ups, edits requiring instruction following)."
        ),
    },
    {
        "slug": "google/gemini-3.1-flash-image-preview",
        "label": "Nano Banana 2 (Gemini 3.1 Flash Image)",
        "capability": "t2i+i2i",
        "price_label": "$0.50 / $3 per 1M tok",
        "description": (
            "Google's Pro-level visual quality at Flash speed. Strong on iterative "
            "edits (i2i) and rapid t2i. Cheapest of the t2i+i2i tier — good default "
            "for character render iteration and b-roll experimentation."
        ),
    },
    {
        "slug": "recraft/recraft-v4.1-vector",
        "label": "Recraft V4.1 Vector",
        "capability": "t2i+i2i",
        "price_label": "$0.08 / image (SVG)",
        "description": (
            "Vector output (SVG) — scales cleanly to broadcast resolution. Best for: "
            "show logos, lower-third backgrounds, brand mark assets, icons. "
            "Not photorealistic; ~13s per image."
        ),
    },
    {
        "slug": "black-forest-labs/flux.2-klein-4b",
        "label": "FLUX.2 Klein 4B",
        "capability": "t2i",
        "price_label": "$0.014 / 1st MP, $0.001 / extra",
        "description": (
            "Fastest + cheapest in FLUX.2 family. Text-to-image only. Best for: "
            "high-throughput b-roll generation, atmospheric studio shots, "
            "background plates. No image-to-image."
        ),
    },
]

# Provider list
PROVIDERS = ["openrouter", "ollama", "anthropic"]

# Niche options
NICHE_OPTIONS = [
    "Weight loss",
    "Memory & cognition",
    "Joint pain",
    "Vision",
    "Anxiety & sleep",
    "Hair loss",
    "Skin aging",
    "Erectile dysfunction",
    "Diabetes",
    "Hypertension",
    "Custom...",
]

# Scientific anchor suggestions
ANCHOR_SUGGESTIONS = [
    "GLP-1 (glucagon-like peptide-1)",
    "BDNF (brain-derived neurotrophic factor)",
    "NAD+ (nicotinamide adenine dinucleotide)",
    "Telomerase",
    "AMPK (AMP-activated protein kinase)",
    "Collagen synthesis",
    "Mitochondrial uncoupling (UCP1)",
    "Autophagy",
    "Sirtuins (SIRT1)",
    "Custom...",
]

# Tone presets
TONE_OPTIONS = [
    "US daytime TV (Oprah / Dr. Phil style)",
    "UK morning show (This Morning style)",
    "Russian federal channel (Malakhov style)",
    "Australian breakfast TV (Sunrise style)",
    "Generic international cable",
]

# Language options
LANGUAGE_OPTIONS = ["English", "Russian"]

# Duration options
DURATION_OPTIONS = [15, 25, 30, 45, 60]

# Antagonist options
ANTAGONIST_TYPES = [
    "Pharmaceutical industry representative",
    "Government health regulator",
    "Big food industry lobbyist",
    "Cosmetics industry executive",
    "Medical association spokesperson",
]

ANTAGONIST_ARCS = [
    "Smooth → aggressive → walkout",
    "Aggressive from the start → defeated",
    "Patronizing → losing composure → defeated",
    "Calm and dismissive → flustered → grudging admission",
]

# Bonus types
BONUS_TYPES = [
    "Buy 2 get 1 free",
    "Free shipping nationwide",
    "Bonus ebook with recipes",
    "Bonus consultation call",
    "Free trial size with first order",
    "None",
]

# Currency options
CURRENCY_OPTIONS = ["$", "€", "£", "₽", "¥"]

# OpenRouter models for the dropdown
OPENROUTER_MODELS = [
    "anthropic/claude-opus-4",
    "anthropic/claude-sonnet-4",
    "anthropic/claude-haiku-4",
    "openai/gpt-5",
    "openai/gpt-5-mini",
    "google/gemini-2.5-pro",
    "google/gemini-2.5-flash",
    "deepseek/deepseek-v3.1",
    "qwen/qwen-3-72b",
    "meta-llama/llama-4-70b",
    "x-ai/grok-4",
    "mistralai/mistral-large",
]

# Anthropic direct models
ANTHROPIC_MODELS = [
    "claude-opus-4-7",
    "claude-opus-4-6",
    "claude-sonnet-4-6",
    "claude-haiku-4-5-20251001",
]

# ── Step 2 (Studio shoot) presets ────────────────────────────────────
ERA_PRESETS = [
    "90s daytime VHS",
    "2000s glossy cable",
    "modern HD prime time",
    "cheap streaming / low-budget",
]

LOGO_STYLES = [
    "bubble / soft inflated 3D",
    "wordmark — bold sans",
    "wordmark — italic serif",
    "lettermark — show initials",
    "monogram — initials in seal",
    "badge / seal with rays",
    "neon outlined",
    "retro chrome / metallic",
]

TYPOGRAPHY_PRESETS = [
    "Sans bold (modern condensed)",
    "Serif elegant (Times-like)",
    "90s grotesque (rounded)",
    "Condensed news",
    "Handwritten script",
    "Retro chrome / metallic",
]

DEFAULT_BRAND_PALETTE = {
    "primary":   "#1d4e89",
    "secondary": "#f4b400",
    "accent":    "#d94e4e",
}

STUDIO_COLOR_PALETTES = [
    "warm",
    "cool",
    "saturated primary",
    "pastel",
    "monochrome",
]

STUDIO_BACKDROPS = [
    "city skyline screen",
    "abstract gradient",
    "windows to street",
    "show logo wall",
    "library books",
    "led video wall",
    "curtain drape",
]

SOFA_STYLES = [
    "modern minimal",
    "classic loveseat",
    "armchairs facing",
    "talk show wraparound",
    "bar stools at high table",
]

LIGHTING_STYLES = [
    "bright high-key",
    "dramatic spots",
    "cool fluorescent",
    "warm tungsten",
    "colored gels",
]

FLOOR_STYLES = [
    "glossy wood",
    "carpet",
    "industrial concrete",
    "tiled",
    "lit acrylic platform",
]

# (key, label) — key is filename slug, label is shown to the user
STUDIO_ANGLES = [
    ("wide",        "Wide establishing"),
    ("cam1_hosts",  "Cam 1 — on hosts"),
    ("cam2_guests", "Cam 2 — on guests"),
    ("cam3_side",   "Cam 3 — side 2-shot"),
    ("audience",    "Audience POV"),
]

# Per-angle framing snippets — appended to the studio_image_prompt template.
# All 5 angles show an EMPTY set — no hosts, no guests, no audience. Characters
# and audience are generated separately and composited in step 4.
STUDIO_ANGLE_FRAMING = {
    "wide": ("Wide establishing shot of the entire empty studio. Frame should "
             "include the hosts' table, the guest sofa area, and rows of "
             "empty audience seating. Convey scale and depth. No people."),
    "cam1_hosts": ("Empty studio. Frame on the unoccupied hosts' table area "
                    "from the camera-1 position. Guest sofa visible in soft "
                    "focus behind. Eye-level camera. No people in shot."),
    "cam2_guests": ("Empty studio. Frame on the unoccupied guest sofa area, "
                     "viewed across the floor from camera 2. Eye-level. "
                     "No people in shot."),
    "cam3_side": ("Empty studio. Side-angle framing showing the empty hosts' "
                   "table and the empty guest sofa in profile, dramatic studio "
                   "lighting on the empty conversation area. No people."),
    "audience": ("Empty studio. View from the back rows of the audience "
                  "seating, looking toward the empty stage. All audience "
                  "seats unoccupied. No people in shot."),
}

# Aspect ratios offered for studio renders (Recraft excluded — vector
# output is wrong for photo-real studio scenes).
STUDIO_ASPECT_RATIOS = ["16:9", "9:16"]
DEFAULT_STUDIO_ASPECT = "16:9"

# Face generator filters (matches this-person-does-not-exist.com dropdowns)
FACE_GENDERS = ["Any", "Male", "Female"]
FACE_AGES = ["Any", "12-18", "19-25", "26-35", "35-50", "50+"]
FACE_ETHNICITIES = [
    "Any", "Asian", "Black", "White",
    "Indian", "Middle Eastern", "Latino Hispanic",
]

# Per-character poses (key, label)
CHARACTER_POSES = [
    ("portrait",  "Portrait (CU)"),
    ("standing",  "Full-body standing"),
    ("entrance",  "Entrance pose"),
    ("seated",    "Seated on sofa"),
]

# Per-pose framing instructions appended to character_pose_prompt
CHARACTER_POSE_FRAMING = {
    "portrait": ("Close-up portrait, head and shoulders. Eye contact with the "
                  "camera. Neutral confident expression. Plain studio backdrop, "
                  "soft key lighting."),
    "standing": ("Full-body standing pose, head-to-toe in frame, neutral stance "
                  "with relaxed arms. Plain neutral backdrop. Even studio "
                  "lighting, sharp focus from head to feet."),
    "entrance": ("Mid-stride walking toward the camera as if entering the studio "
                  "through a stage doorway. Smile, hand near chest level in a "
                  "warm wave or acknowledgement. Studio interior visible behind, "
                  "stage lights catching the figure."),
    "seated":   ("Seated upright on the studio sofa, attentive posture, hands "
                  "relaxed in lap. IMPORTANT: framing is waist-up — show only "
                  "from the waist up. DO NOT show legs or feet. Studio backdrop "
                  "visible behind. Eye-level camera."),
}

# Aspect ratio per pose
CHARACTER_POSE_ASPECTS = {
    "portrait":  "9:16",
    "standing":  "9:16",
    "entrance":  "16:9",
    "seated":    "16:9",
}

# Which studio shot (if any) to use as a SECONDARY reference image for
# in-studio poses, in addition to the identity reference (portrait/face).
CHARACTER_POSE_STUDIO_REF = {
    "entrance": "wide",        # entering the room — wide establishing
    "seated":   "cam2_guests", # on the guest sofa
}

# ── Role-aware outfit catalogs ────────────────────────────────────────
# Each character_id maps to a role; each role has its own outfit + color
# catalogs. Each outfit/color entry has {label, description}: the label is
# what the user sees in the dropdown, the description is what goes into
# the pose-render prompt (a richer phrase than just the label).
CHARACTER_ROLE_MAP = {
    "host1":      "host",
    "host2":      "host",
    "heroine":    "heroine",
    "friend1":    "friend",
    "friend2":    "friend",
    "friend3":    "friend",
    "expert":     "expert",
    "antagonist": "antagonist",
}
DEFAULT_ROLE = "host"

CHARACTER_ROLE_OUTFITS = {
    "host": [
        {"label": "Anchor suit", "gender": "male",
         "description": "tailored two-button business suit, crisp dress shirt, "
                        "muted patterned tie, polished oxfords, anchor wristwatch"},
        {"label": "Three-piece suit", "gender": "male",
         "description": "modern three-piece suit with matching vest, slim tie, "
                        "pocket square, polished derby shoes"},
        {"label": "Blazer + chinos", "gender": "male",
         "description": "fitted blazer over an open-collar shirt, slim chinos, "
                        "leather loafers, polished but approachable"},
        {"label": "Cardigan + oxford + slacks", "gender": "male",
         "description": "knit cardigan over a crisp oxford shirt, smart trousers, "
                        "leather brogues, friendly newsroom feel"},
        {"label": "Blazer + sheath dress", "gender": "female",
         "description": "structured blazer over a tailored knee-length sheath dress, "
                        "simple necklace, closed-toe heels, broadcast-ready"},
        {"label": "Blouse + pencil skirt", "gender": "female",
         "description": "silk blouse, fitted pencil skirt, low pumps, "
                        "statement earrings, broadcast-friendly"},
        {"label": "Wraparound dress", "gender": "female",
         "description": "tailored knee-length wraparound dress, low heels, "
                        "minimal jewelry, classic daytime host look"},
        {"label": "Pantsuit", "gender": "female",
         "description": "tailored pantsuit with a silk shell underneath, low heels, "
                        "statement earrings, modern anchor look"},
    ],
    "heroine": [
        {"label": "Cardigan + jeans", "gender": "female",
         "description": "soft cardigan over a plain crewneck tee, ordinary jeans, "
                        "simple flats, no makeup statement, everywoman feel"},
        {"label": "Modest day-dress", "gender": "female",
         "description": "modest day-dress with three-quarter sleeves, hem at the knee, "
                        "simple sandals, single thin necklace, warm relatable look"},
        {"label": "Knit sweater + pencil skirt", "gender": "female",
         "description": "knit sweater tucked into a midi pencil skirt, small heels, "
                        "modest gold studs, professional but warm"},
        {"label": "Blouse + slacks", "gender": "female",
         "description": "plain blouse, tailored slacks, low loafers, minimal jewelry, "
                        "suburban-mom polish"},
        {"label": "Patterned blouse + jeans", "gender": "female",
         "description": "untucked patterned blouse over jeans, plain flats, tiny "
                        "pendant, looks like she dressed up for being on TV"},
        {"label": "Shawl-collar cardigan + jeans", "gender": "female",
         "description": "shawl-collar cardigan over a plain tee, comfy jeans, plain "
                        "ankle boots, kind and approachable"},
        {"label": "Tunic + leggings", "gender": "female",
         "description": "longer-cut tunic top, slim leggings, flat ankle boots, "
                        "simple ponytail-ready look"},
    ],
    "friend": [
        {"label": "Polo + chinos", "gender": "male",
         "description": "solid polo shirt and slim chinos, leather loafers, simple "
                        "leather-strap watch, friendly suburban dad look"},
        {"label": "Linen shirt + jeans", "gender": "male",
         "description": "soft linen button-up shirt rolled at the sleeves, ordinary "
                        "jeans, plain sneakers, easy weekend feel"},
        {"label": "Henley + chinos", "gender": "male",
         "description": "soft cotton henley, slim chinos, casual leather sneakers, "
                        "easy approachable suburban-dad vibe"},
        {"label": "Button-up + jeans", "gender": "male",
         "description": "casual checkered button-up rolled at the cuffs, ordinary "
                        "jeans, plain ankle boots, looks like a real audience member"},
        {"label": "Casual blouse + jeans", "gender": "female",
         "description": "everyday patterned blouse, ordinary jeans, plain flats, "
                        "minimal accessories, looks like a real audience member who "
                        "got pulled on stage"},
        {"label": "Tee + cardigan + jeans", "gender": "female",
         "description": "plain tee under a soft cardigan, jeans, comfortable flats, "
                        "single thin necklace"},
        {"label": "Knit day-dress", "gender": "female",
         "description": "knit knee-length day-dress, ankle boots, simple stud "
                        "earrings, warm girlfriend energy"},
        {"label": "Tunic top + leggings", "gender": "female",
         "description": "flowy tunic top, slim leggings, ankle boots, comfortable "
                        "and relatable"},
        {"label": "Blouse + casual skirt", "gender": "female",
         "description": "feminine blouse tucked into a casual A-line skirt, low flats, "
                        "warm bracelet, dressed-up-for-TV but still everyday"},
    ],
    "expert": [
        {"label": "Lab coat over shirt + tie", "gender": "male",
         "description": "open lab coat over a crisp dress shirt and tie, smart slacks, "
                        "polished shoes, name badge with credentials"},
        {"label": "Tweed jacket + oxford shirt", "gender": "male",
         "description": "tweed sports jacket with elbow patches, oxford shirt and "
                        "modest knit tie, smart slacks, leather brogues, "
                        "professorial-researcher feel"},
        {"label": "Smart suit + tie", "gender": "male",
         "description": "well-tailored suit, plain shirt and quiet tie, polished "
                        "oxfords, academic lapel pin"},
        {"label": "Blazer + turtleneck (m)", "gender": "male",
         "description": "blazer over a fine-knit turtleneck, smart trousers, plain "
                        "dress shoes, modern male academic look"},
        {"label": "Lab coat over collared dress", "gender": "female",
         "description": "open lab coat over a knee-length collared dress, low pumps, "
                        "simple stud earrings, name badge, female clinician look"},
        {"label": "Lab coat over blouse + slacks", "gender": "female",
         "description": "open lab coat over a blouse and tailored slacks, low "
                        "loafers, name badge, female researcher look"},
        {"label": "Blazer + silk blouse (f)", "gender": "female",
         "description": "tailored blazer over a silk blouse, tailored slacks, "
                        "low pumps, minimal jewelry, female academic-physician look"},
        {"label": "Scrubs + lab coat (unisex)", "gender": "unisex",
         "description": "medical scrubs with a knee-length lab coat, stethoscope "
                        "around neck, name badge on lapel, white sneakers, "
                        "credible clinician look"},
        {"label": "Minimalist scientist (unisex)", "gender": "unisex",
         "description": "fine-knit sweater, slim trousers, plain leather shoes, "
                        "no tie, modern minimalist researcher look"},
    ],
    "antagonist": [
        {"label": "Sharp corporate suit", "gender": "male",
         "description": "sharply tailored single-breasted suit, slim tie, crisp "
                        "dress shirt, polished oxfords, expensive watch, "
                        "intimidating corporate-lawyer aura"},
        {"label": "Pinstripe lobbyist suit", "gender": "male",
         "description": "pinstripe three-piece suit, bold power tie, gold cufflinks, "
                        "polished wingtips, classic Washington-lobbyist look"},
        {"label": "Bureaucratic suit", "gender": "male",
         "description": "boxy bureaucratic suit, plain dress shirt, dull patterned "
                        "tie, government-issued lapel pin, slightly dated "
                        "tortoiseshell glasses, male regulator look"},
        {"label": "Modern slim three-piece", "gender": "male",
         "description": "modern slim-fit three-piece suit with contrasting patterned "
                        "vest, narrow tie, expensive watch, polished derbys"},
        {"label": "Power sheath dress", "gender": "female",
         "description": "tailored sheath dress with structured shoulders, expensive "
                        "gold jewelry, high stiletto heels, sleek hair, intimidating "
                        "corporate-executive aura"},
        {"label": "Corporate blazer + pencil skirt", "gender": "female",
         "description": "tailored blazer over a silk blouse, knee-length pencil "
                        "skirt, expensive heels, branded folder under arm, "
                        "pharma-rep look"},
        {"label": "Luxury cosmetics exec", "gender": "female",
         "description": "expensive tailored blazer over a silk camisole, slim "
                        "trousers, designer heels, statement jewelry, "
                        "cosmetics-industry executive look"},
        {"label": "Bureaucratic skirt suit", "gender": "female",
         "description": "boxy skirt suit, plain blouse, government lapel pin, "
                        "dated low pumps, female regulator look"},
    ],
}

# Color palettes are CONCRETE — only color names. The image model gets a
# clear color directive without abstract terms like 'jewel tones' that
# different models interpret differently.
CHARACTER_ROLE_OUTFIT_COLORS = {
    "host": [
        {"label": "Broadcast neutral",
         "description": "beige, cream, and light grey only; no patterns, no logos"},
        {"label": "Navy + white",
         "description": "navy blue suit/dress, white shirt or blouse, no other colors"},
        {"label": "Charcoal + white",
         "description": "charcoal grey, crisp white accents, no other colors"},
        {"label": "Camel + burgundy",
         "description": "camel tan main color, deep burgundy red accents, cream details"},
        {"label": "Steel blue + slate",
         "description": "steel blue main color, slate grey accents, white shirt"},
        {"label": "Deep emerald + gold",
         "description": "deep emerald green main color, gold accents, white details"},
        {"label": "Royal sapphire + gold",
         "description": "royal sapphire blue main color, gold jewelry accents, white details"},
        {"label": "Ruby red + black",
         "description": "ruby red main color, black accents, no other colors"},
        {"label": "All black + silver",
         "description": "all black main color, brushed silver hardware/jewelry accents"},
    ],
    "heroine": [
        {"label": "Peach + cream",
         "description": "soft peach pink main color, warm cream accents"},
        {"label": "Blush pink + cream",
         "description": "blush pink main color, warm cream accents"},
        {"label": "Sage green + oatmeal",
         "description": "sage green main color, oatmeal beige accents"},
        {"label": "Dusty rose + cream",
         "description": "dusty rose pink main color, cream white accents"},
        {"label": "Warm beige + taupe",
         "description": "warm beige main color, soft taupe brown accents"},
        {"label": "Soft denim + cream",
         "description": "soft mid-blue denim main color, cream white top"},
        {"label": "Sky blue + ivory",
         "description": "soft sky blue main color, ivory accents"},
        {"label": "Lavender + grey",
         "description": "muted lavender main color, soft grey accents"},
    ],
    "friend": [
        {"label": "Denim blue + white",
         "description": "denim blue main color, plain white top"},
        {"label": "Pale blue + dusty pink",
         "description": "pale blue main color, dusty pink accents"},
        {"label": "Olive green + terracotta",
         "description": "olive green main color, terracotta orange accents, jeans"},
        {"label": "Beige + taupe",
         "description": "warm beige main color, taupe brown accents"},
        {"label": "Mustard yellow + cream",
         "description": "mustard yellow main color, cream white accents"},
        {"label": "Rust orange + cream",
         "description": "rust orange main color, cream white accents"},
        {"label": "Coral + teal",
         "description": "coral pink main color, teal green accents, white details"},
        {"label": "Sage green + denim",
         "description": "sage green top, blue denim bottom"},
    ],
    "expert": [
        {"label": "Hospital white + pale blue",
         "description": "white lab coat, pale hospital blue scrubs or shirt underneath"},
        {"label": "Tweed brown + oatmeal",
         "description": "tweed brown main color, oatmeal beige shirt underneath"},
        {"label": "Navy + white",
         "description": "navy blue main color, crisp white shirt accents"},
        {"label": "Charcoal + burgundy",
         "description": "charcoal grey main color, deep burgundy red tie or accents"},
        {"label": "Black + charcoal + white",
         "description": "black and charcoal grey, white shirt, no other colors"},
        {"label": "Soft grey + cream",
         "description": "soft mid-grey main color, cream white accents"},
        {"label": "Dark green + tan",
         "description": "dark forest green main color, tan brown accents"},
    ],
    "antagonist": [
        {"label": "All black + white shirt",
         "description": "all black suit/dress, single crisp white shirt/blouse accent"},
        {"label": "Navy pinstripe + red tie",
         "description": "dark navy blue with thin white pinstripes, bold red tie or accent"},
        {"label": "Black + gold",
         "description": "all black main color, gold jewelry and hardware accents"},
        {"label": "Charcoal + white",
         "description": "charcoal grey suit, cool white shirt"},
        {"label": "Sharp white + black",
         "description": "pure bright white and pure black contrast, no warm colors"},
        {"label": "Cream + navy",
         "description": "cream tan blazer, dark navy blue base, no other colors"},
        {"label": "Burgundy + black",
         "description": "deep burgundy red main color, black accents"},
        {"label": "Dark grey + silver",
         "description": "dark grey suit, brushed silver hardware/jewelry accents"},
    ],
}


def role_for_char_id(char_id: str) -> str:
    return CHARACTER_ROLE_MAP.get(char_id, DEFAULT_ROLE)


def _normalize_gender(gender: str | None) -> str:
    """Map face-filter gender values ('Any' / 'Male' / 'Female') to outfit
    gender tags ('any' / 'male' / 'female')."""
    if not gender:
        return "any"
    g = gender.strip().lower()
    if g in ("any", "", "unspecified"):
        return "any"
    if g in ("male", "m", "man"):
        return "male"
    if g in ("female", "f", "woman"):
        return "female"
    return "any"


def outfits_for_role(role: str, gender: str | None = None) -> list:
    """Return list of {label, gender, description} for a role, filtered by
    gender. 'Any' / None → no filter (returns everything). Falls back to 'host'."""
    catalog = CHARACTER_ROLE_OUTFITS.get(role, CHARACTER_ROLE_OUTFITS[DEFAULT_ROLE])
    g = _normalize_gender(gender)
    if g == "any":
        return list(catalog)
    return [o for o in catalog if o.get("gender", "unisex") in (g, "unisex")]


def outfit_colors_for_role(role: str) -> list:
    return CHARACTER_ROLE_OUTFIT_COLORS.get(role, CHARACTER_ROLE_OUTFIT_COLORS[DEFAULT_ROLE])


def outfit_labels_for_role(role: str, gender: str | None = None) -> list:
    return [o["label"] for o in outfits_for_role(role, gender)]


def outfit_color_labels_for_role(role: str) -> list:
    return [c["label"] for c in outfit_colors_for_role(role)]


def find_outfit_description(role: str, label: str) -> str:
    """Look up a wardrobe description by label within a role's catalog
    (across all genders, so a saved value still resolves even if the
    current dropdown filter doesn't include it). Falls back to the label."""
    catalog = CHARACTER_ROLE_OUTFITS.get(role, CHARACTER_ROLE_OUTFITS[DEFAULT_ROLE])
    for o in catalog:
        if o["label"] == label:
            return o["description"]
    return label


def find_outfit_color_description(role: str, label: str) -> str:
    for c in outfit_colors_for_role(role):
        if c["label"] == label:
            return c["description"]
    return label


def default_outfit_label_for_role(role: str, gender: str | None = None) -> str:
    items = outfits_for_role(role, gender)
    return items[0]["label"] if items else ""


def default_outfit_color_label_for_role(role: str) -> str:
    items = outfit_colors_for_role(role)
    return items[0]["label"] if items else ""

# Audience composition dropdowns
AUDIENCE_GENDER_RATIOS = [
    "mostly female (80/20)",
    "balanced (50/50)",
    "mostly male (20/80)",
]

AUDIENCE_ETHNIC_MIXES = [
    "predominantly white",
    "mixed",
    "predominantly Black",
    "predominantly Latino",
    "predominantly Asian",
]

AUDIENCE_AGE_RANGES = [
    "20–40",
    "30–60",
    "40–70",
    "mixed (20–70)",
]

AUDIENCE_CROWD_SIZES = [
    "small (40)",
    "medium (120)",
    "large (300)",
]

AUDIENCE_DRESS_CODES = [
    "casual",
    "business casual",
    "dressy daytime",
]

AUDIENCE_ENERGY_BASELINES = [
    "polite",
    "engaged",
    "rowdy",
]

# Audience pose set (key, label)
AUDIENCE_POSES = [
    ("attentive",    "Attentive / neutral"),
    ("applauding",   "Applauding"),
    ("laughing",     "Laughing"),
    ("disapproving", "Disapproving (boo)"),
]

# Per-reaction body-language snippet appended to audience_pose_prompt.
# 'attentive' is the phase-1 anchor (no "as in the reference image" hook);
# the others assume the attentive shot is provided as the reference photo.
AUDIENCE_POSE_FRAMING = {
    "attentive":    ("Seated audience in calm neutral posture, attentive expressions, "
                      "looking forward toward the stage (toward the camera), hands "
                      "resting in laps or on armrests, quiet listening energy."),
    "applauding":   ("Same seated audience as in the reference image — same faces, "
                      "same clothing, same seating positions. Hands raised mid-clap "
                      "or just finishing a clap, smiling broadly, some leaning "
                      "slightly forward, warm approving energy across the rows."),
    "laughing":     ("Same seated audience as in the reference image — same faces, "
                      "same clothing, same seating positions. Mouths open in laughter, "
                      "heads tilted back or to the side, some hands resting on stomachs "
                      "or covering mouths, amused expressions across the rows."),
    "disapproving": ("Same seated audience as in the reference image — same faces, "
                      "same clothing, same seating positions. Frowning expressions, "
                      "brows furrowed, some shaking heads, a few hands pointing or "
                      "raised in disagreement, disapproving body language."),
}

AUDIENCE_POSE_ASPECT = "16:9"  # always wide; per user spec

# ElevenLabs default voices — (voice_id, label). voice_id is the stable API id.
ELEVENLABS_VOICES = [
    ("21m00Tcm4TlvDq8ikWAM", "Rachel — calm female"),
    ("AZnzlk1XvdvUeBnXmlld", "Domi — strong female"),
    ("EXAVITQu4vr4xnSDxMaL", "Bella — soft female"),
    ("MF3mGyEYCl7XYWbV9V6O", "Elli — emotional female"),
    ("ErXwobaYiN019PkySvjV", "Antoni — well-rounded male"),
    ("VR6AewLTigWG4xSOukaG", "Arnold — crisp male"),
    ("pNInz6obpgDQGcFmaJgB", "Adam — deep male"),
    ("TxGEqnHWrfWFTfGW9XjX", "Josh — deep male"),
    ("yoZ06aMxZJJ28mfd3POQ", "Sam — raspy male"),
]

DEFAULT_VOICE_SETTINGS = {
    "stability": 0.50,
    "style": 0.30,
    "speed": 1.00,
}

# Storyboard beat types — key + display label
BEAT_TYPES = [
    ("line",              "💬 Line"),
    ("stage_direction",   "🎭 Stage direction"),
    ("audience",          "👥 Audience reaction"),
    ("host_interjection", "🎙 Host interjection"),
    ("pause",             "⏸ Pause"),
    ("entrance",          "🚪 Entrance"),
]

SHOT_TYPES = [
    "",
    "CU (close-up)",
    "MS (medium)",
    "2-shot",
    "wide",
    "audience reaction",
    "entrance wide",
]

# ── Keyframe stage (Generate sub-tab) helpers ────────────────────────
# Each shot type maps to:
#   - a framing snippet describing how the model should compose the keyframe
#   - the studio angle whose render is sent as the secondary reference image
#     (for backdrop continuity — same set across all beats)
#   - the character pose whose render is sent as the primary identity ref
KEYFRAME_FRAMING_BY_SHOT = {
    "CU (close-up)":     "Tight close-up on the speaker — head and shoulders only, "
                          "eye contact with the camera, mid-line delivery.",
    "MS (medium)":       "Medium shot of the speaker, waist-up, seated or standing, "
                          "mid-conversation body language.",
    "2-shot":            "Two-character medium shot — the speaker is the primary subject, "
                          "a second listener visible in the frame in soft focus.",
    "wide":              "Wide establishing shot — speaker visible mid-frame with the "
                          "studio set surrounding them, conveys scale.",
    "audience reaction": "Wide audience POV from the stage facing the seating rows — "
                          "no individual speaker focus, crowd reacting.",
    "entrance wide":     "Wide tracking shot — speaker entering the studio, full body "
                          "visible, stage lights catching the figure.",
}

KEYFRAME_STUDIO_REF_BY_SHOT = {
    "CU (close-up)":     "cam1_hosts",
    "MS (medium)":       "cam2_guests",
    "2-shot":            "cam3_side",
    "wide":              "wide",
    "audience reaction": "audience",
    "entrance wide":     "wide",
}

KEYFRAME_POSE_BY_SHOT = {
    "CU (close-up)":     "portrait",
    "MS (medium)":       "seated",
    "2-shot":            "seated",
    "wide":              "standing",
    "audience reaction": None,         # no character identity ref needed
    "entrance wide":     "entrance",
}

DEFAULT_KEYFRAME_SHOT = "MS (medium)"

# Head-orientation presets used in the Talking heads tab when re-rendering
# a per-beat keyframe. The key is the radio button's value; `label` is the
# UI label; `description` is appended to the prompt verbatim.
TALKING_HEAD_ORIENTATIONS = [
    {"key": "front",   "label": "Front",
     "description": "facing the camera directly, looking straight into the lens"},
    {"key": "slight_left",
     "label": "Slight left",
     "description": "head turned slightly to the left, about 20–30° off the camera axis"},
    {"key": "left_profile",
     "label": "Left profile",
     "description": "head turned 90° to the left, in profile, looking off-camera"},
    {"key": "slight_right",
     "label": "Slight right",
     "description": "head turned slightly to the right, about 20–30° off the camera axis"},
    {"key": "right_profile",
     "label": "Right profile",
     "description": "head turned 90° to the right, in profile, looking off-camera"},
    {"key": "back",   "label": "Back",
     "description": "back of the head visible, the character is facing away from the camera"},
]
DEFAULT_HEAD_ORIENTATION = "front"


def head_orientation_description(key: str) -> str:
    for o in TALKING_HEAD_ORIENTATIONS:
        if o["key"] == key:
            return o["description"]
    return TALKING_HEAD_ORIENTATIONS[0]["description"]


def head_orientation_label(key: str) -> str:
    for o in TALKING_HEAD_ORIENTATIONS:
        if o["key"] == key:
            return o["label"]
    return TALKING_HEAD_ORIENTATIONS[0]["label"]

TRANSITION_TYPES = [
    "",
    "hard cut",
    "smooth",
]

# Storyboard pipeline stages (key, label)
STORYBOARD_PASSES = [
    ("parse",         "1. Parse script"),
    ("atmospherize",  "2. Atmospherize"),
    ("camera",        "3. Camera plan"),
]

# Camera plan presets (global directing style)
CAMERA_PRESETS = [
    "classic talk show",
    "fast cuts (high energy)",
    "static two-shot",
    "documentary style",
    "daytime drama",
]

CAMERA_DEFAULT_TRANSITIONS = [
    "contextual (LLM decides per beat)",
    "mostly hard cuts",
    "mostly smooth",
    "alternate hard / smooth",
]

WIDE_SHOT_FREQUENCIES = [
    "rare (only on entrances + applause)",
    "occasional (every 20–30 beats)",
    "frequent (every 10 beats)",
]

DEFAULT_CAMERA_PLAN = {
    "preset": CAMERA_PRESETS[0],
    "reaction_pct": 30,
    "audience_pct": 15,
    "avg_shot_duration": 4.0,
    "default_transition": CAMERA_DEFAULT_TRANSITIONS[0],
    "wide_frequency": WIDE_SHOT_FREQUENCIES[1],
    "custom_rules": "",
}

# Step 2 Generate pipeline stages (key, label)
PIPELINE_STAGES = [
    ("parse",        "1. LLM Parse"),
    ("atmospherize", "2. LLM Atmospherize"),
    ("camera",       "3. LLM Camera plan"),
    ("tts",          "4. TTS audio (per line)"),
    ("keyframes",    "5. Keyframes (per speaking beat)"),
    ("lipsync",      "6. Lip-sync clips"),
    ("idle_motion",  "7. Reaction idle motion"),
]

# ── Step 3 (Broadcast inserts) asset categories ──────────────────────
BROLL_CATEGORIES = [
    "lab / scientific",
    "kitchen / cooking",
    "factory / production",
    "hero's home / daily life",
    "before / after sequence",
    "product close-up",
    "stock / lifestyle",
    "atmospheric / mood",
]

GRAPHIC_CATEGORIES = [
    "anatomy diagram",
    "mechanism of action",
    "before / after comparison",
    "statistics card",
    "price flash",
    "urgency timer",
    "stock counter",
    "testimonial quote",
    "lower third",
    "show logo bumper",
    "product label",
]

SFX_CATEGORIES = [
    "dramatic sting",
    "transition whoosh",
    "urgency tick-tock",
    "reveal swoosh",
    "applause loop",
    "boo / disapproval",
    "laughter loop",
    "ambient room tone",
]

ASSET_STATUSES = ["pending", "generated", "failed"]

# ── Step 4 (Editing & Assembly) ──────────────────────────────────────
PIP_POSITIONS = [
    "bottom-right",
    "bottom-left",
    "top-right",
    "top-left",
]

PIP_SIZES = [
    "small (20% width)",
    "medium (30% width)",
    "large (40% width)",
]

LOWER_THIRD_STYLES = [
    "block (solid color)",
    "clean line",
    "network bar",
    "90s daytime",
    "modern blur",
]

LOGO_BUMPER_FREQUENCIES = [
    "never",
    "act transitions only",
    "every 60 seconds",
    "every 30 seconds",
]

RENDER_QUALITIES = [
    "preview (720p, fast encode)",
    "broadcast (1080p)",
    "high (1080p, slow encode)",
]

DEFAULT_LAYOUT_SETTINGS = {
    "pip_position":           PIP_POSITIONS[0],
    "pip_size":               PIP_SIZES[1],
    "lower_third_style":      LOWER_THIRD_STYLES[3],
    "logo_bumper_freq":       LOGO_BUMPER_FREQUENCIES[1],
    "render_quality":         RENDER_QUALITIES[0],
    "tts_volume_db":          0.0,
    "sfx_volume_db":          -6.0,
    "audience_volume_db":     -8.0,
}

# Step 4 pipeline stages (key, label)
EDITING_PIPELINE_STAGES = [
    ("plan",     "1. LLM plan compositing (overlays per clip)"),
    ("overlays", "2. Render text overlays (lower thirds + price flashes)"),
    ("preview",  "3. ffmpeg preview render (720p)"),
    ("final",    "4. ffmpeg final render (1080p)"),
]

# Output settings
WORDS_PER_MINUTE = 150  # for screen-reading dialogue
TARGET_WORDS_PER_ACT = {
    15: 550,
    25: 950,
    30: 1100,
    45: 1700,
    60: 2300,
}
