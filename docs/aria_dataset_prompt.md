# Prompt: Build the voice-command & preference dataset for "Aria" (AI Smart Mirror)

> Copy everything below the line into the AI that will generate the dataset.
> Ask it to produce the files one at a time (say "continue" when it stops).

---

You are a senior conversational-AI designer and data engineer. Build a complete,
production-quality **intent + preference dataset** for **Aria**, the voice assistant inside
an **AI Smart Mirror** that stands in a physical clothing store in **India**. The mirror is
**100% touchless**: customers cannot tap anything, so **every function on every screen must
be reachable by voice**. Customers are of **every age (children with parents, teens, adults,
elderly), every gender, body type, budget, religion and region**, and speak **English, Hindi
and Hinglish** (mixed), often casually, incompletely, or with speech-to-text errors.

The dataset will be loaded by our backend (Python/FastAPI) to (1) recognise what the customer
wants, (2) fill a structured preference profile, and (3) trigger the exact screen action. It
must be **exhaustive, consistent, machine-readable JSON**, and every action you reference
must be one of the actions defined below (or a NEW action you explicitly propose in the
`new_actions` file).

## 1. How the system works today (context — do not change these names)

**Flow:** the camera detects a person → Aria greets them → hands-free microphone listens
(speech-to-text with Whisper, English) → backend decides → Aria replies by voice
(Edge-TTS) and the screen performs **actions**.

**Aria's structured output on every turn** (the LLM fills this JSON):
```json
{
  "response": "what Aria says",
  "conversation_state": { "occasion": "wedding", "style": "traditional", "...": "..." },
  "tool_call": { "tool_name": "recommend_clothes", "occasion": "wedding" }
}
```

**Current `conversation_state` fields** (too few — you will expand them, section 4.B):
`occasion, style, color_preferences[], disliked_colors[], budget, fit, design_preference,
constraints[] (things to avoid), notes, undertone (warm|cool|neutral), skin_depth
(fair|light|medium|tan|deep), ready_for_recommendation, requested_items[]`

**Current backend tools Aria can call:**
`navigate_to_page(page)`, `trigger_body_scan`, `recommend_clothes(occasion, category, include)`,
`complete_outfit(item_id)`, `show_item_detail(item_id)`, `explain_recommendation(item_id)`,
`add_item_to_cart(item_id)`, `start_virtual_tryon(item_id)`, `request_staff_assistance(reason)`,
`search_inventory(query)`, `get_body_profile`, `get_color_palette`, `get_weather`

**Current frontend actions** (what the screen can execute):
`navigate{page}`, `repeat_last_reply`, `start_scan`, `show_recommendations{results}`,
`show_item{item_id}`, `start_tryon`, `escalate_to_staff`, `add_to_cart{item_id}`,
`toggle_theme`, `admin_logout`, `end_conversation`, `select_outfit_category{category}`,
`set_outfit_item{category,name}`, `remove_outfit_item{category}`, `set_outfit_name{name}`,
`save_outfit`

**Catalog facts** (only these exist — never invent others):
- Categories: `top, bottom, dress, footwear, bag, watch, jewelry, accessory`
- Occasion tags: `casual, ethnic, formal, office, party, smart casual, sports, travel, wedding`
- 37,567 products (Indian + western wear: sarees, kurtis, kurtas, lehengas, salwar, dupattas,
  shirts, jeans, dresses, heels, flats, sandals, handbags, clutches, watches, earrings…),
  men's, women's and unisex. Kids' items are hidden.
- Department (men's/women's) comes from the scan; customer can switch it.

**Items on screen are an ordered list** — customers refer to them by position
("first", "2nd", "last", "number 4"), colour ("the red one"), name ("the Fabindia saree"),
or deixis ("this one", "that one" = the highlighted/most recently mentioned item).

## 2. Every screen and every function (the full inventory you must cover)

