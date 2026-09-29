"""
Post-scan "styled look": every category broken into garment TYPES with 2-3
options each -- "Heels & Wedges: 3 options", "Kurtas & Kurtis: 3 options",
"Clutches: 3 options" -- plus an "Outfits by occasion" section (Formal,
Party, Casual, ...) with 2-3 outfit pieces each. This is what the customer
asked for verbatim: "if it recommends formal wear, show 2-3 different
formal outfits; if it recommends a dress type, show 2-3 of that type".

WHY NAME KEYWORDS: inventory has no article-type column (the source
dataset's articleType was never captured; style_tags is empty), but the
Myntra-derived product names always carry the type word ("Portia Women
Maroon Sandals", "Murcia Women Teal Blue Handbag"). Coverage measured live
on the women's+unisex catalog before choosing these groups -- e.g. kurta
1,678, heels 426, handbag 1,053, clutch 212. Types with no stock (bodycon 0,
maxi 0, palazzo 0) are deliberately NOT in the plan: a group is only ever
shown when real items exist for it.

RETRIEVAL per group (hybrid, see _fill_group):
  1. FashionCLIP + pgvector, query worded for the type + the scan profile
     (department, palette, body-shape hint), post-filtered by the type
     keywords so the row is truthful, not just CLIP's nearest guess.
  2. If that leaves fewer than `per_group`, a direct name-keyword query
     (ilike) ranked by palette colour + occasion fills the rest -- so a
     group can't come back short because of HNSW post-filter recall (see
     migrations section 7) or a sparse type.
"""
from concurrent.futures import ThreadPoolExecutor

from app.db.supabase_client import get_supabase
from app.services.fashion.catalog_filters import apply_catalog_filters, normalize_gender
from app.services.fashion.inventory_search import (
    CATEGORY_LABELS, body_shape_hint, semantic_search, _dedupe_by_name,
    ALL_ITEM_CATEGORIES, normalize_category,
)
from app.services.vision.skin_tone import recommended_palette

_GARMENT_CATEGORIES = ("top", "bottom", "dress")

# (group label, name keywords [any], excluded keywords [none], CLIP wording)
_WOMEN_PLAN = [
    ("dress", 3, [
        ("Sarees", ["sari", "saree"], [], "saree"),
        ("Dresses", ["dress"], ["sari", "saree"], "dress"),
        ("Shift & A-line dresses", ["shift", "a-line", "a line"], [], "A-line shift dress"),
    ]),
    ("top", 4, [
        ("Kurtas & Kurtis", ["kurta", "kurti"], [], "kurta"),
        ("Tops & Tunics", ["tunic", " top"], [], "top"),
        ("Shirts", ["shirt"], ["t-shirt", "tshirt", "sweatshirt"], "shirt"),
        ("T-shirts", ["t-shirt", "tshirt"], [], "t-shirt"),
        ("Sweaters & Jackets", ["sweater", "sweatshirt", "jacket", "cardigan", "hoodie"], [], "jacket"),
    ]),
    ("bottom", 4, [
        ("Jeans & Jeggings", ["jeans", "jeggings"], [], "jeans"),
        ("Leggings & Capris", ["leggings", "capri"], [], "leggings"),
        ("Skirts", ["skirt"], [], "skirt"),
        ("Trousers", ["trousers"], ["track"], "trousers"),
        ("Ethnic bottoms", ["churidar", "salwar", "patiala"], [], "salwar"),
        ("Shorts", ["shorts"], [], "shorts"),
    ]),
    ("footwear", 5, [
        ("Heels & Wedges", ["heels", "wedges", "pumps"], [], "high heels"),
        ("Flats & Ballerinas", ["flats", "ballerinas"], [], "flat shoes"),
        ("Sandals", ["sandals"], [], "sandals"),
        ("Casual & Sports shoes", ["casual shoes", "sports shoes", "sneakers"], [], "sneakers"),
        ("Flip flops & Slippers", ["flip flops", "slippers"], [], "flip flops"),
        ("Boots", ["boots"], [], "boots"),
    ]),
    ("bag", 4, [
        ("Handbags", ["handbag"], [], "handbag"),
        ("Clutches", ["clutch"], [], "clutch bag"),
        ("Sling bags", ["sling"], [], "sling bag"),
        ("Totes", ["tote"], [], "tote bag"),
        ("Backpacks", ["backpack"], [], "backpack"),
        ("Wallets", ["wallet"], [], "wallet"),
    ]),
    ("watch", 2, [
        ("Analog watches", ["analog", "dial"], ["chronograph", "digital"], "analog watch"),
        ("Chronographs", ["chronograph"], [], "chronograph watch"),
        ("Digital watches", ["digital"], [], "digital watch"),
    ]),
    ("jewelry", 4, [
        ("Earrings", ["earrings"], [], "earrings"),
        ("Necklaces & Pendants", ["necklace", "pendant"], [], "necklace"),
        ("Bangles & Bracelets", ["bangle", "bracelet"], [], "bracelet"),
        ("Rings", ["ring"], ["earring"], "ring"),
        ("Jewellery sets", [" set"], [], "jewellery set"),
    ]),
    ("accessory", 3, [
        ("Belts", ["belt"], [], "belt"),
        ("Sunglasses", ["sunglasses"], [], "sunglasses"),
        ("Scarves", ["scarf", "scarves"], [], "scarf"),
        ("Caps", ["cap"], [], "cap"),
        ("Socks", ["socks"], [], "socks"),
    ]),
]

