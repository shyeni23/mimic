-- Run this in the Supabase SQL editor before starting the backend.
-- Enable pgvector for FashionCLIP embedding similarity search.
create extension if not exists vector;

-- ---------- Users ----------
create table if not exists users (
    id uuid primary key default gen_random_uuid(),
    name text,
    preferences jsonb default '{}'::jsonb,
    created_at timestamptz default now()
);

-- ---------- Sessions (one per mirror interaction) ----------
create table if not exists sessions (
    id uuid primary key default gen_random_uuid(),
    user_id uuid references users(id),
    created_at timestamptz default now()
);

-- ---------- Body/Face scan results (Module 1) ----------
create table if not exists scans (
    id uuid primary key default gen_random_uuid(),
    session_id uuid references sessions(id),
    body_shape text,
    face_shape text,
    skin_tone_hex text,
    skin_tone_category text,
    skin_tone_undertone text,
    body_size_estimate text,
    height_cm numeric,
    height_source text,           -- 'spoken' | 'camera'
    glasses_detected boolean,
    hair_length text,             -- 'short' | 'medium' | 'long' | 'unknown'
    gender text,                  -- 'male' | 'female' | 'unknown'
    landmarks jsonb,
    frame_url text,
    created_at timestamptz default now()
);

-- Mirror-specific one-time calibration: pixels-per-cm at this camera's fixed
-- standing distance, used by height_estimate.py. Insert/update a single row.
create table if not exists mirror_calibration (
    id int primary key default 1,
    px_per_cm numeric,
    updated_at timestamptz default now(),
    constraint single_row check (id = 1)
);

-- ---------- Inventory (Module 1/3) ----------
create table if not exists inventory (
    id uuid primary key default gen_random_uuid(),
    name text not null,
    category text not null,       -- top, bottom, dress, footwear, bag, jewelry, watch, accessory
    color text,
    occasion text[],              -- e.g. {formal, casual, wedding}
    style_tags text[],
    image_url text,
    embedding vector(512),        -- FashionCLIP image embedding
    price numeric,
    stock int default 0,
    created_at timestamptz default now()
);

-- HNSW replaces the earlier IVFFlat index. IVFFlat with lists=100 was silently
-- returning zero rows on small embedding sets: with fewer populated vectors
-- than centroids, most probes hit empty lists and pgvector returns nothing at
-- all. HNSW has no probe/centroid concept and works correctly from row #1.
-- Requires pgvector 0.5.0+ (Supabase ships this).
create index if not exists inventory_embedding_idx
    on inventory using hnsw (embedding vector_cosine_ops)
    with (m = 16, ef_construction = 64);

-- ---------- Conversations (Module 2) ----------
create table if not exists conversations (
    id uuid primary key default gen_random_uuid(),
    session_id uuid references sessions(id),
    role text not null,           -- user | assistant | tool
    content text not null,
    meta jsonb default '{}'::jsonb,
    created_at timestamptz default now()
);

-- ---------- Feedback (used later by Module 4, defined now for forward-compat) ----------
create table if not exists feedback (
    id uuid primary key default gen_random_uuid(),
    session_id uuid references sessions(id),
    item_id uuid references inventory(id),
    liked boolean,
    created_at timestamptz default now()
);

-- ---------- Staff / human-in-the-loop escalation ----------
-- Raised by the agent (request_staff_assistance tool, see app/services/agent/tools.py)
-- whenever a customer asks for something the agent isn't authorized to handle itself
-- (discount, payment, refund, complaint, stock problem, special request). A human
-- reads/resolves these -- the agent never invents an answer to fill the gap.
create table if not exists staff_requests (
    id uuid primary key default gen_random_uuid(),
    session_id uuid references sessions(id),
    reason text not null,          -- discount | payment | refund | complaint | stock_issue | special_request | other
    message text,                  -- short context: what the customer actually asked for
    status text not null default 'pending',  -- pending | acknowledged | resolved
    created_at timestamptz default now()
);

-- Helper RPC for vector similarity search from Python. Returns stock too, and
-- hard-filters out-of-stock items at the SQL level -- the agent must never
-- recommend an item that isn't actually purchasable (see recommend_items()'s
-- budget/stock handling in inventory_search.py).
create or replace function match_inventory(
    query_embedding vector(512),
    match_category text default null,
    match_count int default 10
)
returns table (
    id uuid,
    name text,
    category text,
    color text,
    occasion text[],
    image_url text,
    price numeric,
    stock int,
    similarity float
)
language sql stable
as $$
    select
        id, name, category, color, occasion, image_url, price, stock,
        1 - (embedding <=> query_embedding) as similarity
    from inventory
    where (match_category is null or category = match_category)
      and stock > 0
    order by embedding <=> query_embedding
    limit match_count;
$$;

-- Migration for scans tables created before gender detection was added --
-- safe to re-run, no-ops if the column already exists.
alter table scans add column if not exists gender text;

