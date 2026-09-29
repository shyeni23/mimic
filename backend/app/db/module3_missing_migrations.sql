-- Consolidated Module 3 migrations verified MISSING on the current DB
-- (checked live 2026-09-15). Run this whole block once in the Supabase SQL editor.

-- 1. Image-embedding tracking column
alter table inventory add column if not exists embedding_source text default 'text';
update inventory set embedding_source = 'image'
    where embedding_source = 'text' and image_url is not null and embedding is not null;

create or replace function bulk_update_embeddings(
    ids uuid[],
    embeddings vector(512)[]
)
returns void
language sql
as $$
    update inventory
    set embedding = data.embedding,
        embedding_source = 'image'
    from (
        select unnest(ids) as id, unnest(embeddings) as embedding
    ) as data
    where inventory.id = data.id;
$$;

-- 2. Trend / seasonal columns + trending RPC
alter table inventory add column if not exists season text;
alter table inventory add column if not exists year int;

-- Postgres refuses CREATE OR REPLACE when the RETURNS TABLE column set
-- changes (error 42P13) -- the old match_inventory must be dropped first.
-- Safe: no other DB object depends on it, and the Python caller reads
-- result columns by name so the new superset is a drop-in replacement.
drop function if exists match_inventory(vector, text, integer);

create or replace function match_inventory(
    query_embedding vector(512),
    match_category text default null,
    match_count int default 10
)
returns table (
    id uuid, name text, category text, color text, occasion text[],
    image_url text, price numeric, stock int, similarity float,
    created_at timestamptz, season text, year int
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

create or replace function trending_items(
    match_category text default null,
    match_occasion text default null,
    days_back int default 30,
    match_count int default 8
)
returns table (
    id uuid, name text, category text, color text, occasion text[],
    image_url text, price numeric, stock int, engagement_count bigint
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

-- 2b. Bulk season/year backfill RPC (scripts/backfill_season_year.py)
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

-- 2c. Bulk image_url backfill RPC (scripts/backfill_product_images.py)
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

-- 3. HNSW index (verify/recreate -- IVFFlat silently returns 0 rows on small sets)
drop index if exists inventory_embedding_idx;
create index inventory_embedding_idx
    on inventory using hnsw (embedding vector_cosine_ops)
    with (m = 16, ef_construction = 64);

-- 4. A/B testing / model registry
create table if not exists recommender_configs (
    id uuid primary key default gen_random_uuid(),
    name text not null,
    version int not null,
    config jsonb not null,
    is_active boolean not null default false,
    traffic_pct int not null default 100,
    notes text,
    created_at timestamptz default now(),
    activated_at timestamptz,
    deactivated_at timestamptz
);
create unique index if not exists recommender_configs_name_version_idx
    on recommender_configs(name, version);
create index if not exists recommender_configs_active_idx
    on recommender_configs(name, is_active) where is_active;
alter table recommender_configs disable row level security;

-- 5. Interactions RLS (needed for the event logger to write)
alter table interactions disable row level security;

-- 6. GENDER-AWARE RETRIEVAL (scan -> recommendations)
-- The body scan produces gender (male/female/unknown) but inventory had no
-- gender column and match_inventory couldn't filter on it, so a male scan
-- was getting saris/tunics. Column is backfilled from the source dataset by
-- scripts/backfill_gender.py (values: male | female | unisex | kids).
alter table inventory add column if not exists gender text;
create index if not exists inventory_gender_idx on inventory(gender);

-- 6a. Bulk gender backfill RPC (scripts/backfill_gender.py)
create or replace function bulk_update_gender(
    ids uuid[],
    genders text[]
)
returns void
language sql
as $$
    update inventory
    set gender = data.gender
    from (
        select unnest(ids) as id, unnest(genders) as gender
    ) as data
    where inventory.id = data.id;
$$;

-- 6b. match_inventory with optional gender filter. Postgres won't let
-- CREATE OR REPLACE add a parameter (it'd create an overload, and PostgREST
-- then can't choose between them), so drop the 3-arg version first.
-- null match_gender = old behaviour exactly. With a gender: that gender,
-- unisex, and not-yet-backfilled (null) rows pass -- inventory_search.py's
-- apply_catalog_filters does the name-based check on the null ones -- and
-- kids' rows never pass.
drop function if exists match_inventory(vector, text, integer);
create or replace function match_inventory(
    query_embedding vector(512),
    match_category text default null,
    match_count int default 10,
    match_gender text default null
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
    year int,
    gender text
)
language sql stable
as $$
    select
        id, name, category, color, occasion, image_url, price, stock,
        1 - (embedding <=> query_embedding) as similarity,
        created_at, season, year, gender
    from inventory
    where (match_category is null or category = match_category)
      and stock > 0
      and (
            match_gender is null
            or gender is null
            or gender = match_gender
            or gender = 'unisex'
          )
      and coalesce(gender, '') <> 'kids'
    order by embedding <=> query_embedding
    limit match_count;
$$;

-- 7. HNSW POST-FILTER RECALL FIX (match_inventory)
-- pgvector's HNSW scan collects hnsw.ef_search (default 40) nearest rows
-- FIRST and only then applies the WHERE clause. For a small slice of the
-- catalog -- men's bottoms is ~3% of rows -- that left 0-2 survivors even
-- with match_count=6, so a post-scan "complete look" was missing whole
-- sections (confirmed live). This version raises ef_search for the call
-- and, on pgvector >= 0.8, turns on iterative scanning so the index keeps
-- going until match_count rows actually pass the filter. Same signature
-- and return type as section 6b, so it's a drop-in replacement.
create or replace function match_inventory(
    query_embedding vector(512),
    match_category text default null,
    match_count int default 10,
    match_gender text default null
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
    year int,
    gender text
)
language plpgsql stable
as $$
begin
    -- transaction-local (is_local = true): PostgREST wraps each RPC in its
    -- own transaction, so this never leaks into other queries.
    perform set_config('hnsw.ef_search', '400', true);
    begin
        perform set_config('hnsw.iterative_scan', 'relaxed_order', true);
    exception when others then
        null;  -- pgvector < 0.8: no iterative scans, ef_search alone still helps
    end;
    return query
    select
        i.id, i.name, i.category, i.color, i.occasion, i.image_url, i.price, i.stock,
        1 - (i.embedding <=> query_embedding) as similarity,
        i.created_at, i.season, i.year, i.gender
    from inventory i
    where (match_category is null or i.category = match_category)
      and i.stock > 0
      and (
            match_gender is null
            or i.gender is null
            or i.gender = match_gender
            or i.gender = 'unisex'
          )
      and coalesce(i.gender, '') <> 'kids'
    order by i.embedding <=> query_embedding
    limit match_count;
end;
$$;