_MEN_PLAN = [
    ("top", 4, [
        ("T-shirts", ["t-shirt", "tshirt"], [], "t-shirt"),
        ("Shirts", ["shirt"], ["t-shirt", "tshirt", "sweatshirt"], "shirt"),
        ("Kurtas", ["kurta"], [], "kurta"),
        ("Jackets & Sweaters", ["jacket", "sweater", "sweatshirt", "blazer", "hoodie"], [], "jacket"),
    ]),
    ("bottom", 4, [
        ("Jeans", ["jeans"], [], "jeans"),
        ("Trousers", ["trousers", "chinos"], ["track"], "trousers"),
        ("Shorts", ["shorts"], [], "shorts"),
        ("Track pants", ["track"], [], "track pants"),
    ]),
    ("footwear", 4, [
        ("Casual shoes", ["casual shoes", "sneakers"], [], "casual shoes"),
        ("Sports shoes", ["sports shoes", "running"], [], "sports shoes"),
        ("Formal shoes", ["formal shoes", "formal"], [], "formal shoes"),
        ("Sandals & Flip flops", ["sandals", "flip flops", "slippers"], [], "sandals"),
    ]),
    ("bag", 3, [
        ("Backpacks", ["backpack"], [], "backpack"),
        ("Wallets", ["wallet"], [], "wallet"),
        ("Laptop & Messenger bags", ["laptop", "messenger", "duffle"], [], "messenger bag"),
    ]),
    ("watch", 2, [
        ("Analog watches", ["analog", "dial"], ["chronograph", "digital"], "analog watch"),
        ("Chronographs", ["chronograph"], [], "chronograph watch"),
        ("Digital watches", ["digital"], [], "digital watch"),
    ]),
    ("accessory", 3, [
        ("Belts", ["belt"], [], "belt"),
        ("Sunglasses", ["sunglasses"], [], "sunglasses"),
        ("Caps", ["cap"], [], "cap"),
        ("Ties", ["tie"], [], "tie"),
    ]),
]

# Occasion groups -- garments only, from the real occasion tags in inventory.
_OCCASION_GROUPS = [
    ("Formal", "formal"), ("Party", "party"), ("Casual", "casual"),
    ("Ethnic & Wedding", "ethnic"), ("Office", "office"),
]

_POOL = ThreadPoolExecutor(max_workers=8, thread_name_prefix="styled")


_GENDER_WORDS = ("women's", "women", "woman", "men's", "men", "unisex", "girls", "boys", "ladies")


def _type_part(name: str) -> str:
    """The part of a product name AFTER the gender word -- where the garment
    type lives in this catalog's naming ("Kraus Jeans Women Brown Trousers"
    -> "brown trousers"). Matching the whole name put that item under
    "Jeans" because of the BRAND. Names without a gender word are used
    whole."""
    n = " " + (name or "").lower() + " "
    best = -1
    for w in _GENDER_WORDS:
        i = n.find(f" {w} ")
        if i >= 0 and (best < 0 or i < best):
            best = i + len(w) + 1
    return n[best:] if best >= 0 else n


def _name_matches(item: dict, keywords: list[str], exclude: list[str]) -> bool:
    n = _type_part(item.get("name"))
    if any(x in n for x in exclude):
        return False
    return any(k in n for k in keywords)


