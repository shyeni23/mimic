# AI Smart Mirror — Handoff

Paste this whole file as your first message in a new Claude Code chat.

## Project

`E:\ai-smart-mirror` — AI-powered smart mirror for a physical clothing store.
Backend: FastAPI (`backend/`), Frontend: React (`src/`).
Backend venv: `E:\ai-smart-mirror\backend\venv`. Activate with `.\venv\Scripts\Activate.ps1` from `backend/`.

**Do NOT confuse with `E:\smart-mirror`** — different, older, unrelated project.

## How to run it

Both servers must be running (they're dev processes — they stop when the Claude session ends):

```powershell
# backend (port 8000)
cd E:\ai-smart-mirror\backend
.\venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000

# frontend (port 3000), separate terminal
cd E:\ai-smart-mirror
npm start
```

Then open **http://localhost:3000** in a real browser (Chrome/Edge). Sign in with anything on
the "Start Your Shift" screen — it's a mock gate, no real credentials. Camera features (body
scan, presence detection, virtual try-on) **only work in a real browser**, never in Claude's
sandboxed browser pane.

## The 5 modules

- **Module 1** — Body/face scan (MediaPipe + DeepFace): body shape, face shape, skin tone
  (depth+undertone), height, body size, glasses, hair length, gender. Only `gender` uses a real
  neural net (DeepFace); everything else is geometric heuristics on landmark coordinates.
- **Module 2** — Conversational agent "Aria" (Groq `openai/gpt-oss-120b`): real tool-selection
  loop, streaming replies, cross-turn memory, cart awareness.
- **Module 3** — Recommendation engine (Marqo-FashionCLIP + pgvector retrieval, rule-based
  compatibility ranking, feedback loop, cold-start, trends, A/B testing, two-tower model).
- **Module 4** — Weather-aware styling nudges. **LIVE** (OpenWeatherMap key is in `backend/.env`,
  location `Mumbai,IN`). Verified working: rain → biases toward waterproof, away from sandals.
- **Module 5** — Staff escalation / human-in-the-loop (`backend/app/routers/staff.py` is tagged
  "Module 5"). Never formally specified by the user — confirm scope before building on it.

## Completed this session (2026-09-18)

1. **Season/year backfill** — `scripts/backfill_season_year.py`. 37,562 of 37,567 rows now have
   `season`/`year`. The 5 remaining are generic manually-added test items with no match in the
   source dataset (left null rather than inventing values). Needed a new `bulk_update_season_year`
   RPC. Found+fixed a real bug: `inventory` has duplicate `productDisplayName` values across
   distinct rows (~12%), so a name→single-id dict silently skipped half of each duplicate pair.
2. **Product images** — `scripts/backfill_product_images.py`. 37,566 of 37,567 items now have real
   photos. **Served from backend local disk** (`backend/data/product_images/`, mounted at
   `/media/products` in `main.py`), NOT Supabase Storage — Storage upload is ~5-12s/item
   (50+ hours for 37K); local disk took ~4 minutes. Needed a `bulk_update_image_url` RPC.
   Also fixed Dashboard + OutfitBuilder, which were hardcoding emoji icons instead of
   rendering `image_url` when present.
3. **A/B test is live** — registered + activated two `stage_b_weights` configs at 50/50:
   v1 control (current weights) vs v2 color-forward (`color=0.40, semantic=0.25`). Added
   `model_registry.report_variant_performance()` + `scripts/report_ab_test.py` so it's actually
   measurable. Run `python scripts/report_ab_test.py` to check results.
4. **Two-tower model TRAINED** (was dormant). Generated ~15,700 synthetic interactions via new
   `scripts/generate_synthetic_interactions.py` (6 persona archetypes built from the app's own
   color-matching logic, every row tagged `{"synthetic": true}` in `interactions.context` so it
   can be identified or wiped with `--wipe`). Cleared the 10,000-positive floor; trained 8 epochs,
   loss 2.67→2.56. **NOT wired into live serving** — see open issues.
5. **Fixed silent 1000-row truncation** in `check_training_readiness.py` and `train_two_tower.py`.
   PostgREST caps a plain `.select().execute()` at 1000 rows, so once `interactions` grew past
   that, readiness under-reported (634 instead of 10,889) and training would have silently used
   only the first 1000 rows. Would have bitten real production data too.
