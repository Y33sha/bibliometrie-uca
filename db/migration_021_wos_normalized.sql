-- Migration 021 : Tables normalisées WoS
-- Même architecture que HAL/OpenAlex : documents, authors, authorships

BEGIN;

-- =====================================================
-- wos_documents
-- =====================================================
CREATE TABLE IF NOT EXISTS wos_documents (
    id          SERIAL PRIMARY KEY,
    ut          TEXT NOT NULL UNIQUE,
    doi         TEXT,
    title       TEXT NOT NULL,
    pub_year    SMALLINT,
    doc_type    TEXT,
    publication_id INTEGER REFERENCES publications(id) ON DELETE SET NULL,
    staging_id  INTEGER REFERENCES staging_wos(id),
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_wos_docs_doi ON wos_documents(doi) WHERE doi IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_wos_docs_pub ON wos_documents(publication_id) WHERE publication_id IS NOT NULL;

-- =====================================================
-- wos_authors
-- =====================================================
CREATE TABLE IF NOT EXISTS wos_authors (
    id              SERIAL PRIMARY KEY,
    full_name       TEXT NOT NULL,
    last_name       TEXT,
    first_name      TEXT,
    daisng_id       TEXT UNIQUE,
    orcid           TEXT,
    researcher_id   TEXT,
    person_id       INTEGER REFERENCES persons(id) ON DELETE SET NULL,
    is_reliable     BOOLEAN DEFAULT TRUE,
    notes           TEXT,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_wos_authors_name ON wos_authors(last_name, first_name);
CREATE INDEX IF NOT EXISTS idx_wos_authors_orcid ON wos_authors(orcid) WHERE orcid IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_wos_authors_person ON wos_authors(person_id) WHERE person_id IS NOT NULL;

-- =====================================================
-- wos_authorships
-- =====================================================
CREATE TABLE IF NOT EXISTS wos_authorships (
    id                  SERIAL PRIMARY KEY,
    wos_document_id     INTEGER NOT NULL REFERENCES wos_documents(id) ON DELETE CASCADE,
    wos_author_id       INTEGER NOT NULL REFERENCES wos_authors(id) ON DELETE CASCADE,
    author_position     SMALLINT,
    is_corresponding    BOOLEAN DEFAULT FALSE,
    raw_affiliation     TEXT,
    is_uca              BOOLEAN DEFAULT FALSE,
    excluded            BOOLEAN DEFAULT FALSE,
    structure_ids       INTEGER[],
    UNIQUE (wos_document_id, wos_author_id)
);

CREATE INDEX IF NOT EXISTS idx_wos_as_author ON wos_authorships(wos_author_id);
CREATE INDEX IF NOT EXISTS idx_wos_as_doc ON wos_authorships(wos_document_id);
CREATE INDEX IF NOT EXISTS idx_wos_as_uca ON wos_authorships(is_uca) WHERE is_uca = TRUE;
CREATE INDEX IF NOT EXISTS idx_wos_as_structs ON wos_authorships USING gin(structure_ids) WHERE structure_ids IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_wos_as_doc_uca_structs ON wos_authorships(wos_document_id) INCLUDE (structure_ids) WHERE is_uca = TRUE;

-- =====================================================
-- Mise à jour de la vue publication_sources
-- =====================================================
CREATE OR REPLACE VIEW publication_sources AS
SELECT publication_id, 'hal'::source_type AS source, halid AS source_id
FROM hal_documents WHERE publication_id IS NOT NULL
UNION ALL
SELECT publication_id, 'openalex'::source_type AS source, openalex_id AS source_id
FROM openalex_documents WHERE publication_id IS NOT NULL
UNION ALL
SELECT publication_id, 'wos'::source_type AS source, ut AS source_id
FROM wos_documents WHERE publication_id IS NOT NULL;

COMMIT;
