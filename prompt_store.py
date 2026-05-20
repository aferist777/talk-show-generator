"""
Centralized registry for system / user prompts used across the app.

Each named prompt has:
  • a canonical default template (with {placeholder} markers)
  • zero or more user-edited versions persisted to
    ~/.talkshow_generator/prompts/<name>/<version_slug>.json
  • short docs per placeholder so the editor UI can explain them on hover

The store is a process-wide singleton called STORE.
"""
import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from config import APP_DIR

PROMPTS_DIR = APP_DIR / "prompts"
PROMPTS_DIR.mkdir(exist_ok=True)


@dataclass
class PromptSpec:
    name: str
    display_name: str
    default_template: str
    param_docs: dict
    description: str = ""


@dataclass
class PromptVersion:
    name: str
    template: str
    addition_summary: str = ""
    created_at: str = ""
    is_default: bool = False


def _slug(s: str) -> str:
    return re.sub(r"[^\w\s-]", "", s).strip().replace(" ", "_") or "version"


class PromptStore:
    def __init__(self):
        self._specs: dict = {}
        self._active_version: dict = {}  # prompt_name -> version_name

    # ── registration ───────────────────────────────────────────────
    def register(self, spec: PromptSpec):
        self._specs[spec.name] = spec

    def has(self, name: str) -> bool:
        return name in self._specs

    def spec(self, name: str) -> PromptSpec:
        if name not in self._specs:
            raise KeyError(f"Unknown prompt: {name}")
        return self._specs[name]

    def list_names(self) -> list:
        return list(self._specs.keys())

    # ── versions ───────────────────────────────────────────────────
    def list_versions(self, name: str) -> list:
        spec = self.spec(name)
        out = [PromptVersion(
            name="default",
            template=spec.default_template,
            addition_summary="Original built-in template — leave alone unless you really need to.",
            created_at="",
            is_default=True,
        )]
        d = PROMPTS_DIR / name
        if d.exists():
            for f in sorted(d.glob("*.json")):
                try:
                    data = json.loads(f.read_text(encoding="utf-8"))
                    out.append(PromptVersion(
                        name=data.get("name", f.stem),
                        template=data.get("template", ""),
                        addition_summary=data.get("addition_summary", ""),
                        created_at=data.get("created_at", ""),
                        is_default=False,
                    ))
                except (json.JSONDecodeError, OSError):
                    continue
        return out

    def get_active_version_name(self, name: str) -> str:
        return self._active_version.get(name, "default")

    def set_active_version(self, name: str, version_name: str):
        self._active_version[name] = version_name

    def get_active_template(self, name: str) -> str:
        version_name = self.get_active_version_name(name)
        for v in self.list_versions(name):
            if v.name == version_name:
                return v.template
        return self.spec(name).default_template

    def render(self, name: str, **params) -> str:
        return self.get_active_template(name).format(**params)

    def save_version(self, name: str, version_name: str, template: str,
                     addition_summary: str = "") -> Path:
        if version_name.lower() == "default":
            raise ValueError("'default' is reserved.")
        d = PROMPTS_DIR / name
        d.mkdir(parents=True, exist_ok=True)
        path = d / f"{_slug(version_name)}.json"
        payload = {
            "name": version_name,
            "template": template,
            "addition_summary": addition_summary,
            "created_at": datetime.now().isoformat(timespec="seconds"),
        }
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        return path

    def delete_version(self, name: str, version_name: str):
        if version_name == "default":
            return
        path = PROMPTS_DIR / name / f"{_slug(version_name)}.json"
        path.unlink(missing_ok=True)


# Singleton
STORE = PromptStore()


