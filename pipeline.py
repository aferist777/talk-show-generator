"""
Generation pipeline: runs the 4 acts in sequence (plus optional expand step),
passing summaries forward for continuity.
"""
import re
import time
from typing import Callable, Optional
from llm_clients import LLMClient
import prompts


def expand_instructions(client: LLMClient, user_note: str) -> str:
    """Turn the user's brief idea into developed creative directives."""
    if not user_note.strip():
        return ""
    user = prompts.EXPAND_USER_TEMPLATE.format(user_note=user_note.strip())
    return client.complete(
        system=prompts.EXPAND_SYSTEM,
        user=user,
        max_tokens=600,
        temperature=0.6,
    ).strip()


def _extract_summary(act_text: str) -> str:
    """Pull <summary>...</summary> out of generated act text."""
    m = re.search(r"<summary>(.*?)</summary>", act_text, re.DOTALL | re.IGNORECASE)
    if m:
        return m.group(1).strip()
    # Fallback: take the last 3 sentences
    lines = [l.strip() for l in act_text.split("\n") if l.strip()]
    return " ".join(lines[-3:])[:600]


def _strip_summary(act_text: str) -> str:
    """Remove <summary>...</summary> from the final printed text."""
    return re.sub(r"<summary>.*?</summary>", "", act_text, flags=re.DOTALL | re.IGNORECASE).strip()


def build_context(form: dict, extra_instructions: str) -> str:
    """Render the shared context block from form values."""
    friend_results_lines = []
    for i, fr in enumerate(form.get("friend_results", []), 1):
        if fr.strip():
            friend_results_lines.append(f"  - Friend {i}: {fr.strip()}")
    friend_results_text = "\n".join(friend_results_lines) if friend_results_lines else "  (none)"

    ingredients = ", ".join([i for i in form.get("ingredients", []) if i.strip()])

    return prompts.CONTEXT_TEMPLATE.format(
        show_name=form.get("show_name", "Open Talk"),
        host1_name=form.get("host1_name", "Andrew"),
        host1_role=form.get("host1_role", "skeptic"),
        host2_name=form.get("host2_name", "Olivia"),
        host2_role=form.get("host2_role", "empathetic"),
        duration=form.get("duration", 45),
        tone=form.get("tone", "US daytime TV"),
        country_style=form.get("country_style", "US (Daytime Oprah / Dr. Phil style)"),
        dramatic_curve=form.get("dramatic_curve", "Standard Infomercial (Pain -> Discovery -> Proof -> Close)"),
        pacing_speed=form.get("pacing_speed", "Normal (conversational and standard TV cadence)"),
        language=form.get("language", "English"),
        niche=form.get("niche", "Weight loss"),
        anchor=form.get("anchor", "GLP-1"),
        ingredients=ingredients or "apple cider vinegar, lemon, baking soda",
        heroine_name=form.get("heroine_name", "Marina"),
        heroine_age=form.get("heroine_age", "46"),
        heroine_location=form.get("heroine_location", "small town"),
        heroine_profession=form.get("heroine_profession", "bookkeeper"),
        heroine_result=form.get("heroine_result", "lost 27 kg in 5 months"),
        friend_count=form.get("friend_count", 2),
        friend_results=friend_results_text,
        antagonist_type=form.get("antagonist_type", "Pharmaceutical industry representative"),
        antagonist_arc=form.get("antagonist_arc", "Smooth → aggressive → walkout"),
        product_name=form.get("product_name", "GLP-Activ"),
        currency=form.get("currency", "$"),
        anchor_price=form.get("anchor_price", "99"),
        offer_price=form.get("offer_price", "39"),
        bonus=form.get("bonus", "Buy 2 get 1 free"),
        urgency=form.get("urgency", "48 hours"),
        stock_limit=form.get("stock_limit", "8000"),
        extra_instructions=extra_instructions.strip() or "(none)",
    )


def _wait_while_paused(pause_check, cancel_check):
    """Block while pause_check() is True, polling every 200ms. Bails out
    immediately if cancel_check() becomes True."""
    if not pause_check:
        return
    while pause_check():
        if cancel_check and cancel_check():
            return
        time.sleep(0.2)