def _keyword_query(category: str | None, keywords: list[str], gender: str | None,
                   occasion: str | None = None, limit: int = 60) -> list[dict]:
    """Direct name-keyword lookup (no vectors) -- the recall backstop."""
    sb = get_supabase()
    q = (sb.table("inventory")
         .select("id,name,category,color,occasion,image_url,price,stock,created_at,season,year,gender")
         .gt("stock", 0))
    if category:
        q = q.eq("category", category)
    else:
        q = q.in_("category", list(_GARMENT_CATEGORIES))  # outfit pieces only
    if gender in ("male", "female"):
        q = q.in_("gender", [gender, "unisex"])
    if keywords:
        q = q.or_(",".join(f"name.ilike.%{k.strip()}%" for k in keywords))
    if occasion:
        q = q.contains("occasion", [occasion])
    return q.limit(limit).execute().data or []


def _palette_rank(items: list[dict], palette: list[str], occasion: str | None) -> list[dict]:
    pal = [p.lower() for p in palette]

    def score(it: dict) -> float:
        s = 0.5
        if (it.get("color") or "").lower() in pal:
            s += 0.3
        if occasion and occasion in [o.lower() for o in (it.get("occasion") or [])]:
            s += 0.2
        if it.get("image_url"):
            s += 0.05
        return s

    ranked = sorted(items, key=score, reverse=True)
    for it in ranked:
        it.setdefault("similarity", round(score(it), 2))
    return ranked


def _fill_group(*, category: str | None, keywords: list[str], exclude: list[str], wording: str,
                gender: str | None, palette: list[str], occasion: str | None,
                hint: str | None, per_group: int, exclude_ids: set | None = None,
                strict_occasion: bool = False) -> list[dict]:
    department = {"male": "men's ", "female": "women's "}.get(gender or "", "")
    query = department + ", ".join(palette[:3]) + f" {wording}"
    if occasion:
        query += f" for {occasion}"
    if hint and (category in _GARMENT_CATEGORIES or category is None):
        query += f", {hint}"

    picks: list[dict] = []
    try:
        cands = semantic_search(query, category=category, top_k=40, palette=palette,
                                occasion=occasion, gender=gender)
        cands = apply_catalog_filters(cands, gender)
        if category is None:
            cands = [c for c in cands if c.get("category") in _GARMENT_CATEGORIES]
        if keywords:
            cands = [c for c in cands if _name_matches(c, keywords, exclude)]
        if exclude_ids:
            cands = [c for c in cands if c.get("id") not in exclude_ids]
        if occasion:
            tagged = [c for c in cands if occasion in [o.lower() for o in (c.get("occasion") or [])]]
            # Occasion GROUPS (no type keywords) must be truthful -- a "Party"
            # row of untagged items is worse than no row. So must any group
            # when the customer ASKED for an occasion ("show me formal wear"):
            # strict_occasion drops the group rather than padding it with
            # casual items. Otherwise occasion is a soft preference.
            cands = tagged if (tagged or not keywords or strict_occasion) else cands
        picks = _dedupe_by_name(cands)[:per_group]
    except Exception as e:
        print(f"[styled_look] vector search failed for '{wording}' (using keyword backstop): {e}")

    if len(picks) < per_group:
        try:
            have = {p.get("id") for p in picks}
            names = {(p.get("name") or "").lower() for p in picks}
            extra = _keyword_query(category, keywords, gender, occasion=occasion)
            extra = apply_catalog_filters(extra, gender)
            if category is None:
                extra = [c for c in extra if c.get("category") in _GARMENT_CATEGORIES]
            extra = [c for c in extra if _name_matches(c, keywords, exclude)] if keywords else extra
            extra = [c for c in extra if c.get("id") not in have and (c.get("name") or "").lower() not in names
                     and not (exclude_ids and c.get("id") in exclude_ids)]
            picks = _dedupe_by_name(picks + _palette_rank(extra, palette, occasion))[:per_group]
        except Exception as e:
            print(f"[styled_look] keyword backstop failed for '{wording}': {e}")
    return picks


def _explain(item: dict, *, palette: list[str], undertone: str, hint: str, group_label: str,
             gender: str | None) -> str:
    why = []
    color = (item.get("color") or "").lower()
    if color and color in [p.lower() for p in palette]:
        why.append(f"'{item['color']}' complements your {undertone} undertone")
    if item.get("category") in _GARMENT_CATEGORIES:
        why.append(f"cut suits your body shape ({hint})")
    else:
        why.append("finishes the look in a shade that sits well with your skin tone")
    if gender in ("male", "female"):
        why.append(f"from the {'men' if gender == 'male' else 'women'}'s range")
    why.append(f"one of your {group_label.lower()} options")
    return "; ".join(why)


