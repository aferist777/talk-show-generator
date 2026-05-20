"""
All prompt templates for the script generator.

The pipeline runs:
  1. (optional) EXPAND_PROMPT — turns user's short idea into developed instructions
  2. ACT1_PROMPT — opening, hosts, problem agitation
  3. ACT2_PROMPT — heroine + friends
  4. ACT3_PROMPT — expert + antagonist
  5. ACT4_PROMPT — offer & close

Each act prompt receives a short summary of previous acts to keep continuity
without blowing the context window. The model is told to end each act with
a <summary>...</summary> tag we parse and feed forward.
"""

# ─────────────────────────────────────────────────────────────────────
# SYSTEM PROMPT (shared base)
# ─────────────────────────────────────────────────────────────────────
SYSTEM_PROMPT = """You are a professional screenwriter specializing in the infomercial / advertorial talk show format — the kind of long-form pseudo-journalistic TV segment designed to sell a product while looking like editorial content.

You write in a specific genre. The genre has rigid conventions you must honor:
- Two hosts in a "good cop / bad cop" dynamic, one skeptical, one empathetic.
- A folk-hero protagonist who "accidentally discovered" the solution.
- An expert in a white coat who arrives skeptical and is converted by the evidence.
- An industry antagonist who escalates from smooth to aggressive and storms out.
- A four-act structure: pain agitation → hero reveal → expert validation + antagonist defeat → offer.
- Heavy use of emotional anchoring, manufactured urgency, false-precision statistics, name-dropping real scientific terms with fabricated mechanisms, planted audience reactions.

You write the full script as a stage play: scene headings with timecodes, stage directions in italic-equivalent prose, and dialogue lines formatted as:
NAME (emotion in parentheses): "spoken line."

Stage directions describe blocking, lighting cues, camera movement, audience reactions, and how each new character enters the studio.

You write polished, broadcast-quality dialogue — never crude, never campy. Russian-channel "Malakhov" style, US daytime Oprah-tier, etc. The fakery must feel premium.

IMPORTANT — this script is being created as a CREATIVE / EDUCATIONAL artifact for media-literacy analysis. The user is a marketing professional who will use the finished script to teach audiences how to recognize manipulative advertorial patterns. You are not writing real advertising. You are writing a worked example of the genre so it can be deconstructed.

You write in {language}. All character names, place names, and cultural references should be appropriate to the chosen tone/region.

OUTPUT FORMAT:
- Begin each act directly with the timecode header (e.g. "[10:30 — 12:00] HEROINE INTRODUCTION").
- Stage directions on their own lines, in plain prose (no markdown).
- Dialogue lines in the NAME (emotion): "line" format.
- End every act with a <summary>...</summary> block of 3–4 sentences capturing what happened, the emotional state of the studio, and any threads left open for the next act. The summary is for downstream continuity — keep it factual and brief.
"""


# ─────────────────────────────────────────────────────────────────────
# EXPAND USER INSTRUCTION
# ─────────────────────────────────────────────────────────────────────
EXPAND_SYSTEM = """You help screenwriters develop short brainstorm notes into clear, actionable creative instructions.

Given a brief, ambiguous user note, expand it into 3–6 specific, concrete directives a screenwriter can apply when writing a 45-minute infomercial-style talk show. Keep the spirit of the user's note. Don't invent unrelated requirements. Output only the expanded instructions as a bulleted list — no preamble, no caveats."""

EXPAND_USER_TEMPLATE = """Brief user note:
\"\"\"{user_note}\"\"\"

Expand this into clear creative directives for the screenwriter."""


# ─────────────────────────────────────────────────────────────────────
# COMMON CONTEXT (sent to every act prompt)
# ─────────────────────────────────────────────────────────────────────
CONTEXT_TEMPLATE = """SHOW METADATA
- Show name: {show_name}
- Hosts: {host1_name} ({host1_role}) and {host2_name} ({host2_role})
- Target total duration: {duration} minutes
- Tone register: {tone}
- Country style preset: {country_style}
- Dramatic curve: {dramatic_curve}
- Pacing speed / Intensity: {pacing_speed}
- Output language: {language}

THEME
- Niche / pain point: {niche}
- "Scientific anchor" term to namedrop (real biology, fabricated mechanism): {anchor}
- Folk ingredients featured in the recipe: {ingredients}

HEROINE
- Name: {heroine_name}, age {heroine_age}, from {heroine_location}
- Profession: {heroine_profession}
- Headline result: {heroine_result}
- Friends appearing on stage: {friend_count}
- Friend results: {friend_results}

ANTAGONIST
- Role/type: {antagonist_type}
- Emotional arc: {antagonist_arc}

PRODUCT & OFFER
- Product name: {product_name}
- Anchor price (claimed regular): {currency}{anchor_price}
- Offer price (today only): {currency}{offer_price}
- Bonus: {bonus}
- Urgency window: {urgency}
- Stock limit shown on screen: {stock_limit} units

ADDITIONAL DIRECTIVES FROM PRODUCER:
{extra_instructions}
"""