Global (available on every screen):
- Sidebar menu: open/close; go to Dashboard, Body Scanner, Recommendations, AI Stylist,
  Outfit Builder, Virtual Try-On, Personalization, Shopping, Profile, Staff Assistance, Settings
- Bottom nav (mobile): Home, Style, Chat, Shop, Profile
- Top bar: search box ("Search styles, brands, trends…"), dark/light theme toggle,
  notifications open/close
- Aria overlay: open/expand panel, close panel, hands-free on/off, mic start/stop recording,
  type & send message
- Page-level: scroll up/down, scroll to top/bottom, page up/down, go back, go forward,
  go home, refresh/reload, zoom in/out (accessibility), repeat what Aria said, stop/skip
  Aria's speech, speak slower/louder, mute/unmute Aria's voice, help ("what can I say?")

**Login (Start Your Shift)** — staff only: continue with Google, email, password, show/hide
password, forgot password, Start System. (Voice: staff-only; never let customers log in.)

**Dashboard**: start body scan, open AI stylist, "View recommendations", quick actions
(Body Scan, Get Styled, AI Chat, Try On), trending styles list (Quiet Luxury, Coastal
Grandmother, Dark Academia, Minimalist Chic), recent scan cards (Face Shape, Body Shape,
Skin Tone), "New Scan", "Explore" (shopping), favourite links (Shopping, Outfit Builder,
Staff Assistance).

**Body Scanner**: start scan, rescan/reset, scan steps (posture, body proportions, body shape,
skin tone, face shape), results list (body shape, face shape, gender, skin tone, depth,
undertone, size estimate with confidence), view full analysis, auto-redirect to
recommendations. Instructions: "position yourself in the frame", "ensure good lighting".

**Analysis Results**: insight cards (Ideal Fits, Color Harmony, Style Profile, Size
Recommendation), confidence tags, body-shape card (shoulders/waist/hips), skin-tone card with
"Best Colors", face-shape card (confidence, shape, reason), scan summary, "Get
recommendations" / "Scan again".

**Recommendations**: department switch "Range: Women's | Men's"; category chips (All, Tops,
Bottoms, Dresses, Shoes, Bags, Watches, Jewellery, Accessories); occasion chips (All, casual,
ethnic, formal, office, party, smart casual, sports, travel, wedding); "What should I
include?" chips (Clothes, Footwear & Heels, Bags, Watches, Jewellery, Accessories,
Everything); "Based on your scan" strip; sections and type groups (e.g. Sarees, Heels,
Clutches); per product card: like/heart (favourite), "Why AI picked this" (expand
explanation), "Add to Outfit"; highlight an item; idle nudges.

**AI Stylist (chat page)**: hands-free toggle, suggested quick questions, mic, text input,
send, conversation history.

**Outfit Builder**: category tabs (Top, Bottom, Shoes, Bag, Watch, Accessories), pick an
item, remove an item from a slot, outfit preview, outfit name field, stats (items selected,
completion %, AI match score), "AI outfit" (auto-complete), save outfit.

**Virtual Try-On**: lighting modes (Natural, Studio, Warm, Cool), zoom slider, flip camera,
capture photo, dismiss captured photo, "current outfit" side panel. (Garment overlay is
coming — include commands anyway.)

**Personalization**: refresh recommendations, live weather card, recommended outfit
(top/bottom/shoes/accessory), wardrobe analysis, AI insights (colour harmony, style
patterns, seasonal), per-recommendation thumbs up/down, 1–5 star rating, overall rating.

**Shopping**: search products/colours, clear search, category filter chips, occasion filter
chips, product card: wishlist heart, "Reserve", "Add to cart"; cart open/close; in cart:
quantity +/−, remove item, item count, total; empty-cart state.

**Profile**: take new scan, measurements (height, body shape, face shape, skin tone,
undertone, detected gender, glasses), style-preference tags (toggle on/off), stats.

