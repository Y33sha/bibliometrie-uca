-- Migration : fusion des 4 tables *_documents en une seule table source_documents
-- + remapping des FK *_document_id dans les 4 tables *_authorships

BEGIN;

-- ══════════════════════════════════════════════════════════════════
-- 1. Créer la table unifiée source_documents
-- ══════════════════════════════════════════════════════════════════

CREATE TABLE source_documents (
    id              SERIAL PRIMARY KEY,
    source          TEXT NOT NULL,         -- 'hal', 'openalex', 'wos', 'scanr', 'theses', ...
    source_id       TEXT NOT NULL,         -- halid / openalex_id / ut / scanr_id / nnt
    doi             TEXT,
    title           TEXT NOT NULL,
    pub_year        SMALLINT,
    doc_type        TEXT,
    publication_id  INTEGER REFERENCES publications(id) ON DELETE SET NULL,
    staging_id      INTEGER REFERENCES staging(id),
    created_at      TIMESTAMPTZ DEFAULT now(),
    countries       TEXT[],
    collections     TEXT[],               -- HAL collections, NULL pour les autres
    external_ids    JSONB,                -- {"hal": "hal-01234", "arxiv": "2301.12345", ...}
    UNIQUE (source, source_id)
);

-- ══════════════════════════════════════════════════════════════════
-- 2. Supprimer les anciennes FK des authorships → documents
-- ══════════════════════════════════════════════════════════════════

ALTER TABLE hal_authorships DROP CONSTRAINT hal_authorships_hal_document_id_fkey;
ALTER TABLE openalex_authorships DROP CONSTRAINT openalex_authorships_openalex_document_id_fkey;
ALTER TABLE wos_authorships DROP CONSTRAINT wos_authorships_wos_document_id_fkey;
ALTER TABLE scanr_authorships DROP CONSTRAINT scanr_authorships_scanr_document_id_fkey;

-- ══════════════════════════════════════════════════════════════════
-- 3. Ajouter source_document_id aux authorships (temporairement nullable)
-- ══════════════════════════════════════════════════════════════════

ALTER TABLE hal_authorships ADD COLUMN source_document_id INTEGER;
ALTER TABLE openalex_authorships ADD COLUMN source_document_id INTEGER;
ALTER TABLE wos_authorships ADD COLUMN source_document_id INTEGER;
ALTER TABLE scanr_authorships ADD COLUMN source_document_id INTEGER;

-- ══════════════════════════════════════════════════════════════════
-- 4. Migrer les données et remapper les FK
-- ══════════════════════════════════════════════════════════════════

-- HAL
WITH inserted AS (
    INSERT INTO source_documents (source, source_id, doi, title, pub_year, doc_type,
                                  publication_id, staging_id, created_at, countries, collections)
    SELECT 'hal', halid, doi, title, pub_year, doc_type,
           publication_id, staging_id, created_at, countries, collections
    FROM hal_documents
    RETURNING id, source_id
)
UPDATE hal_authorships ha
SET source_document_id = inserted.id
FROM inserted
JOIN hal_documents hd ON hd.halid = inserted.source_id
WHERE ha.hal_document_id = hd.id;

-- OpenAlex
WITH inserted AS (
    INSERT INTO source_documents (source, source_id, doi, title, pub_year, doc_type,
                                  publication_id, staging_id, created_at, countries)
    SELECT 'openalex', openalex_id, doi, title, pub_year, doc_type,
           publication_id, staging_id, created_at, countries
    FROM openalex_documents
    RETURNING id, source_id
)
UPDATE openalex_authorships oa
SET source_document_id = inserted.id
FROM inserted
JOIN openalex_documents od ON od.openalex_id = inserted.source_id
WHERE oa.openalex_document_id = od.id;

-- WoS
WITH inserted AS (
    INSERT INTO source_documents (source, source_id, doi, title, pub_year, doc_type,
                                  publication_id, staging_id, created_at, countries)
    SELECT 'wos', ut, doi, title, pub_year, doc_type,
           publication_id, staging_id, created_at, countries
    FROM wos_documents
    RETURNING id, source_id
)
UPDATE wos_authorships wa
SET source_document_id = inserted.id
FROM inserted
JOIN wos_documents wd ON wd.ut = inserted.source_id
WHERE wa.wos_document_id = wd.id;

-- ScanR (hal_id → external_ids)
WITH inserted AS (
    INSERT INTO source_documents (source, source_id, doi, title, pub_year, doc_type,
                                  publication_id, staging_id, created_at,
                                  external_ids)
    SELECT 'scanr', scanr_id, doi, title, pub_year, doc_type,
           publication_id, staging_id, created_at,
           CASE WHEN hal_id IS NOT NULL THEN jsonb_build_object('hal', hal_id) END
    FROM scanr_documents
    RETURNING id, source_id
)
UPDATE scanr_authorships sa
SET source_document_id = inserted.id
FROM inserted
JOIN scanr_documents sd ON sd.scanr_id = inserted.source_id
WHERE sa.scanr_document_id = sd.id;

-- ══════════════════════════════════════════════════════════════════
-- 5. Supprimer les anciennes colonnes et ajouter les contraintes
-- ══════════════════════════════════════════════════════════════════

-- Rendre source_document_id NOT NULL + FK
ALTER TABLE hal_authorships ALTER COLUMN source_document_id SET NOT NULL;
ALTER TABLE openalex_authorships ALTER COLUMN source_document_id SET NOT NULL;
ALTER TABLE wos_authorships ALTER COLUMN source_document_id SET NOT NULL;
ALTER TABLE scanr_authorships ALTER COLUMN source_document_id SET NOT NULL;