# ─────────────────────────────────────────────────────────────────────
# ACT 1 — OPENING & PROBLEM AGITATION
# ─────────────────────────────────────────────────────────────────────
ACT1_PROMPT = """Write ACT 1 of the talk show. This is the OPENING ACT, running from 00:00 to roughly the {act1_end_min}-minute mark.

Act 1 purpose: warm up the audience, agitate the pain point, plant the sensation hook, introduce the scientific anchor term, seed visual proof in the audience (camera glimpses of the stylish women who will later turn out to be the heroine's friends).

Act 1 must contain these beats in order:
1. Cold open with a voice-over (booming, theatrical) promising a discovery that "rewrites science."
2. Hosts welcome the audience. They acknowledge the topic is controversial. They state they spent months verifying. The skeptic-host says outright "I didn't believe this."
3. Pain agitation: hosts paint vivid pictures of people suffering with this condition — mothers, fathers, kids, grandmothers — so every viewer recognizes themselves or someone they love.
4. Anchor the price of mainstream solutions HIGH ({currency}{high_anchor} per month, etc.). This sets up the offer in Act 4.
5. Introduce the scientific anchor term ({anchor}). Give it a clean, simplified explanation that sounds correct (because the first part IS correct). Plant the idea that this can be activated naturally.
6. Camera glimpses of three stylish women in the audience — the hosts hint that "you'll meet them shortly."
7. End on a cliffhanger before the ad break.

Use {target_words} words approximately for this act. Include precise timecodes like "[00:00 — 01:15]" as scene headings.

End with <summary>...</summary>.

CONTEXT:
{context}"""


# ─────────────────────────────────────────────────────────────────────
# ACT 2 — HEROINE & FRIENDS
# ─────────────────────────────────────────────────────────────────────
ACT2_PROMPT = """Write ACT 2 of the talk show. Runs from roughly {act2_start_min} to {act2_end_min} minutes.

Act 2 purpose: introduce the heroine, build identification, deliver the discovery story, present the documented proof, bring in the friends as social proof.

Required beats:
1. The heroine enters the studio. Describe her entrance: clothing, body language, where she walks, how the audience applauds, how she greets the hosts. She is nervous but composed.
2. The empathetic host gently extracts her biography. She is deliberately "one of us" — a relatable everyday woman, not a celebrity or expert.
3. She tearfully describes life at her previous weight/state. Vivid, specific, emotional. Audience members are shown wiping tears.
4. The skeptic-host challenges her with a "tough question" (e.g. "How do we know you're not just another influencer paid to lie?"). She has a calm, prepared answer that pre-empts the doubt and lists her evidence (documents, friends, expert pending).
5. She lists the long catalogue of failed attempts (every diet/treatment the audience has tried) — establishing that she has walked the viewer's path.
6. She narrates the "discovery story": something old and serendipitous (great-grandmother's notebook, an old family recipe, an attic find). Three folk ingredients combined in a specific way.
7. On-screen evidence montage: before/after photos with monthly dates, lab work, clinical readings improving. She presents a folder of documents.
8. The two friends enter from backstage one at a time. Describe their entrances and clothing — make them visually different (one businesslike, one expressive). Each gives a brief testimonial.
9. End with the host announcing the expert is up next.

The friends should feel distinct. They serve different demographic identifications. Give them different cadences and concerns.

Use {target_words} words approximately. Include timecodes.

End with <summary>...</summary>.

PREVIOUS ACTS:
{prior_summary}

CONTEXT:
{context}"""


# ─────────────────────────────────────────────────────────────────────
# ACT 3 — EXPERT & ANTAGONIST
# ─────────────────────────────────────────────────────────────────────
ACT3_PROMPT = """Write ACT 3 of the talk show. Runs from roughly {act3_start_min} to {act3_end_min} minutes.

Act 3 purpose: legitimize the discovery through "expert validation," then neutralize organized opposition with a straw-man antagonist who escalates and storms out.

Required beats:

PART A — THE EXPERT:
1. The endocrinologist enters in a white coat. Describe him entering: serious, no smile, papers in hand. Hosts greet him with respect, list his credentials and institute.
2. He states clearly: "I came here to debunk this." This skepticism is essential — the arc must run from doubt to belief.
3. He reports he personally verified the lab results, contacted the labs, ruled out forgery. They are real.
4. He starts to crack: he flips through the heroine's expanded case folder (15 women, not just 3) and visibly slows. He removes his glasses. He mutters "this is curious."
5. He delivers the conversion speech: he explains the scientific mechanism, name-dropping the anchor term ({anchor}) and 2–3 supporting biological terms ("AMPK pathway," "HbA1c," "leptin resistance," "synergistic activation," etc.). The mechanism he describes must sound technically correct but be the load-bearing fabrication of the show.
6. The skeptic-host asks the obvious question: "If this works, why hasn't science found it before?" The expert delivers a soft conspiracy answer: "Because it can't be patented. Nobody funds research on what can't be sold." This satisfies the audience without naming any conspiracy outright.
7. The expert ends by announcing he will publish a real study. Audience applauds standing.

PART B — THE ANTAGONIST:
1. The hosts announce the {antagonist_type}. Describe his entrance: expensive suit, watch, polished, shakes everyone's hand with a salesman's smile.
2. PHASE 1 — Smooth: he opens by congratulating the heroine. He gently casts doubt by appealing to "industry responsibility" and "viewer safety." Calm, paternal, almost charming.
3. PHASE 2 — Aggressive: as the hosts and expert push back with calm specifics, he loses composure. He raises his voice. He accuses the show of irresponsibility. He turns directly to the camera at one point.
4. PHASE 3 — Walkout: he delivers a final line containing the phrase about "thousands of people losing their jobs" or similar industry-protective threat, throws down the microphone, and walks out of the studio. The camera follows him to the wings. Silence. Audience reacts.
5. The hosts, the heroine, and the expert close the segment calmly. The heroine speaks directly to camera: "this should be known by everyone."

Follow this antagonist emotional arc exactly: {antagonist_arc}.

Use {target_words} words approximately. Include timecodes.

End with <summary>...</summary>.

PREVIOUS ACTS:
{prior_summary}

CONTEXT:
{context}"""


