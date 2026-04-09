-- Migration : fusion des 4 tables staging_* en une seule table staging
-- Les staging_id dans hal_documents, openalex_documents, wos_documents sont mis à jour.

BEGIN;

-- 1. Créer la table unifiée
CREATE TABLE staging (
    id           SERIAL PRIMARY KEY,
    source       TEXT NOT NULL,          -- 'hal', 'openalex', 'wos', 'scanr', ...
    source_id    TEXT NOT NULL,          -- halid / openalex_id / ut / scanr_id
    doi          TEXT,
    raw_data     JSONB NOT NULL,
    processed    BOOLEAN DEFAULT FALSE,
    imported_at  TIMESTAMPTZ DEFAULT now(),
    raw_hash     TEXT,
    last_seen_at TIMESTAMPTZ DEFAULT now(),
    meta_hash    TEXT,                   -- utilisé par openalex
    collection   TEXT,                   -- utilisé par hal
    UNIQUE (source, source_id)
);

-- 2. Supprimer les anciennes FK (avant le remapping des IDs)
ALTER TABLE hal_documents DROP CONSTRAINT hal_documents_staging_id_fkey;
ALTER TABLE openalex_documents DROP CONSTRAINT openalex_documents_staging_id_fkey;
ALTER TABLE wos_documents DROP CONSTRAINT wos_documents_staging_id_fkey;
ALTER TABLE scanr_documents DROP CONSTRAINT scanr_documents_staging_id_fkey;

-- 3. Migrer les données et mettre à jour les FK

-- HAL
WITH inserted AS (
    INSERT INTO staging (source, source_id, doi, raw_data, processed, imported_at, raw_hash, last_seen_at, collection)
    SELECT 'hal', halid, doi, raw_data, processed, imported_at, raw_hash, last_seen_at, collection
    FROM staging_hal
    RETURNING id, source_id
)
UPDATE hal_documents hd
SET staging_id = inserted.id
FROM inserted
JOIN staging_hal sh ON sh.halid = inserted.source_id
WHERE hd.staging_id = sh.id;

-- OpenAlex
WITH inserted AS (
    INSERT INTO staging (source, source_id, doi, raw_data, processed, imported_at, raw_hash, last_seen_at, meta_hash)
    SELECT 'openalex', openalex_id, doi, raw_data, processed, imported_at, raw_hash, last_seen_at, meta_hash
    FROM staging_openalex
    RETURNING id, source_id
)
UPDATE openalex_documents od
SET staging_id = inserted.id
FROM inserted
JOIN staging_openalex so ON so.openalex_id = inserted.source_id
WHERE od.staging_id = so.id;

-- WoS
WITH inserted AS (
    INSERT INTO staging (source, source_id, doi, raw_data, processed, imported_at, raw_hash, last_seen_at)
    SELECT 'wos', ut, doi, raw_data, processed, imported_at, raw_hash, last_seen_at
    FROM staging_wos
    RETURNING id, source_id
)
UPDATE wos_documents wd
SET staging_id = inserted.id
FROM inserted
JOIN staging_wos sw ON sw.ut = inserted.source_id
WHERE wd.staging_id = sw.id;

-- ScanR
WITH inserted AS (
    INSERT INTO staging (source, source_id, doi, raw_data, processed, imported_at, raw_hash, last_seen_at)
    SELECT 'scanr', scanr_id, doi, raw_data, processed, imported_at, raw_hash, last_seen_at
    FROM staging_scanr
    RETURNING id, source_id
)
UPDATE scanr_documents sd
SET staging_id = inserted.id
FROM inserted
JOIN staging_scanr ss ON ss.scanr_id = inserted.source_id
WHERE sd.staging_id = ss.id;

-- 4. Recréer les FK vers la table unifiée
ALTER TABLE hal_documents
    ADD CONSTRAINT hal_documents_staging_id_fkey FOREIGN KEY (staging_id) REFERENCES staging(id);
ALTER TABLE openalex_documents
    ADD CONSTRAINT openalex_documents_staging_id_fkey FOREIGN KEY (staging_id) REFERENCES staging(id);
ALTER TABLE wos_documents
    ADD CONSTRAINT wos_documents_staging_id_fkey FOREIGN KEY (staging_id) REFERENCES staging(id);
ALTER TABLE scanr_documents
    ADD CONSTRAINT scanr_documents_staging_id_fkey FOREIGN KEY (staging_id) REFERENCES staging(id);

-- 5. Index
CREATE INDEX idx_staging_source ON staging (source);
CREATE INDEX idx_staging_doi ON staging (doi) WHERE doi IS NOT NULL;
CREATE INDEX idx_staging_processed ON staging (processed) WHERE NOT processed;

-- 6. Supprimer les anciennes tables
DROP TABLE staging_hal CASCADE;
DROP TABLE staging_openalex CASCADE;
DROP TABLE staging_wos CASCADE;
DROP TABLE staging_scanr CASCADE;

COMMIT;
