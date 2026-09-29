"""
"Recommend only what I asked for" -- the customer's own examples (2026-09-29):

  "I want a party outfit"        -> ask first, then clothes only
  "Suggest heels also"           -> clothes AND footwear, nothing else
  "Suggest me a dress, bag,
   and heels"                    -> exactly those three, no watch/belt

Two layers are covered here: parse_requested_items (free text -> categories)
and recommend_styled_look's `include`/`strict_occasion` handling. The second
stubs _fill_group, so these tests never touch Supabase or FashionCLIP -- they
assert the PLAN (which sections get built), which is the part that must not
regress; retrieval quality is verified live instead.
"""
from unittest.mock import patch

from app.services.fashion.inventory_search import parse_requested_items
from app.services.fashion.styled_look import recommend_styled_look

CLOTHES = {"top", "bottom", "dress"}


class TestParseRequestedItems:
    def test_customers_own_examples(self):
        assert set(parse_requested_items("I want a party outfit")) == CLOTHES
        assert set(parse_requested_items("Suggest heels also")) == CLOTHES | {"footwear"}
        assert parse_requested_items("Suggest me a dress, bag, and heels") == ["dress", "footwear", "bag"]

    def test_clothes_only_variants(self):
        for text in ("only clothes", "just the clothes please", "nothing else", "clothes only"):
            assert set(parse_requested_items(text)) == CLOTHES, text

    def test_everything(self):
        got = parse_requested_items("everything")
        assert set(got) >= CLOTHES | {"footwear", "bag", "watch", "jewelry", "accessory"}

    def test_also_adds_to_clothes_but_naming_garments_does_not(self):
        # "heels also" = clothes + heels; "a dress and heels" = just those two.
        assert set(parse_requested_items("with a bag as well")) == CLOTHES | {"bag"}
        assert parse_requested_items("a dress and heels") == ["dress", "footwear"]

    def test_accessories_covers_both_catalog_categories(self):
        got = parse_requested_items("accessories")
        assert set(got) == {"accessory", "jewelry"}

    def test_no_preference_returns_none(self):
        assert parse_requested_items("hello how are you") is None
        assert parse_requested_items("") is None
        assert parse_requested_items(None) is None


def _fake_fill(**kw):
    cat = kw["category"] or "top"
    return [
        {"id": f"{cat}-{kw['wording']}-{i}", "name": f"Fake {kw['wording']} {i}",
         "category": cat, "color": "teal", "occasion": ["party"], "gender": "female"}
        for i in range(3)
    ]


def _look(**kw):
    with patch("app.services.fashion.styled_look._fill_group", side_effect=_fake_fill):
        return recommend_styled_look(
            depth="medium", undertone="warm", body_shape="hourglass", gender="female", **kw,
        )


class TestIncludeFiltersTheLook:
    def test_full_look_when_nothing_requested(self):
        cats = [s["category"] for s in _look()["sections"]]
        assert CLOTHES.issubset(set(cats))
        assert {"footwear", "bag", "watch", "jewelry", "accessory"}.issubset(set(cats))
        assert "occasion" in cats  # "Outfits by occasion" only on the full look

    def test_exactly_the_three_she_named(self):
        r = _look(include=["dress", "bag", "footwear"])
        assert [s["category"] for s in r["sections"]] == ["dress", "footwear", "bag"]
        # nothing she didn't ask for, including the occasion row
        assert "occasion" not in [s["category"] for s in r["sections"]]
        assert {i["category"] for i in r["results"]} == {"dress", "footwear", "bag"}

    def test_heels_also_keeps_clothes(self):
        r = _look(include=parse_requested_items("suggest heels also"))
        assert {s["category"] for s in r["sections"]} == CLOTHES | {"footwear"}

    def test_single_category_request(self):
        r = _look(include=["watch"])
        assert [s["category"] for s in r["sections"]] == ["watch"]

    def test_strict_occasion_reaches_every_group(self):
        calls = []

        def spy(**kw):
            calls.append(kw)
            return _fake_fill(**kw)

        with patch("app.services.fashion.styled_look._fill_group", side_effect=spy):
            recommend_styled_look(depth="medium", undertone="warm", body_shape="hourglass",
                                  gender="female", occasion="party", strict_occasion=True,
                                  include=["dress"])
        assert calls, "no groups were built"
        assert all(c["strict_occasion"] for c in calls)
        assert all(c["occasion"] == "party" for c in calls)