-- ---------- Interaction events (Module 3, implicit-feedback training signal) ----------
-- Every implicit signal a customer generates: card impression, click, tryon
-- request, add-to-cart, skip. Feeds the deep-learning recommender's user tower
-- once we have enough volume -- until then it's just a passive log. Explicit
-- like/dislike stays in the feedback table above (kept as a separate signal).
create table if not exists interactions (
    id uuid primary key default gen_random_uuid(),
    session_id uuid references sessions(id),
    user_id uuid references users(id),
    item_id uuid references inventory(id),
    event_type text not null check (event_type in
        ('view','click','tryon','add_to_cart','skip','dismiss','recommend_shown')),
    context jsonb default '{}'::jsonb,
    created_at timestamptz default now()
);
create index if not exists interactions_session_idx on interactions(session_id, created_at desc);
create index if not exists interactions_item_idx on interactions(item_id);
create index if not exists interactions_user_type_idx on interactions(user_id, event_type);

-- ---------- Image-embedding backfill (Module 3 quality upgrade) ----------
-- The 44K-item bulk seed only computed TEXT embeddings (name+color+category)
-- -- real Marqo-FashionCLIP IMAGE embeddings (actual product photo) capture
-- color nuance, pattern, and silhouette that text alone can't, and are what
-- the retriever was actually designed to use. This column tracks which rows
-- still need the upgrade so scripts/backfill_image_embeddings.py (or its
-- Colab GPU counterpart) can resume safely instead of re-processing rows
-- that already got a real image embedding.
alter table inventory add column if not exists embedding_source text default 'text';
-- backfill existing rows: the original 5 hand-seeded items already got real
-- image embeddings via embed_inventory.py -- mark them so the backfill
-- script doesn't waste time re-embedding what's already correct.
update inventory set embedding_source = 'image'
    where embedding_source = 'text' and image_url is not null and embedding is not null;

-- Bulk-update RPC: writes many (id, embedding) pairs in ONE round trip via
-- unnest, instead of one UPDATE per row. This is what fixes the "canceling
-- statement due to statement timeout" failures seen when inserting/updating
-- large batches one row at a time -- a single set-based UPDATE is far
-- cheaper for Postgres (and for the HNSW index's incremental maintenance)
-- than N separate statements each paying their own round-trip + planning cost.
-- `embeddings` is text[] (each entry a vector literal string like
-- "[0.1,0.2,...]"), NOT vector(512)[] -- PostgREST/postgrest-py cannot
-- reliably serialize a JSON array-of-arrays into a native Postgres vector
-- array parameter (confirmed live: error 22P02 "invalid input syntax for
-- type vector" when the Python side sent vector(512)[] directly -- it
-- flattened to raw floats instead of vector literals). Casting text->vector
-- inside the function body sidesteps the RPC layer's array-of-vector
-- serialization gap entirely; the Python caller just needs to str() each
-- embedding list before sending.
create or replace function bulk_update_embeddings(
    ids uuid[],
    embeddings text[]
)
returns void
language sql
as $$
    update inventory
    set embedding = data.embedding::vector(512),
        embedding_source = 'image'
    from (
        select unnest(ids) as id, unnest(embeddings) as embedding
    ) as data
    where inventory.id = data.id;
$$;

-- ---------- Cold-start personalization (Module 3) ----------
-- A brand-new customer has no scan and no conversation history -- the
-- recommender's only options today are "wait for a scan" or "generic
-- results." This RPC aggregates cross-SESSION engagement (click/add_to_cart/
-- tryon, never raw views -- views are too noisy a signal for what's
-- genuinely popular) so a first-time customer sees real, currently-popular
-- items immediately while we get her scanned, instead of nothing at all.
-- No user_id or cross-session identity needed -- this is store-wide
-- popularity, not personalization of a specific returning customer (that's
-- a separate, larger feature -- see the project's own note on
-- cross-session-memory as future work).
create or replace function trending_items(
    match_category text default null,
    match_occasion text default null,
    days_back int default 30,
    match_count int default 8
)
returns table (
    id uuid,
    name text,
    category text,
    color text,
    occasion text[],
    image_url text,
    price numeric,
    stock int,
    engagement_count bigint
)
language sql stable
as $$
    select
        i.id, i.name, i.category, i.color, i.occasion, i.image_url, i.price, i.stock,
        count(*) as engagement_count
    from interactions x
    join inventory i on i.id = x.item_id
    where x.event_type in ('click', 'add_to_cart', 'tryon')
      and x.created_at > now() - (days_back || ' days')::interval
      and i.stock > 0
      and (match_category is null or i.category = match_category)
      and (match_occasion is null or match_occasion = any(i.occasion))
    group by i.id, i.name, i.category, i.color, i.occasion, i.image_url, i.price, i.stock
    order by engagement_count desc
    limit match_count;
$$;

