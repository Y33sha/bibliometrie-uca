-- Table staging pour les publications ScanR (Elasticsearch MESR)
CREATE TABLE IF NOT EXISTS staging_scanr (
    id           SERIAL PRIMARY KEY,
    scanr_id     TEXT NOT NULL UNIQUE,     -- ex: "doi10.1234/abc" ou "halhal-01234567"
    doi          TEXT,
    raw_data     JSONB NOT NULL,
    processed    BOOLEAN DEFAULT FALSE,
    imported_at  TIMESTAMPTZ DEFAULT now(),
    raw_hash     TEXT,
    last_seen_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_staging_scanr_doi ON staging_scanr (doi) WHERE doi IS NOT NULL;
