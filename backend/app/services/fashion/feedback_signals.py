"""
Skip/dismiss feedback signal (Module 3's "smart" feedback loop).

recommend_items() already drops the EXACT items a customer skipped this
session (see inventory_search.py's dismissed_item_ids filter) -- that stops
the SAME dress from reappearing. It does NOT stop five near-identical
dresses from taking its place one after another, because exact-id exclusion
has no notion of "this whole direction isn't landing." That's the literal
bug report this file fixes: "customer skips 5 dresses in a row -> 6th still
shown" -- the 6th wasn't a repeat, it just looked like the first five.

This turns the skip PATTERN into an active ranking signal:
  - semantic: average embedding of skipped items -> candidates close to that
    centroid get penalized (rank-normalized across the candidate pool, same
    fix compatibility.py uses for the mixed text/image embedding space --
    see that file's module docstring for why absolute cosine isn't reliable
    here)
  - color / style_tags: an attribute that shows up repeatedly across skips
    is treated as an explicit "avoid this" signal, not just noise

Deliberately a SOFT signal (a penalty score, not a hard rule) -- a customer
skipping 5 red dresses doesn't mean a 6th red dress is unwantable, just that
it should rank behind alternatives. inventory_search.py decides how hard to
filter on top of the penalty.
"""
from collections import Counter

from app.services.fashion.compatibility import _cosine, _rank_normalize, _parse_embedding

# A single skip is too easy to misread (maybe she just didn't like the
# color, not the whole style) -- only trust the signal once it repeats.
MIN_SKIPS_FOR_SIGNAL = 2

# An attribute (color or style tag) needs to show up in at least this many
# skipped items before it's treated as a real "avoid this" signal.
ATTRIBUTE_REPEAT_THRESHOLD = 2


def compute_skip_signal(skipped_items: list[dict]) -> dict:
    """Build a negative-preference profile from this session's skipped items.

    Returns:
        {
            "centroid": avg embedding of skipped items, or None if too few/no embeddings,
            "avoid_colors": {color: count} for colors repeated >= threshold,
            "avoid_styles": {tag: count} for style_tags repeated >= threshold,
        }
    All-empty means "no reliable signal yet" -- callers should treat that as
    a no-op, not guess from a single data point.
    """
    if len(skipped_items) < MIN_SKIPS_FOR_SIGNAL:
        return {"centroid": None, "avoid_colors": {}, "avoid_styles": {}}

    embeddings = [_parse_embedding(i.get("embedding")) for i in skipped_items]
    embeddings = [e for e in embeddings if e]
    centroid = None
    if embeddings:
        dim = len(embeddings[0])
        centroid = [sum(e[i] for e in embeddings) / len(embeddings) for i in range(dim)]

    color_counts = Counter(
        (i.get("color") or "").lower().strip()
        for i in skipped_items if i.get("color")
    )
    style_counts: Counter = Counter()
    for i in skipped_items:
        for t in (i.get("style_tags") or []):
            style_counts[str(t).lower().strip()] += 1

    avoid_colors = {c: n for c, n in color_counts.items() if n >= ATTRIBUTE_REPEAT_THRESHOLD}
    avoid_styles = {s: n for s, n in style_counts.items() if n >= ATTRIBUTE_REPEAT_THRESHOLD}

    return {"centroid": centroid, "avoid_colors": avoid_colors, "avoid_styles": avoid_styles}


def apply_skip_penalty(candidates: list[dict], skip_signal: dict) -> list[dict]:
    """Score every candidate's resemblance to the skip pattern. Mutates and
    returns the SAME list (order unchanged) with a `skip_penalty` field
    added in [0, 0.9] -- 0 means "no resemblance to what she's been
    skipping," near 0.9 means "closely matches the pattern." Caller decides
    whether to filter, demote, or just log it.
    """
    if not candidates:
        return candidates
    centroid = skip_signal.get("centroid")
    avoid_colors = skip_signal.get("avoid_colors") or {}
    avoid_styles = skip_signal.get("avoid_styles") or {}

    if not centroid and not avoid_colors and not avoid_styles:
        for c in candidates:
            c["skip_penalty"] = 0.0
        return candidates

    # Rank-percentile cosine to the skip centroid, computed across THIS
    # candidate pool -- same modality-mismatch fix as compatibility.py's
    # _semantic_compatibility. High cosine to the skip centroid = resembles
    # what she rejected, so the raw percentile rank IS the penalty directly
    # (no inversion needed, unlike the "higher is better" anchor case).
    semantic_penalties = [0.0] * len(candidates)
    if centroid:
        raw = []
        for c in candidates:
            emb = _parse_embedding(c.get("embedding"))
            raw.append(_cosine(emb, centroid) if emb else 0.0)
        semantic_penalties = _rank_normalize(raw)

    for c, sem_pen in zip(candidates, semantic_penalties):
        color = (c.get("color") or "").lower().strip()
        tags = {str(t).lower().strip() for t in (c.get("style_tags") or [])}

        color_hit = color in avoid_colors
        style_hit_count = len(tags & avoid_styles.keys())

        # Semantic is the broadest signal (catches pattern/silhouette a
        # color/tag rule can't); color/style are sharp boosts for the
        # literal "keeps skipping teal" case.
        penalty = 0.5 * sem_pen
        if color_hit:
            penalty += 0.25
        if style_hit_count:
            penalty += min(0.25, 0.1 * style_hit_count)

        c["skip_penalty"] = round(min(penalty, 0.9), 3)

    return candidates