**Settings**: theme; notifications toggles (email, push, sound alerts, outfit reminders,
weather alerts, promotions, weekly digest); display language dropdown; privacy toggles
(profile visibility, share analytics, location services, biometric lock, data sync); change
password, two-factor auth, admin logout, delete account (danger); about links.
(Staff-only area — customers must be politely refused.)

**Staff Requests** (staff screen): refresh, Pending/All tabs, acknowledge, resolve.
Request types: discount, payment/checkout, refund, complaint, stock issue, special request,
other.

## 3. What to produce — files and exact formats

Produce **valid JSON only** inside each file (no comments). Use stable `snake_case` ids.

### File 1 — `intents.json` (the core; aim for **250+ intents**)
One entry per smallest function above, plus conversational intents:
```json
{
  "intent_id": "recs.like_item_by_position",
  "screens": ["recommendations"],          // or ["global"]
  "description": "Customer likes an item on screen, referred to by position",
  "action": {"type": "like_item", "params": {"target": "{item_ref}"}},
  "tool": null,                             // or a backend tool name if data is needed
  "slots": {
    "item_ref": {"type": "item_reference", "required": true,
                 "examples": ["first", "2nd", "last", "number 4", "the red one", "this one"]}
  },
  "requires_confirmation": false,          // true for irreversible: remove, clear cart, logout, delete
  "allowed_roles": ["customer"],           // customer | staff
  "utterances": [ "... 40-80 varied phrasings ..." ],
  "negative_examples": ["phrases that look similar but mean something else"],
  "responses": {
    "success": ["Added to your favourites!", "..."],
    "missing_slot": ["Which one would you like — the first, second…?"],
    "not_possible": ["There's nothing on screen to like yet — want me to show you some options?"]
  },
  "follow_up": "Offer accessories that match the liked item"
}
```
Utterance rules (every intent):
- 40–80 utterances; mix of: very short ("next", "like it"), polite, casual, rushed,
  elderly-formal ("Could you kindly…"), teen slang, indirect ("I think I'd go with the
  second"), questions ("can you scroll?"), commands, and **Hinglish/Hindi** (≈25%:
  "agla dikhao", "isko cart mein daal do", "neeche scroll karo", "yeh wala pasand hai",
  romanised and a few Devanagari).
- Include ~10% **speech-to-text-style errors** (missing words, homophones: "add to card",
  "scroll don", "shoe me sarees", "next one place").
- Use `{slot}` placeholders where values vary, plus many filled examples.

Must include at least these intent groups:
1. **Navigation**: every page, back, forward, home, open/close menu, open/close Aria.
2. **Scrolling & paging**: up/down, a little/a lot, top/bottom, next/previous page,
   next/previous section, "show more", "load more".
3. **Item focus & selection**: next/previous item, highlight by position/colour/name,
   "zoom into it", "show details", "go back to the list".
4. **Like / favourites / wishlist**: like, unlike, show my liked list, clear liked list.
5. **Cart / fitting room**: add, remove, change quantity, show cart, close cart, empty cart,
   "how many items", "what's the total", reserve an item, send cart to fitting room.
6. **Filters & sorting**: department switch, category chips, occasion chips, include chips,
   price range, colour, size, sort by price/newest/popularity, clear all filters.
7. **Search**: search for anything, clear search, refine ("only in blue", "under 2000").
8. **Recommendations**: get recommendations, more like this, something different, explain
   "why this one", complete the outfit, show only X, add accessories, compare two items.
9. **Body scan**: start, restart, cancel, "am I standing right?", "is the scan done?", explain
   my results (body shape, face shape, skin tone, size, height), correct a result
   ("I'm actually 165 cm", "I'm a size M", "show men's instead").
10. **Outfit builder**: switch tab, pick item, remove item, name outfit, AI auto-complete,
    save outfit, "what's my match score".
11. **Virtual try-on**: start try-on with item, change lighting, zoom, flip camera, take
    photo, retake, delete photo.
12. **Personalization & feedback**: thumbs up/down, star rating, "I don't like this style",
    "more like my favourites", weather questions.
