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

create index if not exists inventory_embedding_idx
    on inventory using ivfflat (embedding vector_cosine_ops) with (lists = 100);

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

-- Helper RPC for vector similarity search from Python
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
    similarity float
)
language sql stable
as $$
    select
        id, name, category, color, occasion, image_url, price,
        1 - (embedding <=> query_embedding) as similarity
    from inventory
    where match_category is null or category = match_category
    order by embedding <=> query_embedding
    limit match_count;
$$;