6. **Sidebar/navigation freeze bug** — at any browser width 769–1024px an invisible full-page
   overlay blocked every click and keystroke in the app. Breakpoint mismatch: JS used 768px,
   CSS used 1024px. Fixed `MainLayout.js`, `useMediaQuery.js`, `Sidebar.js`, `Navbar.css`.
7. **JSON leak in chat** — Aria could append a raw JSON blob after a normal reply. Broadened the
   detector in `graph.py` (it only checked the START of the message) and added a frontend safety
   net in `VoiceAgentContext.js` so a stuck stream never leaves raw JSON on screen.
8. **Occasion filters (displayed)** — filter chips on Shopping + Recommendations, backed by a new
   `/api/inventory/occasions` endpoint and an `occasion` param on `/api/inventory/browse`.
   Real tags: casual, ethnic, formal, office, party, smart casual, sports, travel, wedding.
9. **Performance** — `get_inventory(include_embedding=False)` for callers that don't need the
   512-float embedding. Fixed a real 500 (Supabase statement timeout) on
   `/api/outfit-recommendation`, and cut `/api/inventory/browse` from 1.33MB to 63KB.
10. **Frontend retry** — `utils/api.js` now has `fetchWithRetry` with backoff. The first
    cross-origin request after a page load was failing reliably in this environment (looked like
    a CORS error, was actually a cold-connection failure), permanently sticking filter rows on "All".
11. **Body-scan distance-invariance** — camera distance no longer affects results. Both
    `height_estimate.py` and `body_shape.py` were checking the calibration-based (distance-dependent)
    method BEFORE the ratio-based (distance-invariant) one. Reordered both: height now uses your own
    face length as the reference scale, body size uses head-width. No need to stand at a fixed spot.