13. **Voice & assistant control**: repeat, stop talking, slower, louder/quieter, mute/unmute,
    hands-free on/off, "are you listening?", help/"what can I say", wake/sleep.
14. **Staff**: call a staff member, size/stock check, discount, payment, refund, complaint,
    trial-room request, alteration, gift wrap.
15. **Conversation**: greetings, thanks/goodbye (ends chat), small talk, compliments,
    "who are you", store info (timings, location, returns policy → hand to staff),
    out-of-scope (weather elsewhere, jokes, maths) with graceful redirection.
16. **Safety & etiquette**: body-negative statements ("I'm too fat for this") → kind,
    non-judgemental reframing; requests about other people's bodies; privacy questions
    ("are you recording me?"); a child speaking alone → ask for a parent for purchases.
17. **Staff-only intents** (role = staff): settings, logout, staff request handling.
18. **Error recovery**: "no, not that", "undo", "cancel", "I said X not Y", "start over".

### File 2 — `preference_schema.json` (expanded `conversation_state`)
Design the full profile Aria should capture (aim for **40–60 fields**). For each field:
```json
{
  "field": "wearer_age_group",
  "type": "enum",                               // enum | list[enum] | number | range | text | bool
  "values": ["child", "teen", "young_adult", "adult", "middle_aged", "senior"],
  "description": "Age group of the person who will WEAR the clothes",
  "synonyms": {
    "senior": ["for my grandmother", "dadi ke liye", "for an elderly person", "60 plus"]
  },
  "extraction_examples": [
    {"utterance": "something for my mom, she's in her fifties", "value": "middle_aged"}
  ],
  "how_it_affects_recommendations": "Seniors: comfort, easy closures, modest cuts, low heels",
  "never_infer": false                          // true = only set if customer states it
}
```
Must cover at least:
- **Who it's for**: self / gift; relation (mother, wife, husband, daughter, friend,
  mother-in-law…); wearer gender; wearer age group.
- **Occasion depth**: occasion, sub-event (haldi, mehendi, sangeet, reception, puja, Eid,
  Diwali, Navratri/garba, Durga Puja, Onam, Pongal, Karva Chauth, baby shower, office party,
  interview, convocation, date, funeral/condolence), role at event (bride, groom, sister of
  bride, guest, host), time of day, venue (indoor/outdoor/beach/temple), season, city
  climate, dress code.
- **Style**: archetype (traditional, ethnic-fusion, western, minimal, boho, glam,
  streetwear, sporty, classic, quiet luxury…), formality level 1–5, trend appetite,
  favourite brands, celebrity/film inspiration.
- **Fit & body comfort**: fit (slim/regular/relaxed/oversized), length (crop/regular/long),
  rise, sleeve preference, neckline preference, body areas to highlight / to downplay
  (always phrased neutrally), maternity, plus-size, petite, tall.
- **Modesty & culture**: coverage level, no sleeveless, no short lengths, head-covering
  compatible, religious/community dress norms — **only if the customer states them**.
- **Fabric & comfort**: preferred/avoided fabrics (cotton, linen, silk, georgette, chiffon,
  rayon, wool…), breathability, allergies/sensitive skin, ease of wear (no zips, elastic
  waist), washability/ironing.
- **Colour & pattern**: favourite colours (incl. Indian names: rani pink, mehendi green,
  mustard, peacock blue…), avoided colours, colour mood (pastel, bright, dark, neutral),
  patterns (floral, checks, stripes, prints, solid), embellishment level (plain → heavy
  zari/embroidery/sequins).