ALTER TABLE hal_authorships
    ADD CONSTRAINT hal_authorships_source_document_id_fkey
    FOREIGN KEY (source_document_id) REFERENCES source_documents(id) ON DELETE CASCADE;
ALTER TABLE openalex_authorships
    ADD CONSTRAINT openalex_authorships_source_document_id_fkey
    FOREIGN KEY (source_document_id) REFERENCES source_documents(id) ON DELETE CASCADE;
ALTER TABLE wos_authorships
    ADD CONSTRAINT wos_authorships_source_document_id_fkey
    FOREIGN KEY (source_document_id) REFERENCES source_documents(id) ON DELETE CASCADE;
ALTER TABLE scanr_authorships
    ADD CONSTRAINT scanr_authorships_source_document_id_fkey
    FOREIGN KEY (source_document_id) REFERENCES source_documents(id) ON DELETE CASCADE;

-- Supprimer les anciennes colonnes document_id
ALTER TABLE hal_authorships DROP COLUMN hal_document_id;
ALTER TABLE openalex_authorships DROP COLUMN openalex_document_id;
ALTER TABLE wos_authorships DROP COLUMN wos_document_id;
ALTER TABLE scanr_authorships DROP COLUMN scanr_document_id;

-- ══════════════════════════════════════════════════════════════════
-- 6. Recréer les contraintes UNIQUE sur les authorships
-- ══════════════════════════════════════════════════════════════════

-- Les anciennes UNIQUE(hal_document_id, hal_author_id) etc. sont supprimées
-- avec le DROP COLUMN. On recrée avec source_document_id.
ALTER TABLE hal_authorships
    ADD CONSTRAINT hal_authorships_source_document_id_hal_author_id_key
    UNIQUE (source_document_id, hal_author_id);
ALTER TABLE openalex_authorships
    ADD CONSTRAINT openalex_authorships_source_document_id_oa_author_id_key
    UNIQUE (source_document_id, openalex_author_id);
ALTER TABLE wos_authorships
    ADD CONSTRAINT wos_authorships_source_document_id_wos_author_id_key
    UNIQUE (source_document_id, wos_author_id);
ALTER TABLE scanr_authorships
    ADD CONSTRAINT scanr_authorships_source_document_id_scanr_author_id_key
    UNIQUE (source_document_id, scanr_author_id);

-- ══════════════════════════════════════════════════════════════════
-- 7. Index sur source_documents
-- ══════════════════════════════════════════════════════════════════

CREATE INDEX idx_source_docs_source ON source_documents (source);
CREATE INDEX idx_source_docs_doi ON source_documents (doi) WHERE doi IS NOT NULL;
CREATE INDEX idx_source_docs_pub ON source_documents (publication_id) WHERE publication_id IS NOT NULL;
CREATE INDEX idx_source_docs_countries ON source_documents USING GIN (countries) WHERE countries IS NOT NULL;
CREATE INDEX idx_source_docs_collections ON source_documents USING GIN (collections) WHERE collections IS NOT NULL;
CREATE INDEX idx_source_docs_external_ids ON source_documents USING GIN (external_ids) WHERE external_ids IS NOT NULL;
CREATE INDEX idx_source_docs_staging ON source_documents (staging_id) WHERE staging_id IS NOT NULL;

-- Index sur authorships (remplacent les anciens idx_*_as_doc et idx_*_as_doc_uca_structs)
CREATE INDEX idx_hal_as_source_doc ON hal_authorships (source_document_id);
CREATE INDEX idx_hal_as_source_doc_uca ON hal_authorships (source_document_id) INCLUDE (structure_ids) WHERE (is_uca = true);
CREATE INDEX idx_oa_as_source_doc ON openalex_authorships (source_document_id);
CREATE INDEX idx_oa_as_source_doc_uca ON openalex_authorships (source_document_id) INCLUDE (structure_ids) WHERE (is_uca = true);
CREATE INDEX idx_oa_as_pos_affil ON openalex_authorships (source_document_id, author_position) WHERE (is_uca = false AND raw_affiliation IS NOT NULL AND raw_affiliation <> '');
CREATE INDEX idx_wos_as_source_doc ON wos_authorships (source_document_id);
CREATE INDEX idx_wos_as_source_doc_uca ON wos_authorships (source_document_id) INCLUDE (structure_ids) WHERE (is_uca = true);
CREATE INDEX idx_wos_as_pos_affil ON wos_authorships (source_document_id, author_position) WHERE (is_uca = false AND raw_affiliation IS NOT NULL AND raw_affiliation <> '');
CREATE INDEX idx_scanr_as_source_doc ON scanr_authorships (source_document_id);

-- ══════════════════════════════════════════════════════════════════
-- 8. Supprimer les anciennes tables et FK staging
-- ══════════════════════════════════════════════════════════════════

ALTER TABLE hal_documents DROP CONSTRAINT hal_documents_staging_id_fkey;
ALTER TABLE openalex_documents DROP CONSTRAINT openalex_documents_staging_id_fkey;
ALTER TABLE wos_documents DROP CONSTRAINT wos_documents_staging_id_fkey;
ALTER TABLE scanr_documents DROP CONSTRAINT scanr_documents_staging_id_fkey;

DROP TABLE hal_documents CASCADE;
DROP TABLE openalex_documents CASCADE;
DROP TABLE wos_documents CASCADE;
DROP TABLE scanr_documents CASCADE;

COMMIT;
