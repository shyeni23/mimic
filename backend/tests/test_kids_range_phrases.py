"""
The kids/adult range decision, checked against docs/dataset/kids_range_phrases.json.

This rule decides whether to show CHILDREN'S clothing, so the negatives
matter more than the positives: 148 of the 404 utterances are ordinary adult
shopping speech that merely *sounds* child-related ("baby pink saree",
"girls night out dress", "kid leather gloves", "beti ki shaadi ke liye",
"beta, trial room kahan hai?" where beta is a term of address). Any one of
them routing to the kids range is a real bug, so they are asserted
individually rather than as an aggregate score.

Speech reaches this code through Whisper pinned to English
(config.whisper_language), which is why the Hindi here is romanized.

NOTE ON THE SCORE: the patterns in ui_commands were tuned against this same
file, so a pass here is a coverage check, not a measure of generalisation to
unseen phrasing. Its value is as a regression guard -- it fails loudly when
a future edit breaks a phrasing that used to work.
"""
import json
from pathlib import Path

import pytest

from app.services.agent.ui_commands import ui_command_turn

DATASET = Path(__file__).resolve().parents[2] / "docs" / "dataset" / "kids_range_phrases.json"

# label -> the department action it must produce. "ask" means Aria must come
# back with a question and change nothing.
EXPECTED = {
    "child_explicit": {"kids"},
    "child_with_age": {"kids"},
    "relative_no_age": {"ask"},
    "adult_relative": {"men", "women", "adult"},
    "for_self": {"adult", "men", "women"},
    "none": {"nothing"},
}
RANGE_TO_DEPT = {"kids": "kids", "mens": "men", "womens": "women"}


def _samples():
    data = json.loads(DATASET.read_text(encoding="utf-8"))
    return data["samples"]


def _route(text: str) -> str:
    """What the matcher does with this utterance, as a single token."""
    result = ui_command_turn(text, {}, {"page": "recommendations"}, None)
    if not result:
        return "nothing"
    depts = [a.get("payload", {}).get("department")
             for a in result["actions"] if a.get("type") == "set_department"]
    if depts:
        return depts[0]
    if "how old" in (result.get("reply") or "").lower():
        return "ask"
    # Some other rule answered (e.g. "the previous one"). That is fine here:
    # what must never happen is an unasked-for department change.
    return "nothing"


def _id(sample):
    return f"{sample['label']}-{sample['text'][:38]}"


ALL = _samples()
NEGATIVES = [s for s in ALL if s["label"] == "none"]


@pytest.mark.parametrize("sample", ALL, ids=_id)
def test_utterance_routes_correctly(sample):
    got = _route(sample["text"])
    if sample["label"] == "range_request":
        want = {RANGE_TO_DEPT[sample["range"]]}
    else:
        want = EXPECTED[sample["label"]]
    assert got in want, (
        f"{sample['text']!r} ({sample['lang']}) routed to {got!r}, expected one of {sorted(want)}")


@pytest.mark.parametrize("sample", NEGATIVES, ids=_id)
def test_adult_shopping_speech_never_opens_the_kids_range(sample):
    """The safety direction, asserted on its own so a failure is unmistakable."""
    assert _route(sample["text"]) != "kids", (
        f"{sample['text']!r} would have shown children's clothing")


def test_dataset_is_romanized_not_devanagari():
    """Whisper is pinned to English, so Devanagari samples would be dead
    weight that never matches anything a customer actually produces."""
    bad = [s["text"] for s in ALL if any("ऀ" <= ch <= "ॿ" for ch in s["text"])]
    assert not bad, f"Devanagari in the dataset: {bad[:3]}"


def test_dataset_has_enough_negatives():
    assert len(NEGATIVES) / len(ALL) > 0.30, (
        "negatives are what stop children's clothing leaking into adult results")