12. **Scan → recommendations flow** — `BodyScanner.js` now auto-navigates to `/recommendations`
    1.5s after the scan completes, and `events.py`'s `scan_complete` trigger now *requires* Aria to
    call `recommend_clothes` (it previously let her ask a follow-up question instead, so half the time
    you'd get a question instead of clothes).
13. **Accessory coverage** — a "style me" set was 7/8 garments with zero footwear or bags (the
    search query literally ended in "clothing"). `_merge_accessory_coverage` in `inventory_search.py`
    now runs an accessory-worded search and interleaves results across accessory *types*. Also added
    `_dedupe_by_name` — duplicate-named catalog rows were showing the same item twice in one result set.
14. **Prompt token cost cut** — system prompt trimmed without dropping any behavioral rule.
    Per structured call: 6,576 → 4,815 tokens. Per fast-chat call: 3,872 → 2,355.
    (Original verbose prompt is in git history; a backup is in this session's scratchpad.)

15. **Scan -> recommendations are now actually scan-driven (gender)** — the scan's DeepFace
    `gender` label was never passed to `recommend_items`, so a male scan got saris/tunics
    (confirmed live). New `app/services/fashion/catalog_filters.py` (gender + innerwear/kids
    safety filter, shared by both recommenders); `inventory.gender` column + `match_inventory`
    now takes `match_gender` (migration section 6 in `module3_missing_migrations.sql`);
    `scripts/backfill_gender.py` fills the column from the source dataset (name-based inference
    for the rest). Code degrades gracefully if the migration hasn't run (Python-side filtering,
    logged once). Body-shape hint wording is now per-department ("belted pieces" for a men's
    rectangle scan just retrieved belts). Accessory top-up search no longer carries the
    garment hint. `/api/recommend` returns `scan_profile`; Recommendations page shows a
    "Based on your scan" strip. **Open issue #1 (underwear) is fixed by this.**

16. **Post-scan COMPLETE LOOK (2026-09-19)** — the scan now produces one short ranked list PER
    category (tops, bottoms, dresses, footwear, bags, watches, jewellery, accessories), each
    searched against the scan profile, instead of one list of 8 that was ~all tops. Backend:
    `inventory_search.recommend_complete_look()` (sections run in parallel, ~1.5s; serial retry
    for the shared Supabase client's occasional "Server disconnected"), `/api/recommend` takes
    `grouped: true` (+ `per_category`), Aria's `recommend_clothes` uses it whenever no category is
    asked for and puts `sections` in the `show_recommendations` payload. Also
    `normalize_category()` — the page's chips were sending "tops"/"shoes"/"watches" which the DB
    (top/footwear/watch) never matched, so every chip except All returned nothing. Frontend:
    Recommendations.js renders headed sections on "All", flat grid on a chip; chips now cover all
    8 categories; emoji/gradient map keys fixed (were plural, never matched). Verified in-browser
    by driving a real `/api/vision/scan` with a stored frame and pushing the result into React
    state via the SessionProvider fiber (camera isn't available in Claude's pane).

17. **Gender detection was silently broken (FIXED)** — DeepFace needs legacy Keras
    (`TF_USE_LEGACY_KERAS=1`) and sets it on import, but TensorFlow only reads it on its FIRST
    import, and MediaPipe/face_shape_ml import TF earlier in the scan chain. Result: every scan
    returned gender=unknown (conf 0.0, "The layer sequential has never been called") so the whole
    men's/women's filter never activated in practice. Fix: env var set in `app/__init__.py`
    before anything imports TF; `face_shape_ml/predictor.py` now imports Keras 3 directly
    (`import keras`) since its .keras file is Keras-3 format and `tensorflow.keras` becomes tf_keras
    under the flag. Both models verified in one server: gender male 0.91 + face shape from the
    trained classifier. **Requires a real server restart** (a --reload hot reload was not enough).
18. **pgvector HNSW post-filter recall (SQL section 7 — user must run)** — `match_inventory` with
    a category+gender filter on a small slice (men's bottoms ≈3% of rows) returned 0-2 rows even
    with match_count=6, because HNSW collects `hnsw.ef_search` (40) nearest rows BEFORE the WHERE
    clause. A men's complete look was missing its whole Bottoms section live. Section 7 re-declares
    the RPC as plpgsql with `ef_search=400` + `hnsw.iterative_scan=relaxed_order` (guarded for
    pgvector <0.8). Python safety net regardless: `recommend_items` tops up a short single-category
    result from a palette/occasion scan (`_fallback_search`) and logs it.
19. **Supabase client is now thread-local** (`supabase_client.get_supabase`) — the process-wide
    singleton's httpx pool broke under the parallel section searches ("Server disconnected",
    "deque mutated during iteration"). Persistent `_LOOK_POOL` executor so threads (and their
    connections) are reused. Complete look ≈1.1-1.5s warm.

20. **Gender ensemble + on-screen override (2026-09-19)** — the user's real scan (dark room, frame mean
    brightness 32/255) came back `male 0.77` for a woman; DeepFace's face-only model has a documented
    male bias and low-light normalisation made it WORSE (0.93). Replaced with an ensemble in
    `gender_detect.py`: FashionCLIP zero-shot on the full frame (weight 2 — hair/clothing/build), CLIP on
    the face crop, DeepFace (both face votes halved when the crop is dark), thresholds 0.62/0.38 with a
    real "unknown" band. Measured: 47/50 on labelled catalog shots (M 22/25, F 25/25, 0 unknown); both
    real frames now `female 0.77-0.78`. **Load-order gotcha:** importing TensorFlow after PyTorch
    segfaults this process — DeepFace (TF) must run before the CLIP votes; main.py's warm-up loads a TF
    model first for the same reason. Customer override: `POST /api/vision/scan/gender` + the
    "Range: Women's | Men's" chip on the Recommendations strip (saved on the scan row, so Aria agrees).
    Verified live: scan → Women's look → tap Men's → men's look. Aria voice is OFF via
    `REACT_APP_ARIA_VOICE=off` in `.env` (user request; restart `npm start` after changing).

21. **DEMO MODE: women's-only + styled look (2026-09-19)** — `FORCE_GENDER=female` in `backend/.env`
    (`config.force_gender`): every scan is recorded as female, `/api/vision/scan/gender` refuses changes
    (`locked: true`), `/api/recommend` returns `scan_profile.gender_locked` and the page shows "Range:
    Women's" as a plain tag (no toggle). Remove the line to go back to the gender ensemble. New
    `app/services/fashion/styled_look.py`: the post-scan view is now every category split into garment
    TYPES with 2-3 options each (Dresses→Sarees/Dresses/Shift & A-line; Footwear→Heels/Flats/Sandals/…;
    Bags→Handbags/Clutches/Sling/Totes; …) plus "Outfits by occasion" (Formal/Party/Casual/Ethnic).
    Types come from product-name words AFTER the gender word (brand "Kraus Jeans" no longer counts as
    jeans); groups with <2 real items are dropped, never padded. Catalog has NO bodycon/maxi/palazzo —
    can't be shown. `recommend_complete_look(styled=True)` delegates to it, so page + Aria both get
    `sections[].groups[]`. ~5s warm (33 groups, 8 threads; first call after a restart ~30s = model load).
    Fixed on the way: FashionCLIP `_load()` is now lock-guarded (8 threads racing into open_clip
    segfaulted); proactive `/api/agent/event` returns `reply:""` instead of "Sorry, I hit a little snag"
    when the LLM fails (Groq quota) so no apology toasts appear during a scan.

22. **Product images upgraded to 384x512 (2026-09-19)** — the catalog was seeded from the "small"
    dataset edition whose images are 60x80 px, so cards looked blurry at ~370px.
    `scripts/upgrade_product_images_hq.py` streams `benitomartin/fashion-product-images-small-384x512`
    (same 44,072 rows, same productDisplayName join) and overwrites `data/product_images/<id>.jpg`
    in place -- no DB write, same URLs. 37,562 of 37,567 upgraded in ~14 min (157MB -> 888MB);
    resumable (skips files already >=200px wide). Browsers cache the old tiny files: hard-refresh once.
23. **Auto gender detection RE-ENABLED (2026-09-29)** — `FORCE_GENDER` in `backend/.env` is now empty,
    so the ensemble decides per scan again (the `female` lock was only for the 2026-09-19 demo video).
    The Range chip on the Recommendations page is interactive again (tap to correct). Both departments
    have full grouped plans in `styled_look.py` (`_WOMEN_PLAN` / `_MEN_PLAN`).

24. **"Recommend only what I asked for" (2026-09-29)** — two behaviours the user specified:
    (a) an occasion request now HARD-filters ("show me formal wear" -> only formal-tagged items;
    a type group with nothing formal is dropped, not padded) via `strict_occasion`, set whenever
    the caller passes an occasion; (b) the customer picks WHICH item types to see.
    `inventory_search.parse_requested_items()` turns her own words into categories
    ("suggest heels also" -> clothes+footwear; "a dress, bag and heels" -> exactly those three;
    "only clothes"; "everything"), and `recommend_styled_look(include=[...])` builds only those
    sections -- the "Outfits by occasion" row is skipped for a narrowed request so it can't add
    garments she didn't ask for. Wired through `/api/recommend` (`include`, `items_text`,
    `strict_occasion`), Aria's `recommend_clothes(include=...)` + a flat `include` field on the
    structured tool-call schema, and a prompt rule that makes her ASK once ("accessories, a bag,
    heels or a watch to go with it, or just the clothes?") before recommending -- with the
    post-scan `scan_complete` event explicitly carved out so the automatic set stays a full look.
    Frontend: a "What should I include?" chip row on the Recommendations page (the on-screen form
    of the same question, works with Aria's voice/LLM off) that also syncs from her
    `requested_categories`. Tests: `tests/test_item_selection.py` (87 passed total) covers the
    parser and the section plan with `_fill_group` stubbed -- no DB needed.
    **Retrieval quality for these paths is NOT yet verified live** (see the blocker below).

25. **Gap-closing pass (2026-09-29, later)** — all work committed to git on branch
    `feature/modules-1-5` (it was all uncommitted since the initial push; `data/product_images/`
    is now gitignored, 888MB). Then:
    - **Fast chat on its own Groq quota** — new `config.groq_fast_model` (`openai/gpt-oss-20b`) +
      `llm.get_fast_chat_llm()`, used by graph.py's fast path (sync + streaming) and
      `llm_explain.py`. Tool/structured turns stay on 120b. Verified live: chit-chat answered
      on 20b while the 120b daily quota was exhausted.
    - **Fast-path failures now fall through** to the structured path instead of crashing
      (`get_*_llm()` was called outside the try) or apologising (stream path). New
      `run_agent_turn(..., allow_fast_path=False)` so the fallback doesn't call the fast model twice.
    - **Style refinements routed to the structured path** — "maybe something softer",
      "I prefer cotton", "no embroidery" had no action keyword, went to the fast path, and were
      never saved to conversation_state. Added a refinement-word group to `_ACTION_KEYWORDS`.
    - **`design_preference` restored to `ConversationState`** — the slim-schema cut removed it
      while the prompt and `tools.py` still used it, so "something simple" was silently dropped.
    - **`complete_outfit` joined the A/B test** (passes `session_id` to `rerank_by_compatibility`);
      `report_variant_performance` counts both sources and now **pages past 1000 rows**
      (it had the same PostgREST truncation bug as item 5).
    - Tests: stale mocks in `test_natural_language_extraction.py` fixed (they didn't account for
      the fast path) + new `TestFastChatRouting`. **126 passed** excluding the live-Groq class.
    - `.env.example` had `GROQ_MODEL=openai/gpt-oss-20b` (the model config.py says fails at
      structured output) — now 120b, plus `GROQ_FAST_MODEL` and `FORCE_GENDER`. Both READMEs
      rewritten (backend one still described Ollama/qwen).
    - Supabase is reachable again (the 2026-09-29 NXDOMAIN blocker is resolved).

## SQL migrations already run by the user (don't re-ask)

`bulk_update_season_year`, `bulk_update_image_url`, section 6 (gender column + `bulk_update_gender` +
`match_inventory(..., match_gender)`), and `alter table recommender_configs disable row level security;`
**Section 7 (HNSW recall) has NOT been confirmed run — ask.**
All are also in `backend/app/db/schema.sql` and `backend/app/db/module3_missing_migrations.sql`.

## OPEN ISSUES — start here

1. ~~Underwear/lingerie appears in recommendations.~~ **FIXED** (item 15 above) — filter now
   applies on every path (`catalog_filters.passes_sanity_check`), with whole-word matching and
   briefs/boxers/trunks/camisole/shapewear added.
2. **Groq daily quota** — mitigated (item 25: chit-chat now uses 20b's separate 200K bucket),
   but tool/structured turns still share 120b's 200K/day (~40 tool turns). For real store
   traffic, upgrade the Groq tier.
3. **Aria's spoken reply after a scan is unverified.** The tool call itself is confirmed working
   (returns 8 items spanning clothes + accessories), but every attempt to verify her actual
   spoken reply hit the quota limit. Re-test `POST /api/agent/event` with
   `{"event": "scan_complete"}` once quota resets.
4. **Image-embedding backfill incomplete** — 15,781 of 37,567 have real *image* embeddings; the
   rest fall back to text embeddings (search still works). Resume anytime, it skips done rows:
   `python scripts/backfill_image_embeddings.py`
5. **Two-tower model isn't wired into serving.** The trained checkpoint sits in
   `backend/data/models/two_tower/` but nothing loads it — live recommendations still use
   Stage A (FashionCLIP + pgvector) + Stage B (rule-based ranking). Needs an inference function
   before it affects anything. Also remember it's trained on synthetic data, so its output isn't
   meaningful about real customers yet.
6. ~~`complete_outfit` is excluded from the A/B test~~ **FIXED** (item 25).
7. **Height/size confidence values were re-tuned** when I reordered the estimation tiers. Worth
   sanity-checking against real people if precision matters.
8. **Module 5 (staff escalation) scope was never specified** — code exists (`routers/staff.py`,
   `StaffRequests.js`), but confirm with the user what it must do before calling it done.
9. **Live Groq tests** (`TestNaturalLanguageExtraction`) have not been re-run since item 25 —
   the 120b quota was exhausted. Run them on a fresh quota day.

## Working style that worked well

- **Live-test everything** against the real Supabase DB and real Groq calls. Don't claim a fix
  works without running it.
- **Be economical with Groq calls** — the daily quota is the binding constraint. Prefer direct
  Python function tests over full chat turns when proving backend logic.
- **SQL migrations must be handed to the user** as a SQL block to paste into the Supabase SQL
  editor — there's no direct Postgres connection, only the REST/RPC API.
- **PostgREST caps responses at 1000 rows.** Any `.select().execute()` without `.range()`
  pagination silently truncates. This caused two real bugs this session — check for more.
- The user runs **Windows PowerShell** (`curl` is aliased to `Invoke-WebRequest`; prefer
  `Invoke-RestMethod` or `curl.exe`).
- Claude's sandboxed browser pane **cannot access a camera** — camera flows must be tested by the
  user in a real browser.
- The dev servers reset between turns in this environment fairly often; check they're up before
  testing rather than assuming.
