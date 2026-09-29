"""
On-demand LLM rationale for a single recommendation (Module 3 explanation
upgrade).

The default explanation stays template-fill (inventory_search.py's `why`
list) -- zero latency, deterministic, good enough for "here are 3 options."
This file is for when a customer ASKS "why this one?" -- one real Groq call,
scoped to exactly one item, only paid when the customer actually wants the
richer answer.

Deliberately NOT wired into recommend_clothes' default path. Doing that for
every item in every recommendation would reintroduce exactly the latency
problem this session spent significant effort fixing (fast-path routing,
streaming, avoiding unnecessary structured-output calls) -- an always-on
LLM rationale is a ~3s tax per call, and recommend_clothes already returns
multiple items per call. Gating it behind explicit customer intent (a new
agent tool, see tools.py's explain_recommendation) means the cost is paid
exactly when the value is highest.

Uses a plain (non-structured) LLM call -- same reasoning as graph.py's fast
path: Groq's json_schema constrained decoding is the dominant latency
driver on this model, not generation length. A short, unconstrained text
response is meaningfully faster than a structured one for output this small.
"""
from app.services.agent.llm import get_agent_llm


def generate_llm_rationale(item: dict, user_context: dict, template_explanation: str = "") -> str | None:
    """One real Groq call, scoped to ONE item. Returns None on any failure
    (timeout, malformed response, LLM not configured) -- caller falls back
    to the existing template explanation, never blocks on this.
    """
    try:
        llm = get_agent_llm()  # plain, non-structured -- see module docstring
    except Exception as e:
        print(f"[llm_explain] LLM not available (non-fatal, using template explanation): {e}")
        return None

    context_bits = []
    if user_context.get("occasion"):
        context_bits.append(f"occasion: {user_context['occasion']}")
    if user_context.get("style"):
        context_bits.append(f"style preference: {user_context['style']}")
    if user_context.get("undertone"):
        context_bits.append(f"undertone: {user_context['undertone']}")
    if user_context.get("body_shape"):
        context_bits.append(f"body shape: {user_context['body_shape']}")
    context_line = "; ".join(context_bits) if context_bits else "no specific preferences stated yet"

    prompt = (
        f"A customer at a fashion store's smart mirror asked why you recommended this item. "
        f"Item: {item.get('name')} ({item.get('category')}, {item.get('color') or 'no specific color'}). "
        f"What we already know about her: {context_line}. "
        f"Base reasoning already computed: {template_explanation or 'general style match'}.\n\n"
        f"Write ONE natural, warm sentence (like a real stylist explaining her pick out loud) "
        f"that expands on WHY this works for her specifically. Don't just restate the base "
        f"reasoning verbatim -- make it sound like genuine styling advice, not a system log. "
        f"No preamble, no quotes, just the sentence."
    )

    try:
        result = llm.invoke(prompt)
        text = (result.content if hasattr(result, "content") else str(result)).strip()
        # Defensive: strip accidental quote-wrapping or leading labels the
        # model sometimes adds despite instruction.
        text = text.strip('"\'')
        if text.lower().startswith(("reason:", "explanation:", "rationale:")):
            text = text.split(":", 1)[1].strip()
        return text or None
    except Exception as e:
        print(f"[llm_explain] generation failed for item {item.get('id')} (non-fatal): {e}")
        return None