- **Budget**: amount, range, currency formats ("2k", "₹1,500", "under 3000", "not more than
  five thousand", "1 lakh", "pocket-friendly"), flexibility.
- **Size**: size system (IN/UK/US/EU, S–XXL, numeric waist, shoe size), size the customer
  states vs scanned.
- **Footwear specifics**: heel height, comfort/standing all day, closed/open toe.
- **Accessories**: jewellery type (gold-tone, silver, oxidised, kundan), bag type, watch type.
- **Shopping behaviour**: urgency (need it today), quantity, mix-and-match, sustainable/
  handloom preference, pre-owned interest.
- **Accessibility**: wheelchair user, limited mobility, visual impairment (needs more voice
  detail), hearing (prefers on-screen text).
- **Session state**: requested_items, liked_items, disliked_items, last_shown list,
  pending confirmation.

### File 3 — `entities.json` (vocabulary for slot filling)
Lists with synonyms and Hinglish/Hindi variants for: garment types (100+, e.g. saree/sari/
saadi, kurti/kurta, lehenga/lehnga/ghagra, salwar/shalwar, churidar, sherwani, bandhgala,
nehru jacket, palazzo, dhoti…), colours (80+ incl. Indian names), patterns, fabrics,
occasions/festivals (60+ across Indian regions & religions), body-shape words, fits,
sizes, ordinal & positional references (first…tenth, last, top-left, "the one on the
right"), screen/page names and their spoken variants, UI words (button, tab, chip, card,
filter, cart, wishlist, fitting room, trial room).

### File 4 — `dialogues.json` (**150+ multi-turn conversations**)
Realistic end-to-end sessions (5–15 turns) across personas: bride shopping with mother,
elderly man needing comfortable kurta, teen wanting streetwear, office worker on a budget,
NRI visiting for a wedding, wheelchair user, shy customer giving one-word answers, customer
who keeps changing their mind, Hinglish-only customer, customer correcting the scan,
father shopping for a daughter, couple shopping together. Format:
```json
{"dialogue_id": "d001", "persona": "...", "turns": [
  {"speaker": "customer", "text": "...", "intent_id": "...",
   "slots": {...}, "state_delta": {...}},
  {"speaker": "aria", "text": "...", "actions": [{"type": "...", "params": {...}}]}
]}
```

### File 5 — `responses.json` (Aria's voice)
Response templates per situation, with **3 tone variants** (`friendly_default`,
`respectful_elder`, `playful_young`) and Hinglish versions: greeting, scan instructions,
scan done, showing results, empty results, item added/removed, liked, unclear request,
can't do that, waiting/thinking fillers, idle nudges, goodbye. Keep spoken replies short
(≤ 25 words) — they are read aloud.

### File 6 — `new_actions.json`
Every frontend action the intents need that does **not** exist yet (e.g. `scroll`,
`focus_item`, `like_item`, `unlike_item`, `show_liked`, `remove_from_cart`,
`set_cart_quantity`, `open_cart`, `close_cart`, `set_filter`, `clear_filters`,
`search`, `go_back`, `toggle_sidebar`, `set_lighting`, `capture_photo`, `rate_item`,
`stop_speaking`, `set_voice_volume`…). For each: name, params with types, which screens,
expected UI behaviour, and the reply Aria should give.

### File 7 — `test_set.json` (**500 held-out utterances**)
Utterances NOT used elsewhere, each with the gold `intent_id`, slots and expected action —
we will use it to measure accuracy.

## 4. Quality rules
- Never invent product names, prices, stock, discounts or store policies; route those to
  `search_inventory` or staff.
- Never infer sensitive attributes (religion, body size, age, gender) unless the customer
  states them; the scan supplies gender/size separately.
- Body talk is always positive/neutral; never use words like "flaw", "hide your belly".
- Irreversible or costly actions (empty cart, remove item, logout, delete) need a
  confirmation step.
- Customers cannot access staff-only functions — refuse politely and offer staff help.
- Every utterance must map to exactly one intent; put look-alikes in `negative_examples`.
- Keep ids, action names and field names consistent across all files.
- If the output is long, split each file into numbered parts (`intents.part1.json` …) and
  continue when asked; never truncate a JSON object mid-way.

Start with `new_actions.json`, then `preference_schema.json`, `entities.json`,
`intents.json`, `responses.json`, `dialogues.json`, `test_set.json`.