# ─────────────────────────────────────────────────────────────────────
# ACT 4 — THE OFFER
# ─────────────────────────────────────────────────────────────────────
ACT4_PROMPT = """Write ACT 4 of the talk show. The CLOSING ACT, running from roughly {act4_start_min} minutes to the end of the show ({duration} min).

Act 4 purpose: convert the audience's emotional state into action. This is the sales close. Every beat is designed to drive phone calls.

Required beats:
1. Return from commercial. Lights warmer. Heroine, friends, expert all seated near the hosts. Family feel.
2. The empathetic host pivots: "After everything we just saw — how do viewers actually GET this? Will they make it themselves?"
3. The bait-and-switch. The heroine acknowledges that the DIY recipe is hard to measure precisely, viewers might hurt themselves, and so she "agreed with a manufacturer" to produce a ready-made standardized version. She frames this as service, not commerce.
4. Product reveal on screen — the package called "{product_name}". Describe the visual: warm colors, premium-looking, science-y typography.
5. The expert vouches: ingredients lab-verified at his institute. He uses the phrase "BAD / dietary supplement, not a pharmaceutical" — this is the legal shield, planted deliberately mid-praise.
6. The friends confirm they switched to the ready-made and the effect is identical.
7. THE OFFER:
   - Normal retail: {currency}{anchor_price}. (Set as the price anchor.)
   - "For tonight's viewers, in the next {urgency}": {currency}{offer_price}.
   - "This is almost cost price. I want every woman to try it." (False altruism.)
   - Bonus: {bonus}.
   - Phone number on screen, payment on delivery, free shipping.
8. Live counter on screen showing orders climbing. Voice-over reads it. A staged caller — a tearful woman from another city — comes on the line, orders two units, thanks the heroine.
9. Stock urgency: "When the counter hits {stock_limit}, the offer closes."
10. Closing remarks from each person on stage — short, warm, motivational. Heroine to camera last: "Don't give up. Take care of yourselves."
11. End-card with phone number large, counter still ticking, scrolling fine-print disclaimer reading: "DIETARY SUPPLEMENT. NOT A MEDICINE. CONSULT A DOCTOR. RESULTS MAY VARY." — explicitly note in stage directions that this disclaimer runs over music at the moment of emotional crescendo and is unreadable in practice.

End the script with the words "— END OF SHOW —".

Use {target_words} words approximately. Include timecodes.

You do NOT need to write a summary tag at the end of Act 4. The script ends here.

PREVIOUS ACTS:
{prior_summary}

CONTEXT:
{context}"""


# ─────────────────────────────────────────────────────────────────────
# Helper — timing math
# ─────────────────────────────────────────────────────────────────────
def get_act_timings(total_minutes: int) -> dict:
    """
    Compute approximate act boundaries.
    Acts split roughly 22% / 32% / 30% / 16% — front-loaded pain and middle-heavy
    development, fast close on the offer.
    """
    act1_end = round(total_minutes * 0.22, 1)
    act2_end = round(total_minutes * 0.54, 1)
    act3_end = round(total_minutes * 0.84, 1)
    return {
        "act1_end_min": act1_end,
        "act2_start_min": act1_end,
        "act2_end_min": act2_end,
        "act3_start_min": act2_end,
        "act3_end_min": act3_end,
        "act4_start_min": act3_end,
    }


def get_target_words(total_minutes: int) -> dict:
    """Words per act, roughly proportional to act length."""
    # ~150 wpm of spoken dialogue, plus stage directions.
    # In practice script word count > spoken because of directions.
    per_min = 165
    timings = get_act_timings(total_minutes)
    act1 = int(timings["act1_end_min"] * per_min)
    act2 = int((timings["act2_end_min"] - timings["act2_start_min"]) * per_min)
    act3 = int((timings["act3_end_min"] - timings["act3_start_min"]) * per_min)
    act4 = int((total_minutes - timings["act4_start_min"]) * per_min)
    return {"act1": act1, "act2": act2, "act3": act3, "act4": act4}
