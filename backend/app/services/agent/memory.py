"""
Conversation memory management (G4).

Provides sliding-window history with automatic summarization of older turns,
preventing context loss in long conversations while staying within the LLM's
token budget and Groq's rate limits.

Strategy:
  - Keep the most recent WINDOW_SIZE turns as verbatim messages (the LLM needs
    these for reference resolution — "the first one", "not that, something softer")
  - Older turns are condensed into a brief digest: one line per exchange capturing
    what the customer said and what was discussed, without the full back-and-forth
  - The accumulated preferences dict (already built by merge_preferences every turn)
    carries structured facts forward regardless of the window — occasion, colors,
    budget, etc. are never lost even if the turn they came from scrolls out of the
    raw window
  - The digest + preferences together give the LLM full continuity without sending
    40 raw turns on a long conversation

No extra LLM call — the digest is built by simple extraction (user turns only,
truncated to key content), keeping latency and rate-limit impact at zero.
"""

# Bumped 10 -> 24: the persona now allows off-topic chat, jokes, and
# extended conversation, which use turns faster than the tight fashion-only
# path did. gpt-oss-120b's 128K context handles this trivially; 24 raw
# turns + digest is still well under 20K prompt tokens.
WINDOW_SIZE = 24


def _summarize_turn(turn: dict) -> str | None:
    """Extract a one-line summary from a single conversation turn.
    Only user turns are summarized — assistant responses are implicit
    in the flow and the preferences already capture what was extracted."""
    if turn.get("role") != "user":
        return None
    content = (turn.get("content") or "").strip()
    if not content:
        return None
    if len(content) > 120:
        content = content[:117] + "..."
    return f"- Customer: {content}"


def build_history_digest(older_turns: list[dict]) -> str:
    """Build a compact text digest from turns that have scrolled out of the
    raw window. Returns a string block to prepend to the system prompt."""
    lines = []
    for turn in older_turns:
        line = _summarize_turn(turn)
        if line:
            lines.append(line)
    if not lines:
        return ""
    return (
        "EARLIER IN THIS CONVERSATION (condensed — the full details are in "
        "the 'already known' preferences block above, this is just for conversational "
        "continuity so you remember what was discussed):\n"
        + "\n".join(lines)
    )


def window_history(full_history: list[dict]) -> tuple[str, list[dict]]:
    """Split conversation history into a digest string and a recent-turns list.

    Returns:
        (digest, recent_turns) where digest is empty string if history fits
        in the window, and recent_turns is the verbatim tail to send as messages.
    """
    if len(full_history) <= WINDOW_SIZE:
        return "", full_history

    older = full_history[:-WINDOW_SIZE]
    recent = full_history[-WINDOW_SIZE:]
    digest = build_history_digest(older)
    return digest, recent