def recommend_styled_look(
    depth: str, undertone: str, body_shape: str, gender: str | None = None,
    occasion: str | None = None, per_group: int = 3,
    include: list[str] | None = None, strict_occasion: bool = False, **_ignored,
) -> dict:
    """Build the grouped look. Extra kwargs (style/constraints/budget/...) are
    accepted and ignored so this is a drop-in for recommend_complete_look's
    call sites; those refinements still apply on the single-list paths.

    include: the item categories the customer actually asked for (see
    inventory_search.parse_requested_items). Only those are built -- if she
    says "a dress, bag and heels" she gets exactly three sections, no
    watches or belts. None = the full look.

    strict_occasion: True when the customer named the occasion herself
    ("show me formal wear"). Every group is then hard-filtered to that
    occasion tag and dropped if it has nothing, instead of padding with
    off-occasion items.
    """
    gender = normalize_gender(gender)
    if gender not in ("male", "female"):
        gender = None
    palette = recommended_palette(depth, undertone)
    hint = body_shape_hint(body_shape, gender)
    plan = _MEN_PLAN if gender == "male" else _WOMEN_PLAN

    wanted = None
    if include:
        wanted = {normalize_category(c) for c in include if c}
        wanted = {c for c in wanted if c in ALL_ITEM_CATEGORIES}
        plan = [entry for entry in plan if entry[0] in wanted]
        if not plan:
            print(f"[styled_look] requested categories {sorted(wanted)} have no plan for "
                  f"gender={gender} -- returning empty look")

    jobs = []  # (section_key, section_label, group_label, kwargs)
    for category, max_groups, groups in plan:
        for label, kws, excl, wording in groups:
            jobs.append((category, CATEGORY_LABELS.get(category, category.title()), label, dict(
                category=category, keywords=kws, exclude=excl, wording=wording,
                gender=gender, palette=palette, occasion=occasion, hint=hint, per_group=per_group,
                strict_occasion=strict_occasion,
            )))
    results = list(_POOL.map(lambda j: _fill_group(**j[3]), jobs)) if jobs else []

    # Occasion outfits run AFTER the category groups so they can exclude
    # everything already on the page -- otherwise their picks overlap the
    # palette-matched tops/dresses above and the whole section dedupes away.
    used = {it.get("id") for items in results for it in items}
    occ_jobs = []
    # Skipped entirely when the customer named the item types she wants: an
    # "Outfits by occasion" row would add garments she didn't ask for (her
    # example: "a dress, bag and heels" must not also return tops).
    for label, occ in ([] if wanted else _OCCASION_GROUPS):
        if occasion and occ != occasion:
            continue
        occ_jobs.append(("occasion", "Outfits by occasion", label, dict(
            category=None, keywords=[], exclude=[], wording="outfit",
            gender=gender, palette=palette, occasion=occ, hint=hint, per_group=per_group,
            exclude_ids=used,
        )))
    results += list(_POOL.map(lambda j: _fill_group(**j[3]), occ_jobs))
    jobs += occ_jobs

    sections: dict[str, dict] = {}
    max_groups_by_cat = {c: n for c, n, _ in plan}
    seen_ids: set = set()
    for (cat, sec_label, group_label, _kw), items in zip(jobs, results):
        fresh = []
        for it in items:
            if it.get("id") in seen_ids:
                continue
            seen_ids.add(it.get("id"))
            it["explanation"] = _explain(it, palette=palette, undertone=undertone, hint=hint,
                                         group_label=group_label, gender=gender)
            it["group"] = group_label
            fresh.append(it)
        if len(fresh) < 2:
            continue  # a "type" with one item isn't a choice -- skip rather than pad
        sec = sections.setdefault(cat, {"category": cat, "label": sec_label, "groups": [], "items": []})
        if cat != "occasion" and len(sec["groups"]) >= max_groups_by_cat.get(cat, 99):
            continue
        sec["groups"].append({"label": group_label, "items": fresh})
        sec["items"].extend(fresh)

    ordered = [sections[c] for c, _, _ in plan if c in sections]
    if "occasion" in sections:
        ordered.append(sections["occasion"])

    # round-robin flat list: first option of every group, then seconds, ...
    flat: list[dict] = []
    for i in range(per_group):
        for sec in ordered:
            for g in sec["groups"]:
                if i < len(g["items"]):
                    flat.append(g["items"][i])

    print(f"[styled_look] {len(ordered)} sections, {sum(len(s['groups']) for s in ordered)} groups, "
          f"{len(flat)} items" + (f" (requested: {sorted(wanted)})" if wanted else "")
          + (f" strictly {occasion}" if strict_occasion and occasion else ""))
    return {
        "mode": "styled_look",
        "requested_categories": sorted(wanted) if wanted else None,
        "occasion_considered": occasion,
        "sections": ordered,
        "results": flat,
        "gender_considered": gender,
        "palette_considered": palette,
    }
