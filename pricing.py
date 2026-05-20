"""
Pricing tables for cost estimation.
Prices are USD per 1 million tokens (input / output).
Update manually as needed — these are approximations.
"""

# Format: model_id -> (input_per_million, output_per_million)
PRICING_TABLE = {
    # Anthropic via OpenRouter (and direct)
    "anthropic/claude-opus-4": (15.00, 75.00),
    "anthropic/claude-sonnet-4": (3.00, 15.00),
    "anthropic/claude-haiku-4": (0.80, 4.00),
    "claude-opus-4-7": (15.00, 75.00),
    "claude-opus-4-6": (15.00, 75.00),
    "claude-sonnet-4-6": (3.00, 15.00),
    "claude-haiku-4-5-20251001": (0.80, 4.00),

    # OpenAI
    "openai/gpt-5": (10.00, 40.00),
    "openai/gpt-5-mini": (1.50, 6.00),

    # Google
    "google/gemini-2.5-pro": (3.50, 14.00),
    "google/gemini-2.5-flash": (0.30, 2.50),

    # Open-weight via OpenRouter
    "deepseek/deepseek-v3.1": (0.50, 1.50),
    "qwen/qwen-3-72b": (0.80, 2.40),
    "meta-llama/llama-4-70b": (0.70, 2.10),
    "x-ai/grok-4": (5.00, 20.00),
    "mistralai/mistral-large": (3.00, 9.00),

    # Curated 2026 OpenRouter test models (see config.OPENROUTER_TEST_MODELS)
    "anthropic/claude-opus-4.7-fast":                       (30.00, 150.00),
    "~anthropic/claude-haiku-latest":                       ( 1.00,   5.00),
    "x-ai/grok-4.3":                                         ( 1.25,   2.50),
    "openrouter/owl-alpha":                                  ( 0.00,   0.00),
    "google/gemini-3.1-flash-lite":                          ( 0.25,   1.50),
    "perceptron/perceptron-mk1":                             ( 0.15,   1.50),
    "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free":    ( 0.00,   0.00),
    "baidu/cobuddy:free":                                    ( 0.00,   0.00),
}


def get_pricing(model: str) -> tuple:
    """Return (input_price_per_mtok, output_price_per_mtok). Returns (0, 0) if unknown."""
    return PRICING_TABLE.get(model, (0.0, 0.0))


def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    """Estimate cost in USD for a given model and token counts."""
    in_price, out_price = get_pricing(model)
    cost = (input_tokens / 1_000_000) * in_price + (output_tokens / 1_000_000) * out_price
    return cost


def estimate_script_cost(model: str, duration_min: int, include_expand: bool = False) -> dict:
    """
    Estimate total cost for generating a full script.
    Returns dict with per-call breakdown and total.
    """
    # Heuristic estimates per call
    # Act calls: ~2500 input tokens (system + context), output depends on duration
    output_per_act = {30: 1500, 45: 2300, 60: 3100}.get(duration_min, 2300)
    input_per_act = 2500

    expand_input = 800
    expand_output = 400

    if model.lower() == "ollama":
        return {"per_call": [], "total_usd": 0.0, "currency": "USD"}

    calls = []
    if include_expand:
        c = estimate_cost(model, expand_input, expand_output)
        calls.append(("Expand instructions", c))

    for act_num in range(1, 5):
        c = estimate_cost(model, input_per_act, output_per_act)
        calls.append((f"Act {act_num}", c))

    total = sum(c for _, c in calls)
    return {"per_call": calls, "total_usd": total, "currency": "USD"}


def format_cost(cost_usd: float) -> str:
    """Format cost for display."""
    if cost_usd == 0:
        return "$0.00 (local)"
    if cost_usd < 0.01:
        return f"<$0.01"
    return f"${cost_usd:.2f}"
