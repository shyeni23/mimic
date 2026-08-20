"""
Structured, persistent conversation state -- what the agent has understood
about the customer's styling preferences so far (occasion, style, colors,
...), built up naturally over a multi-turn conversation instead of a
fixed-format questionnaire. Framework-agnostic: this module has no LangGraph
or LangChain dependency, so it survived the LangGraph -> LangChain migration
untouched in concept (only merge_preferences' signature changed, see below).

extract_prior_preferences() / this module's persistence model is unchanged:
the structured state is stored in the assistant turn's existing Supabase
`meta` jsonb column (see chat.py) -- no new table/column needed -- and read
back out at the start of the next turn. That's what makes it survive across
turns despite each HTTP request being otherwise stateless.

merge_preferences() DID change shape as part of that migration: the old
LangGraph tool-calling loop produced a *list of incremental deltas* (one per
update_preferences() tool call during a turn -- see the now-dormant
record_preference_update/get_preference_updates below, kept only because
tools.py's update_preferences tool still calls them). The new single-call
LangChain + Gemini pipeline (see graph.py) instead asks the model to return
its *complete, corrected* understanding every turn -- given what it already
knew -- so merge_preferences now overlays one full snapshot on top of the
prior one, rather than folding a list of deltas.
"""
import contextvars

_preference_updates: contextvars.ContextVar[list] = contextvars.ContextVar("preference_updates", default=None)


def start_turn():
    """Call once at the start of each agent turn to reset this turn's updates.
    NOTE: dormant since the LangGraph -> LangChain migration -- nothing in
    the current pipeline calls record_preference_update, so this queue stays
    empty. Kept for tools.py's update_preferences tool, unused for now."""
    _preference_updates.set([])


def record_preference_update(updates: dict):
    if not updates:
        return
    queue = _preference_updates.get()
    if queue is None:
        queue = []
        _preference_updates.set(queue)
    queue.append(updates)


def get_preference_updates() -> list[dict]:
    return _preference_updates.get() or []


def merge_preferences(prior: dict, new_state: dict) -> dict:
    """Overlays this turn's full conversation-state snapshot on top of what
    was already known: any field the model returned a real (non-empty) value
    for wins -- this is what makes corrections work (style 'traditional' ->
    'modern' simply overwrites) -- and any field the model left null/absent
    falls back to the prior value, so a quiet turn (or the model forgetting
    to restate something) can't accidentally erase it."""
    merged = dict(prior or {})
    for key, value in (new_state or {}).items():
        if value is not None and value != "" and value != []:
            merged[key] = value
    return merged


def extract_prior_preferences(history: list[dict]) -> dict:
    """Pulls the most recently persisted preferences dict out of Supabase
    conversation history (see chat.py, which stores it in the assistant
    turn's existing `meta` jsonb column -- no new table/column needed)."""
    for turn in reversed(history or []):
        if turn.get("role") == "assistant":
            meta = turn.get("meta") or {}
            if meta.get("preferences"):
                return meta["preferences"]
    return {}
