CREATE TABLE IF NOT EXISTS messages (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    received_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    source VARCHAR(10) NOT NULL CHECK (source IN ('nwws', 'api')),
    wmo_heading VARCHAR(10),
    awips_id VARCHAR(20),
    pil_code VARCHAR(10) NOT NULL,
    office VARCHAR(10) NOT NULL,
    product_text TEXT NOT NULL,
    is_deleted BOOLEAN DEFAULT FALSE,
    deleted_at TIMESTAMPTZ,
    expires_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_messages_received_at ON messages (received_at DESC);
CREATE INDEX IF NOT EXISTS idx_messages_pil_code ON messages (pil_code);
CREATE INDEX IF NOT EXISTS idx_messages_office ON messages (office);
CREATE INDEX IF NOT EXISTS idx_messages_source ON messages (source);
CREATE INDEX IF NOT EXISTS idx_messages_not_deleted ON messages (received_at DESC) WHERE is_deleted = FALSE;

CREATE TABLE IF NOT EXISTS filters (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(100) NOT NULL,
    type VARCHAR(20) NOT NULL CHECK (type IN ('product', 'office', 'zone', 'location')),
    mode VARCHAR(10) NOT NULL CHECK (mode IN ('include', 'exclude')),
    values TEXT[] NOT NULL DEFAULT '{}',
    enabled BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS settings (
    key VARCHAR(50) PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

INSERT INTO settings (key, value) VALUES
    ('retention_days', '30'),
    ('api_poll_interval', '30'),
    ('data_source', 'api')
ON CONFLICT (key) DO NOTHING;
