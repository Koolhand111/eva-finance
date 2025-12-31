CREATE TABLE IF NOT EXISTS raw_messages (
    id SERIAL PRIMARY KEY,
    source TEXT NOT NULL,
    platform_id TEXT,
    timestamp TIMESTAMPTZ NOT NULL,
    text TEXT NOT NULL,
    url TEXT,
    meta JSONB DEFAULT '{}'::jsonb,
    processed BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS processed_messages (
    id SERIAL PRIMARY KEY,
    raw_id INTEGER NOT NULL REFERENCES raw_messages(id) ON DELETE CASCADE,
    brand TEXT[] DEFAULT '{}',
    product TEXT[] DEFAULT '{}',
    category TEXT[] DEFAULT '{}',
    sentiment TEXT,
    intent TEXT,
    tickers TEXT[] DEFAULT '{}',
    tags TEXT[] DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW()
);