def generate_script(
    client: LLMClient,
    form: dict,
    extra_instructions: str = "",
    progress_callback: Optional[Callable[[str, int, int], None]] = None,
    cancel_check: Optional[Callable[[], bool]] = None,
    act_complete_callback: Optional[Callable[[str, str], None]] = None,
    pause_check: Optional[Callable[[], bool]] = None,
) -> str:
    """
    Run the four-act pipeline.

    progress_callback(stage_name, current_step, total_steps) — fired BEFORE each act.
    act_complete_callback(label, text) — fired AFTER each act with polished text.
    cancel_check() — return True to cancel.
    pause_check() — return True to pause; the pipeline waits between acts until
                    pause_check() returns False or cancel_check() goes True.
    """
    duration = int(form.get("duration", 45))
    timings = prompts.get_act_timings(duration)
    target_words = prompts.get_target_words(duration)
    high_anchor = form.get("anchor_price", "99")  # used in act 1 as reference
    language = form.get("language", "English")

    system = prompts.SYSTEM_PROMPT.format(language=language)
    context = build_context(form, extra_instructions)

    full_script_parts = []
    prior_summary = ""

    def step(name: str, idx: int):
        # Honor pause BEFORE starting the next act (LLM calls can't be paused
        # mid-flight; pausing only delays the next act from kicking off).
        _wait_while_paused(pause_check, cancel_check)
        if cancel_check and cancel_check():
            raise RuntimeError("Cancelled by user.")
        if progress_callback:
            progress_callback(name, idx, 4)

    # ─── ACT 1 ───
    step("Act 1: Opening & problem agitation", 1)
    act1_user = prompts.ACT1_PROMPT.format(
        act1_end_min=timings["act1_end_min"],
        currency=form.get("currency", "$"),
        high_anchor=high_anchor,
        anchor=form.get("anchor", "GLP-1"),
        target_words=target_words["act1"],
        context=context,
    )
    act1 = client.complete(system=system, user=act1_user, max_tokens=4096, temperature=0.85)
    prior_summary += "ACT 1 SUMMARY: " + _extract_summary(act1) + "\n"
    act1_clean = "# ACT 1 — OPENING\n\n" + _strip_summary(act1)
    full_script_parts.append(act1_clean)
    if act_complete_callback:
        act_complete_callback("Act 1 — Opening", act1_clean)

    # ─── ACT 2 ───
    step("Act 2: Heroine & friends", 2)
    act2_user = prompts.ACT2_PROMPT.format(
        act2_start_min=timings["act2_start_min"],
        act2_end_min=timings["act2_end_min"],
        target_words=target_words["act2"],
        prior_summary=prior_summary,
        context=context,
    )
    act2 = client.complete(system=system, user=act2_user, max_tokens=4096, temperature=0.85)
    prior_summary += "ACT 2 SUMMARY: " + _extract_summary(act2) + "\n"
    act2_clean = "# ACT 2 — HEROINE & FRIENDS\n\n" + _strip_summary(act2)
    full_script_parts.append("\n\n" + act2_clean)
    if act_complete_callback:
        act_complete_callback("Act 2 — Heroine & friends", act2_clean)

    # ─── ACT 3 ───
    step("Act 3: Expert & antagonist", 3)
    act3_user = prompts.ACT3_PROMPT.format(
        act3_start_min=timings["act3_start_min"],
        act3_end_min=timings["act3_end_min"],
        anchor=form.get("anchor", "GLP-1"),
        antagonist_type=form.get("antagonist_type", "Pharma rep"),
        antagonist_arc=form.get("antagonist_arc", "Smooth → aggressive → walkout"),
        target_words=target_words["act3"],
        prior_summary=prior_summary,
        context=context,
    )
    act3 = client.complete(system=system, user=act3_user, max_tokens=4096, temperature=0.85)
    prior_summary += "ACT 3 SUMMARY: " + _extract_summary(act3) + "\n"
    act3_clean = "# ACT 3 — EXPERT & ANTAGONIST\n\n" + _strip_summary(act3)
    full_script_parts.append("\n\n" + act3_clean)
    if act_complete_callback:
        act_complete_callback("Act 3 — Expert & antagonist", act3_clean)

    # ─── ACT 4 ───
    step("Act 4: Offer & close", 4)
    act4_user = prompts.ACT4_PROMPT.format(
        act4_start_min=timings["act4_start_min"],
        duration=duration,
        product_name=form.get("product_name", "GLP-Activ"),
        currency=form.get("currency", "$"),
        anchor_price=form.get("anchor_price", "99"),
        offer_price=form.get("offer_price", "39"),
        bonus=form.get("bonus", "Buy 2 get 1 free"),
        urgency=form.get("urgency", "48 hours"),
        stock_limit=form.get("stock_limit", "8000"),
        target_words=target_words["act4"],
        prior_summary=prior_summary,
        context=context,
    )
    act4 = client.complete(system=system, user=act4_user, max_tokens=4096, temperature=0.85)
    act4_clean = "# ACT 4 — THE OFFER\n\n" + _strip_summary(act4)
    full_script_parts.append("\n\n" + act4_clean)
    if act_complete_callback:
        act_complete_callback("Act 4 — The offer", act4_clean)

    # Assemble
    header = _build_header(form)
    return header + "\n\n" + "\n".join(full_script_parts)


def _build_header(form: dict) -> str:
    """Cover header for the script file."""
    lines = [
        "=" * 70,
        f"  {form.get('show_name', 'Open Talk').upper()}",
        f"  Episode: {form.get('niche', 'Weight loss')} — featuring {form.get('product_name', 'GLP-Activ')}",
        "=" * 70,
        "",
        f"  Duration target:  {form.get('duration', 45)} minutes",
        f"  Tone:             {form.get('tone', 'US daytime TV')}",
        f"  Language:         {form.get('language', 'English')}",
        "",
        "  CAST",
        f"    Host 1:       {form.get('host1_name')} ({form.get('host1_role')})",
        f"    Host 2:       {form.get('host2_name')} ({form.get('host2_role')})",
        f"    Heroine:      {form.get('heroine_name')}, {form.get('heroine_age')}, "
            f"{form.get('heroine_profession')} from {form.get('heroine_location')}",
        f"    Antagonist:   {form.get('antagonist_type')}",
        "",
        "  NOTICE",
        "    This script is a creative / educational artifact in the",
        "    infomercial-advertorial genre. It is intended for media-literacy",
        "    analysis and satirical deconstruction. It is not real advertising.",
        "",
        "=" * 70,
    ]
    return "\n".join(lines)