-- ---------- Trend / seasonal awareness (Module 3) ----------
-- The source dataset (ashraq/fashion-product-images-small, see
-- scripts/seed_fashion_dataset.py) carries `season` and `year` columns for
-- every product, but the seed pipeline never captured them -- this data was
-- always available and simply never wired in. "New arrival" needs no new
-- column at all: inventory.created_at (already present) is the signal,
-- see app/services/fashion/trends.py's is_new_arrival().
alter table inventory add column if not exists season text;   -- Spring, Summer, Fall, Winter (from source dataset)
alter table inventory add column if not exists year int;      -- product year (from source dataset)

-- match_inventory (defined earlier in this file) didn't return created_at/
-- season/year -- semantic_search()'s Stage A path went through this RPC
-- and never had trend/seasonal data to annotate, unlike the fallback path
-- (get_inventory(), a plain select *) which always had it. Re-declaring to
-- add the missing columns. NOTE: Postgres refuses CREATE OR REPLACE when the
-- RETURNS TABLE column set changes (error 42P13 "cannot change return type
-- of existing function"), so the old definition must be dropped first --
-- safe, since no other DB object depends on it and the Python caller reads
-- result columns by name, not position, so the superset is drop-in.
drop function if exists match_inventory(vector, text, integer);
create or replace function match_inventory(
    query_embedding vector(512),
    match_category text default null,
    match_count int default 10
)
returns table (
    id uuid,
    name text,
    category text,
    color text,
    occasion text[],
    image_url text,
    price numeric,
    stock int,
    similarity float,
    created_at timestamptz,
    season text,
    year int
)
language sql stable
as $$
    select
        id, name, category, color, occasion, image_url, price, stock,
        1 - (embedding <=> query_embedding) as similarity,
        created_at, season, year
    from inventory
    where (match_category is null or category = match_category)
      and stock > 0
    order by embedding <=> query_embedding
    limit match_count;
$$;

-- Bulk season/year backfill (scripts/backfill_season_year.py) -- same
-- unnest-join pattern as bulk_update_embeddings, needed because these two
-- columns come from the source dataset per-row (not a single shared value),
-- so a plain .update() can't set them all in one round trip.
create or replace function bulk_update_season_year(
    ids uuid[],
    seasons text[],
    years int[]
)
returns void
language sql
as $$
    update inventory
    set season = data.season,
        year = data.year
    from (
        select unnest(ids) as id, unnest(seasons) as season, unnest(years) as year
    ) as data
    where inventory.id = data.id;
$$;

-- Bulk image_url backfill (scripts/backfill_product_images.py) -- same
-- unnest-join pattern as the two RPCs above. A plain PostgREST .upsert()
-- can't do this: with only (id, image_url) in the payload it still
-- generates a real INSERT ... ON CONFLICT statement under the hood, which
-- fails NOT NULL constraints (e.g. `name`) on every unlisted column before
-- the conflict/update path is even reached. Confirmed live (error 23502).
create or replace function bulk_update_image_url(
    ids uuid[],
    urls text[]
)
returns void
language sql
as $$
    update inventory
    set image_url = data.image_url
    from (
        select unnest(ids) as id, unnest(urls) as image_url
    ) as data
    where inventory.id = data.id;
$$;

-- ---------- Recommender config registry (A/B testing + rollback, Module 3) ----------
-- Named, versioned tunable configs (e.g. Stage B compatibility weights) --
-- rows are NEVER deleted, only deactivated, so version history and rollback
-- both fall out of the same simple model: "roll back" = reactivate a prior
-- version's row. Multiple rows for the same `name` can be active
-- simultaneously (split by traffic_pct) for genuine A/B testing; normally
-- exactly one row per `name` is active at 100%.
create table if not exists recommender_configs (
    id uuid primary key default gen_random_uuid(),
    name text not null,               -- e.g. 'stage_b_weights' -- groups versions together
    version int not null,             -- auto-incremented per name by app/services/fashion/model_registry.py
    config jsonb not null,            -- the actual tunable parameters
    is_active boolean not null default false,
    traffic_pct int not null default 100,  -- % of sessions assigned when multiple versions of `name` are active
    notes text,
    created_at timestamptz default now(),
    activated_at timestamptz,
    deactivated_at timestamptz
);
create unique index if not exists recommender_configs_name_version_idx
    on recommender_configs(name, version);
create index if not exists recommender_configs_active_idx
    on recommender_configs(name, is_active) where is_active;

-- ---------- Gender-aware retrieval (scan -> recommendations) ----------
-- The scan's DeepFace gender label (scans.gender) is the single strongest
-- "based on the scan" signal, but inventory had no gender column and
-- match_inventory couldn't filter on it -- so a male scan got saris.
-- Backfilled from the source dataset's `gender` field (Men/Women/Boys/
-- Girls/Unisex) by scripts/backfill_gender.py; see catalog_filters.py for
-- how null rows are handled by name. Full migration (including the
-- re-declared match_inventory with `match_gender`) is section 6 of
-- module3_missing_migrations.sql.
alter table inventory add column if not exists gender text;   -- male | female | unisex | kids
create index if not exists inventory_gender_idx on inventory(gender);