# ── Register existing prompts ─────────────────────────────────────────
def _register_defaults():
    from prompts import (
        SYSTEM_PROMPT, EXPAND_SYSTEM, EXPAND_USER_TEMPLATE,
        CONTEXT_TEMPLATE, ACT1_PROMPT, ACT2_PROMPT, ACT3_PROMPT, ACT4_PROMPT,
    )

    STORE.register(PromptSpec(
        name="script_system",
        display_name="🎬 Script — base system prompt",
        description="The persona sent with every act-generation LLM call. Defines genre conventions, tone, and the output format.",
        default_template=SYSTEM_PROMPT,
        param_docs={"language": "Step 1 → Output language."},
    ))
    STORE.register(PromptSpec(
        name="expand_system",
        display_name="✨ Expand instructions — system prompt",
        description="Used when the user clicks 'Expand with AI' on the Instructions tab.",
        default_template=EXPAND_SYSTEM,
        param_docs={},
    ))
    STORE.register(PromptSpec(
        name="expand_user",
        display_name="✨ Expand instructions — user template",
        description="User-message template that wraps the brainstorm note.",
        default_template=EXPAND_USER_TEMPLATE,
        param_docs={"user_note": "The brief note the user typed."},
    ))
    STORE.register(PromptSpec(
        name="context",
        display_name="📋 Context block (shared per act call)",
        description="Renders all step-1 form fields into a structured block sent with every act prompt.",
        default_template=CONTEXT_TEMPLATE,
        param_docs={
            "show_name": "Step 1 → Show name", "host1_name": "Step 1 → Host 1 name",
            "host1_role": "Step 1 → Host 1 role", "host2_name": "Step 1 → Host 2 name",
            "host2_role": "Step 1 → Host 2 role", "duration": "Step 1 → Duration",
            "tone": "Step 1 → Tone preset",
            "country_style": "Step 1 → Country style preset",
            "dramatic_curve": "Step 1 → Dramatic curve",
            "pacing_speed": "Step 1 → Pacing / Intensity",
            "language": "Step 1 → Language",
            "niche": "Step 1 → Niche", "anchor": "Step 1 → Scientific anchor",
            "ingredients": "Step 1 → Folk ingredients", "heroine_name": "Step 1 → Heroine name",
            "heroine_age": "Step 1 → Heroine age", "heroine_location": "Step 1 → Heroine location",
            "heroine_profession": "Step 1 → Heroine profession", "heroine_result": "Step 1 → Headline result",
            "friend_count": "Step 1 → Friends count", "friend_results": "Step 1 → Friend testimonials",
            "antagonist_type": "Step 1 → Antagonist type", "antagonist_arc": "Step 1 → Emotional arc",
            "product_name": "Step 1 → Product name", "currency": "Step 1 → Currency",
            "anchor_price": "Step 1 → Anchor price", "offer_price": "Step 1 → Offer price",
            "bonus": "Step 1 → Bonus", "urgency": "Step 1 → Urgency window",
            "stock_limit": "Step 1 → Stock limit",
            "extra_instructions": "Step 1 → Additional instructions",
        },
    ))
    STORE.register(PromptSpec(
        name="act1",
        display_name="🎬 Act 1 — Opening & pain agitation",
        description="Drives the LLM to write the opening act.",
        default_template=ACT1_PROMPT,
        param_docs={
            "act1_end_min": "Computed end minute of act 1",
            "currency": "Step 1 → Currency",
            "high_anchor": "Computed inflated reference price",
            "anchor": "Step 1 → Scientific anchor",
            "target_words": "Computed target word count",
            "context": "Rendered context block (all step-1 fields)",
        },
    ))
    STORE.register(PromptSpec(
        name="act2",
        display_name="🎬 Act 2 — Heroine + friends",
        description="Drives the LLM to write the second act.",
        default_template=ACT2_PROMPT,
        param_docs={
            "act2_start_min": "Computed start minute of act 2",
            "act2_end_min": "Computed end minute of act 2",
            "target_words": "Computed target word count",
            "prior_summary": "Summary of act 1 (carried forward)",
            "context": "Rendered context block",
        },
    ))
    STORE.register(PromptSpec(
        name="act3",
        display_name="🎬 Act 3 — Expert + antagonist",
        description="Drives the LLM to write the third act.",
        default_template=ACT3_PROMPT,
        param_docs={
            "act3_start_min": "Computed start minute of act 3",
            "act3_end_min": "Computed end minute of act 3",
            "anchor": "Step 1 → Scientific anchor",
            "antagonist_type": "Step 1 → Antagonist type",
            "antagonist_arc": "Step 1 → Emotional arc",
            "target_words": "Computed target word count",
            "prior_summary": "Summary of acts 1+2",
            "context": "Rendered context block",
        },
    ))
    STORE.register(PromptSpec(
        name="act4",
        display_name="🎬 Act 4 — Offer & close",
        description="Drives the LLM to write the closing act (the offer).",
        default_template=ACT4_PROMPT,
        param_docs={
            "act4_start_min": "Computed start minute of act 4",
            "duration": "Step 1 → Duration",
            "product_name": "Step 1 → Product name",
            "currency": "Step 1 → Currency",
            "anchor_price": "Step 1 → Anchor price",
            "offer_price": "Step 1 → Offer price",
            "bonus": "Step 1 → Bonus",
            "urgency": "Step 1 → Urgency window",
            "stock_limit": "Step 1 → Stock limit",
            "target_words": "Computed target word count",
            "prior_summary": "Summary of acts 1+2+3",
            "context": "Rendered context block",
        },
    ))

    # Inline prompts (defined in UI code, registered here for editing)
    STORE.register(PromptSpec(
        name="product_name",
        display_name="✨ Product name — AI suggestion",
        description="Generates a pseudo-scientific product name from the scientific anchor + niche.",
        default_template=(
            "Suggest ONE product name for a dietary supplement positioned as activating "
            "the body's natural {anchor} for {niche}. The name should sound semi-scientific "
            "and confident — a single word or a hyphenated pair. Output ONLY the name, "
            "nothing else."
        ),
        param_docs={
            "anchor": "Step 1 → Scientific anchor term",
            "niche": "Step 1 → Niche / pain point",
        },
    ))

    # ── Storyboard pipeline (Sprint 1) ─────────────────────────────
    STORE.register(PromptSpec(
        name="storyboard_parse_system",
        display_name="📋 Storyboard · 1. Parse — system prompt",
        description="Parses one act of the generated talk-show script into a list of structured beats (line / stage_direction).",
        default_template=(
            "You parse a TV talk show script into structured beats. You output "
            "STRICT JSON wrapped in <beats>...</beats> tags — no preamble, no "
            "code fences, no commentary.\n\n"
            "Each beat is a JSON object with these fields:\n"
            "  type:    one of 'line' | 'stage_direction'\n"
            "  speaker: string — character name, or '' for stage_direction\n"
            "  text:    string — the spoken line (without surrounding quotes) "
            "or the stage direction prose\n"
            "  duration: number — estimated seconds based on ~150 wpm of "
            "spoken text (omit for stage_direction or set to 1.5)\n"
            "  act:     integer — which act this beat belongs to\n\n"
            "Recognise the script format:\n"
            "  • Dialog lines look like: NAME (emotion): \"text\"\n"
            "  • Stage directions are narrative prose between dialog lines, "
            "describing blocking, lighting, audience, character entrances\n"
            "  • Timecode headers (e.g. '[00:00 — 01:15] OPENING') and act "
            "headings are NOT beats; ignore them\n\n"
            "Output ONLY the <beats>...</beats> JSON. Nothing else."
        ),
        param_docs={},
    ))
    STORE.register(PromptSpec(
        name="storyboard_parse_user",
        display_name="📋 Storyboard · 1. Parse — user template",
        description="The user-message that feeds the script text to the Parse pass.",
        default_template=(
            "Parse Act {act_number} of the talk show into structured beats. "
            "The cast on stage includes: {cast_names}.\n\n"
            "SCRIPT SEGMENT:\n"
            "{act_text}\n\n"
            "Return the beats array wrapped in <beats>...</beats>."
        ),
        param_docs={
            "act_number": "Computed: which act (1–4) this segment represents.",
            "cast_names": "Computed: comma-separated cast members from step 1 (helps the LLM disambiguate speakers).",
            "act_text":   "Computed: the raw text of the act, extracted from script.txt.",
        },
    ))

    STORE.register(PromptSpec(
        name="storyboard_atmospherize_system",
        display_name="📋 Storyboard · 2. Atmospherize — system prompt",
        description="Inserts audience reactions, host interjections, pauses, and character entrances between existing beats.",
        default_template=(
            "You add atmospheric beats to a TV talk show storyboard. Given a "
            "list of existing line / stage_direction beats from one act, you "
            "INSERT additional beats representing:\n"
            "  • audience reactions (type 'audience'): applause, boos, gasps, laughs\n"
            "  • host interjections (type 'host_interjection'): quick host "
            "cut-ins like 'Calm down, let her finish'\n"
            "  • pauses (type 'pause'): silent dramatic beats\n"
            "  • character entrances (type 'entrance'): a new character walks "
            "onto stage\n\n"
            "Output the FULL enriched beats array (originals + new) wrapped in "
            "<beats>...</beats> JSON. PRESERVE every original beat byte-for-byte. "
            "Insert new beats at appropriate positions in the sequence.\n\n"
            "Schema for inserted beats:\n"
            "  audience:          speaker='', text='[short description like \"applause and cheers\" or \"Boo!\"]', duration=2–4s\n"
            "  host_interjection: speaker=one of the host names, text=the spoken interjection, duration=1–3s\n"
            "  entrance:          speaker=name of the entering character, text='[brief stage direction]', duration=2–4s\n"
            "  pause:             speaker='', text='[brief context]', duration=1–3s\n\n"
            "Match the crowd energy: {audience_energy}. Heat moments deserve "
            "strong reactions, calm moments deserve restraint. Heroine entrances "
            "and antagonist defeat moments warrant entrance + applause/boo "
            "combos. Stage directions describing a new character should be "
            "matched with an entrance + audience beat right before/after.\n\n"
            "Output ONLY the <beats>...</beats> JSON."
        ),
        param_docs={
            "audience_energy": "Step 2 → Audience · Energy baseline (polite / engaged / rowdy).",
        },
    ))
    STORE.register(PromptSpec(
        name="storyboard_atmospherize_user",
        display_name="📋 Storyboard · 2. Atmospherize — user template",
        description="Feeds the parsed beats + context summaries to the Atmospherize pass.",
        default_template=(
            "Act {act_number} of the show.\n\n"
            "Existing beats from the Parse pass:\n"
            "<beats>\n{beats_json}\n</beats>\n\n"
            "Continuity context from previous acts:\n"
            "{prior_summary}\n\n"
            "Audience composition:\n"
            "{audience_summary}\n\n"
            "Now output the enriched beats array wrapped in <beats>...</beats>."
        ),
        param_docs={
            "act_number":       "Computed: current act number.",
            "beats_json":       "Computed: JSON array of the act's parsed beats.",
            "prior_summary":    "Computed: brief summary of completed previous acts for continuity.",
            "audience_summary": "Step 2 → Audience: composition (gender/ethnic/age/size/dress/energy).",
        },
    ))

    STORE.register(PromptSpec(
        name="storyboard_camera_system",
        display_name="📋 Storyboard · 3. Camera plan — system prompt",
        description="Assigns shot type and transition style to every beat.",
        default_template=(
            "You are the director assigning camera coverage to a TV talk show "
            "storyboard. Given a list of beats, you populate the 'shot' and "
            "'transition' fields on every beat.\n\n"
            "Valid shot types:\n"
            "  • 'CU (close-up)'      — single speaker, head-and-shoulders\n"
            "  • 'MS (medium)'        — single speaker, waist-up\n"
            "  • '2-shot'             — two characters in frame\n"
            "  • 'wide'               — full stage establishing\n"
            "  • 'audience reaction'  — crowd close-up\n"
            "  • 'entrance wide'      — full stage tracking a new character\n\n"
            "Valid transition types:\n"
            "  • 'hard cut' — instant cut, used for energy / surprise / argument\n"
            "  • 'smooth'   — short cross-fade, used for calm consecutive lines\n\n"
            "Output the FULL beats array with shot + transition filled on every "
            "beat, wrapped in <beats>...</beats> JSON. Preserve every other "
            "field exactly.\n\n"
            "Rules:\n"
            "  • Vary shots — don't put CU on every line\n"
            "  • Reaction shots cut to a NON-speaking character listening; use "
            "according to the director's 'reaction shot %'\n"
            "  • Audience reactions get 'audience reaction' or 'wide' framing\n"
            "  • Entrances get 'entrance wide'\n"
            "  • Stage directions are usually 'wide' or '2-shot' depending on action\n"
            "  • Use 'hard cut' for high-energy moments (boos, interjections, "
            "entrances). Use 'smooth' for calm consecutive lines of the same speaker.\n\n"
            "Output ONLY the <beats>...</beats> JSON."
        ),
        param_docs={},
    ))
    STORE.register(PromptSpec(
        name="storyboard_camera_user",
        display_name="📋 Storyboard · 3. Camera plan — user template",
        description="Feeds the enriched beats + director preferences to the Camera pass.",
        default_template=(
            "Act {act_number}. Beats to plan camera for:\n"
            "<beats>\n{beats_json}\n</beats>\n\n"
            "Continuity context from previous acts:\n"
            "{prior_summary}\n\n"
            "Director's preferences (Camera plan sub-tab):\n"
            "{camera_plan_json}\n\n"
            "Custom rules (free-form):\n"
            "{custom_rules}\n\n"
            "Output the array with shot + transition filled, wrapped in <beats>...</beats>."
        ),
        param_docs={
            "act_number":       "Computed: current act number.",
            "beats_json":       "Computed: JSON array of the enriched beats from Atmospherize.",
            "prior_summary":    "Computed: brief summary of completed previous acts for continuity.",
            "camera_plan_json": "Step 2 → Camera plan: preset, reaction_pct, audience_pct, avg_shot_duration, default_transition, wide_frequency.",
            "custom_rules":    "Step 2 → Camera plan → Custom rules text area.",
        },
    ))

    STORE.register(PromptSpec(
        name="character_pose_prompt",
        display_name="🎭 Character pose — prompt builder",
        description="Composes the image prompt for one character pose. The face-seed image is sent as the primary reference (identity lock); for in-studio poses a studio shot is sent as the secondary reference (backdrop continuity).",
        default_template=(
            "Photo-realistic broadcast-quality portrait of a single person.\n"
            "Identity: {character_name}. Role on show: {role}. "
            "Gender: {gender}. Age range: {age}. Ethnicity: {ethnicity}.\n"
            "Distinctive features: {distinctive}\n\n"
            "{wardrobe_clause}\n"
            "{identity_lock_clause}\n"
            "{studio_clause}\n"
            "Pose & framing: {pose_framing}\n"
            "Style: photo-realistic, broadcast lighting, sharp focus, no text "
            "overlays, no watermarks."
        ),
        param_docs={
            "character_name":      "Step 2 → Characters → display name (from step 1 cast).",
            "role":                "Computed: role on the show (host / heroine / friend / expert / antagonist).",
            "gender":               "Step 2 → Characters → Gender filter.",
            "age":                  "Step 2 → Characters → Age range filter.",
            "ethnicity":            "Step 2 → Characters → Ethnicity filter.",
            "distinctive":          "Step 2 → Characters → Distinctive features text.",
            "wardrobe_clause":      "Computed: For the portrait pose — full wardrobe description + concrete color palette. For other poses — a WARDROBE LOCK instruction that tells the model to copy the outfit exactly from the reference photo (which is the already-rendered portrait).",
            "identity_lock_clause": "Computed: tells the model that the first reference image is either the face seed (portrait) or the previously-rendered portrait (other poses) and to keep the face exactly the same.",
            "studio_clause":        "Computed: a line about the studio backdrop when a secondary studio reference image is being sent, otherwise empty.",
            "pose_framing":         "Per-pose framing snippet (portrait / standing / entrance / seated).",
        },
    ))

    STORE.register(PromptSpec(
        name="audience_pose_prompt",
        display_name="👥 Audience pose — prompt builder",
        description="Composes the image prompt for one audience reaction (attentive / applauding / laughing / disapproving). Phase 1 (attentive) is the crowd anchor; phase-2 reactions lock the crowd composition to the rendered attentive shot.",
        default_template=(
            "Photo-realistic broadcast-quality wide shot of a television talk show "
            "studio audience.\n"
            "POV: camera positioned at the front of the stage, facing the audience "
            "seating rows. Show the seated crowd from the stage's perspective — "
            "heads, faces and bodies of audience members visible in rows that "
            "recede into the depth of the studio. 16:9 broadcast framing.\n\n"
            "Crowd composition — describe and depict accurately:\n"
            "{composition}\n\n"
            "Studio styling context:\n"
            "{studio_context}\n\n"
            "{crowd_lock_clause}\n"
            "Pose & reaction: {pose_framing}\n"
            "{extra_description}\n"
            "Style: photo-realistic, broadcast lighting, sharp focus, no text "
            "overlays, no watermarks, no logos, no captions."
        ),
        param_docs={
            "composition":       "Computed: combined composition string (gender ratio / ethnic mix / age range / crowd size / dress code / energy baseline).",
            "studio_context":    "Computed: short studio styling summary (era + palette + lighting + floor + brand colors) so the audience render visually matches the rest of the show.",
            "crowd_lock_clause": "Computed: For 'attentive' (phase 1) — empty (this is the anchor). For other reactions — a CROWD LOCK instruction telling the model to keep the SAME faces, clothing, and seating positions as in the reference photo, and only change expressions/poses.",
            "pose_framing":      "Per-reaction body-language snippet (attentive / applauding / laughing / disapproving).",
            "extra_description": "Step 2 → Audience → Extra description (free-form). Applied verbatim.",
        },
    ))

    STORE.register(PromptSpec(
        name="studio_image_prompt",
        display_name="🏛 Studio render — prompt builder",
        description="Composes the image prompt for one studio camera angle. Combines Brand colors + Studio params + the angle-specific framing.",
        default_template=(
            "Television talk show studio interior, photo-realistic, broadcast quality.\n"
            "IMPORTANT: This is an EMPTY SET. Do NOT include any people — no hosts, "
            "no guests, no audience members, no crew, no extras. Render only the "
            "physical set, furniture, lighting, decor, and props. Every chair "
            "and sofa must be unoccupied.\n"
            "Era / aesthetic: {era}. Color palette: {palette}. "
            "Brand colors — primary {primary}, secondary {secondary}, accent {accent}.\n"
            "Backdrop: {backdrop}. Sofa / seating: {sofa}. "
            "Lighting: {lighting}. Floor: {floor}.\n"
            "{logo_clause}\n"
            "Camera framing for this shot: {angle_framing}\n"
            "{extra_description}"
        ),
        param_docs={
            "era":               "Step 2 → Studio design → Era preset",
            "palette":           "Step 2 → Studio design → Color palette",
            "primary":           "Step 2 → Brand → Primary color (hex)",
            "secondary":         "Step 2 → Brand → Secondary color (hex)",
            "accent":            "Step 2 → Brand → Accent color (hex)",
            "backdrop":          "Step 2 → Studio design → Backdrop",
            "sofa":              "Step 2 → Studio design → Sofa / seating",
            "lighting":          "Step 2 → Studio design → Lighting",
            "floor":             "Step 2 → Studio design → Floor",
            "logo_clause":       "Computed: either 'The show logo is mounted on the back wall.' (when 'Show logo on backdrop' is on) or empty.",
            "angle_framing":     "Per-angle framing snippet (wide / cam1_hosts / cam2_guests / cam3_side / audience).",
            "extra_description": "Step 2 → Studio design → Extra description (free-form)",
        },
    ))

    STORE.register(PromptSpec(
        name="keyframe_prompt",
        display_name="🎞 Keyframe — prompt builder",
        description="Composes the image prompt for the per-beat keyframe rendered on the Talking heads tab. The first reference image is the character's portrait pose (identity + outfit lock). The keyframe is the starting frame for a future lipsync animation, so the head orientation matters more than the framing.",
        default_template=(
            "Photo-realistic broadcast-quality talking-head shot of a TV talk show.\n"
            "Identity: {character_name} ({role}, {gender}).\n\n"
            "IMPORTANT — IDENTITY + WARDROBE LOCK: The first reference image already shows "
            "this person fully rendered with their outfit. Reproduce the face, hair, body, "
            "AND outfit EXACTLY as in that reference — same garments, same cut, same colors, "
            "same accessories. Do not invent new clothing or change appearance.\n\n"
            "Head orientation: {head_orientation}.\n"
            "Camera framing: {framing}\n"
            "Character Pose & Expression: {visual_pose_description}\n"
            "Style: photo-realistic, broadcast lighting, sharp focus, neutral mouth position "
            "(this is the starting frame of a speaking clip — keep the mouth closed or "
            "barely parted, never wide open). No text overlays, no watermarks, no captions."
        ),
        param_docs={
            "shot_label":              "Shot type label (CU / MS / 2-shot / wide / audience reaction / entrance wide).",
            "character_name":          "Display name of the speaker for this beat.",
            "role":                    "Role of the speaker (host / heroine / friend / expert / antagonist).",
            "gender":                  "Gender of the speaker from the Characters tab.",
            "framing":                 "Framing snippet derived from the shot type (cfg.KEYFRAME_FRAMING_BY_SHOT).",
            "head_orientation":        "Sentence describing the head pose (from cfg.TALKING_HEAD_ORIENTATIONS, or a free-form custom value).",
            "visual_pose_description": "Vivid starting visual description paragraph generated by the Dialogue Pre-Analysis Agent.",
        },
    ))

    STORE.register(PromptSpec(
        name="keyframe_pre_analysis_system",
        display_name="🎞 Keyframe pre-analysis — system prompt",
        description="Analyzes the dialogue line, performance style, and character attributes to describe the starting facial expression, posture, and gaze direction for the image generator.",
        default_template=(
            "You are a cinematic director directing an actor's starting pose for a talk-show segment.\n"
            "Given the character's details, the exact line of dialogue they are about to speak, "
            "their physical performance style, and the camera framing, write a detailed, highly descriptive, "
            "vivid single paragraph that details the character's exact starting posture, facial expression, "
            "mouth position (must be closed or slightly parted as they are about to speak), and gaze/eyeline direction.\n\n"
            "Hard rules:\n"
            "  • Write ONLY the physical visual description. Do NOT mention emotion labels (e.g. 'angry' or 'sad') — describe what the eyes, mouth, cheeks, and shoulders DO to show that feeling.\n"
            "  • Focus on maintaining consistency with their seated posture in the studio sofa.\n"
            "  • Be concise and clear. Output only the visual description paragraph."
        ),
        param_docs={},
    ))

    STORE.register(PromptSpec(
        name="keyframe_pre_analysis_user",
        display_name="🎞 Keyframe pre-analysis — user template",
        description="Payload for the keyframe pre-analysis pass.",
        default_template=(
            "Character: {character_name} ({role}, {gender})\n"
            "Framing: {framing}\n"
            "Head Orientation: {head_orientation}\n"
            "Dialogue line to deliver: \"{dialogue_text}\"\n"
            "Performance/Style guideline: {style_guideline}\n\n"
            "Generate the detailed starting visual description paragraph for this character."
        ),
        param_docs={
            "character_name":   "Display name of the speaker.",
            "role":             "Role of the speaker (host, expert, antagonist, heroine, friend).",
            "gender":           "Gender of the speaker.",
            "framing":          "Camera framing description.",
            "head_orientation": "Head orientation description.",
            "dialogue_text":     "The exact dialogue text of this part.",
            "style_guideline":   "The chosen physical performance style or custom style override.",
        },
    ))

    STORE.register(PromptSpec(
        name="narrative_style_system",
        display_name="🎭 Narrative style analyzer — system prompt",
        description="Drives the per-part narrative style analysis on the Talking heads tab. The LLM proposes 3 distinct physical-performance descriptions for every speaking part of an act — concrete body / head / gesture choices the actor will use while delivering that line. The chosen description is later fed into the talking-head video render prompt.",
        default_template=(
            "You are a TV-talk-show director coaching an actor's physical performance.\n"
            "For each speaking PART of an act, propose 3 DISTINCT concrete physical-performance "
            "descriptions the actor could use to deliver that line.\n\n"
            "Each description must focus ONLY on observable physical behaviour:\n"
            "  • HEAD movements (tilts, nods, glances, turns, eyeline)\n"
            "  • BODY posture (lean, shoulders, weight, hands position)\n"
            "  • GESTURES (hand movements, facial expression shifts, breathing)\n\n"
            "Hard rules:\n"
            "  • Write ONLY physical behaviour. Do NOT mention emotion labels like "
            "'happy' / 'sad' — describe what the body DOES that makes the feeling read.\n"
            "  • One sentence per description. Concrete and concise.\n"
            "  • The 3 options for the same part must be visibly different.\n"
            "  • Match the option to the actual line and the surrounding context.\n\n"
            "Output STRICT JSON wrapped in <styles>...</styles> — no preamble, no fences:\n"
            "[\n"
            "  {\"beat_idx\": N, \"part_idx\": M, \"options\": [\"…\", \"…\", \"…\"]},\n"
            "  …\n"
            "]\n"
            "beat_idx is the integer index in the input; part_idx is 1-based per beat. "
            "Cover EVERY part in the input."
        ),
        param_docs={},
    ))
    STORE.register(PromptSpec(
        name="narrative_style_user",
        display_name="🎭 Narrative style analyzer — user template",
        description="Per-act payload sent to the narrative style analyzer.",
        default_template=(
            "Act {act_number} of the talk show.\n\n"
            "Show context:\n"
            "  Topic / niche: {niche}\n"
            "  Tone: {tone}\n"
            "  Cast: {cast_names}\n\n"
            "Continuity from previous acts:\n"
            "{prior_summary}\n\n"
            "Speaking parts in this act (numbered as beat_idx.part_idx):\n"
            "{parts_block}\n\n"
            "For every part above, propose 3 distinct physical-performance descriptions. "
            "Return the <styles>...</styles> JSON."
        ),
        param_docs={
            "act_number":     "Computed: current act number (1–4).",
            "niche":          "Step 1 → Niche / pain point.",
            "tone":           "Step 1 → Tone preset.",
            "cast_names":     "Computed: cast list (names + roles).",
            "prior_summary":  "Computed: brief summary of earlier acts.",
            "parts_block":    "Computed: numbered list of all speaking parts in this act.",
        },
    ))
    STORE.register(PromptSpec(
        name="ensemble_shot_prompt",
        display_name="🛋 Ensemble shot — prompt builder",
        description="Composes the image prompt for the wide ensemble shot — all cast members seated on the studio sofa. Multi-reference image input: each character's portrait pose + the studio backdrop (cam2_guests). Used as a reference / establishing shot.",
        default_template=(
            "Wide establishing shot of a TV talk show studio interior, photo-realistic, "
            "broadcast quality.\n"
            "All cast members are visible together in the same frame:\n"
            "{cast_lines}\n\n"
            "IMPORTANT — IDENTITY + WARDROBE LOCK: Each reference image shows one of the "
            "characters fully rendered with their outfit. Reproduce every face, hair, body, "
            "and outfit EXACTLY as in their reference — same garments, same cut, same colors. "
            "Do not invent new people or change their appearance.\n\n"
            "STUDIO BACKDROP: The last reference image shows the empty studio set. "
            "Place the characters INTO that studio context — same backdrop, same lighting, "
            "same furniture.\n\n"
            "Arrangement on set: {arrangement}\n\n"
            "Style: photo-realistic, broadcast lighting, sharp focus, "
            "no text overlays, no watermarks, no captions."
        ),
        param_docs={
            "cast_lines":   "Computed: bullet list of cast members + role for the model to identify them.",
            "arrangement":  "Step 2 → Talking heads → Custom arrangement text (free-form, e.g., 'Hosts at the table on the left, heroine on the sofa middle, friends on either side, expert beside them, antagonist at the end').",
        },
    ))

    STORE.register(PromptSpec(
        name="logo_image_prompt",
        display_name="🎨 Logo image — prompt builder",
        description="Composes the image-generation prompt for the show's logo from Brand & Palette parameters.",
        default_template=(
            "Logo design for a TV talk show titled '{show_name}'.\n"
            "Style: {logo_style}.\n"
            "Era and aesthetic: {era}.\n"
            "Color palette: primary {primary}, secondary {secondary}, accent {accent}.\n"
            "Typography preset: {typography}.\n"
            "Composition: centered logo on a clean background, square 1:1 ratio, "
            "broadcast-quality graphic asset, no extraneous elements, no text "
            "outside the show name. {extra_description}"
        ),
        param_docs={
            "show_name":         "Step 1 → Show name",
            "logo_style":        "Step 2 → Brand → Logo style",
            "era":               "Step 2 → Brand → Era preset",
            "primary":           "Step 2 → Brand → Primary palette color (hex)",
            "secondary":         "Step 2 → Brand → Secondary palette color (hex)",
            "accent":            "Step 2 → Brand → Accent palette color (hex)",
            "typography":        "Step 2 → Brand → Typography preset",
            "extra_description": "Step 2 → Brand → Logo description (free-form)",
        },
    ))

    STORE.register(PromptSpec(
        name="suggest_palette",
        display_name="✨ Brand palette — AI suggestion",
        description="Asks the LLM to propose a 3-color brand palette for the show.",
        default_template=(
            "Propose a 3-color palette for a talk show with these traits:\n"
            "  Show name: {show_name}\n"
            "  Era / look: {era}\n"
            "  Tone: {tone}\n"
            "  Topic / niche: {niche}\n\n"
            "Return exactly this JSON shape (hex colors with #):\n"
            '{{"primary": "#RRGGBB", "secondary": "#RRGGBB", "accent": "#RRGGBB"}}'
        ),
        param_docs={
            "show_name": "Step 1 → Show name",
            "era": "Step 2 → Brand era preset",
            "tone": "Step 1 → Tone preset",
            "niche": "Step 1 → Niche / pain point",
        },
    ))

_register_defaults()
