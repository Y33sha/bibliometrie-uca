-- =============================================================
-- Migration 014a : Création des nouvelles tables (schéma v2)
-- =============================================================
-- Crée les 11 nouvelles tables nécessaires au schéma v2 :
--   - person_identifiers
--   - hal_authors, hal_documents, hal_authorships
--   - openalex_institutions, openalex_authors, openalex_documents, openalex_authorships
--   - authorships (table de vérité)
--   - address_structures (remplace address_laboratories)
--   - openalex_authorship_addresses (remplace publication_author_addresses)
--
-- Prérequis : migrations 001–013 appliquées.
-- Aucune donnée n'est modifiée ; les anciennes tables restent intactes.
-- =============================================================

BEGIN;


-- =============================================================
-- 1. person_identifiers
-- =============================================================

CREATE TABLE IF NOT EXISTS person_identifiers (
    id          SERIAL PRIMARY KEY,
    person_id   INT NOT NULL REFERENCES persons(id) ON DELETE CASCADE,
    id_type     TEXT NOT NULL,                   -- 'orcid', 'idhal', 'researcher_id', etc.
    id_value    TEXT NOT NULL,
    verified    BOOLEAN DEFAULT FALSE,
    source      TEXT,                            -- provenance : 'hr', 'hal', 'openalex', 'manual'
    created_at  TIMESTAMPTZ DEFAULT now(),
    UNIQUE (id_type, id_value)
);

CREATE INDEX IF NOT EXISTS idx_person_ids_person ON person_identifiers (person_id);
CREATE INDEX IF NOT EXISTS idx_person_ids_lookup ON person_identifiers (id_type, id_value);


-- =============================================================
-- 2. hal_authors
-- =============================================================

CREATE TABLE IF NOT EXISTS hal_authors (
    id              SERIAL PRIMARY KEY,
    hal_person_id   INT UNIQUE,
    full_name       TEXT NOT NULL,
    last_name       TEXT,
    first_name      TEXT,
    idhal           TEXT,
    orcid           TEXT,
    -- Lien vers vérité
    person_id       INT REFERENCES persons(id) ON DELETE SET NULL,
    is_reliable     BOOLEAN DEFAULT TRUE,
    notes           TEXT,
    created_at      TIMESTAMPTZ DEFAULT now(),
    updated_at      TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_hal_authors_person ON hal_authors (person_id) WHERE person_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_hal_authors_idhal ON hal_authors (idhal) WHERE idhal IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_hal_authors_orcid ON hal_authors (orcid) WHERE orcid IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_hal_authors_name ON hal_authors (last_name, first_name);


-- =============================================================
-- 3. hal_documents
-- =============================================================

CREATE TABLE IF NOT EXISTS hal_documents (
    id              SERIAL PRIMARY KEY,
    halid           TEXT NOT NULL UNIQUE,
    doi             TEXT,
    title           TEXT NOT NULL,
    pub_year        SMALLINT,
    doc_type        TEXT,
    collections     TEXT[],
    -- Lien vers vérité
    publication_id  INT REFERENCES publications(id) ON DELETE SET NULL,
    staging_id      INT REFERENCES staging_hal(id),
    created_at      TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_hal_docs_doi ON hal_documents (doi) WHERE doi IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_hal_docs_pub ON hal_documents (publication_id) WHERE publication_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_hal_docs_collections ON hal_documents USING GIN (collections);


-- =============================================================
-- 4. hal_authorships
-- =============================================================

CREATE TABLE IF NOT EXISTS hal_authorships (
    id                  SERIAL PRIMARY KEY,
    hal_document_id     INT NOT NULL REFERENCES hal_documents(id) ON DELETE CASCADE,
    hal_author_id       INT NOT NULL REFERENCES hal_authors(id) ON DELETE CASCADE,
    author_position     SMALLINT,
    hal_struct_ids      INT[],
    is_uca              BOOLEAN DEFAULT FALSE,
    structure_id        INT REFERENCES structures(id) ON DELETE SET NULL,
    excluded            BOOLEAN DEFAULT FALSE,
    UNIQUE (hal_document_id, hal_author_id)
);

CREATE INDEX IF NOT EXISTS idx_hal_as_doc ON hal_authorships (hal_document_id);
CREATE INDEX IF NOT EXISTS idx_hal_as_author ON hal_authorships (hal_author_id);
CREATE INDEX IF NOT EXISTS idx_hal_as_uca ON hal_authorships (is_uca) WHERE is_uca = TRUE;
CREATE INDEX IF NOT EXISTS idx_hal_as_struct ON hal_authorships (structure_id) WHERE structure_id IS NOT NULL;


-- =============================================================
-- 5. openalex_institutions
-- =============================================================

CREATE TABLE IF NOT EXISTS openalex_institutions (
    id              SERIAL PRIMARY KEY,
    openalex_id     TEXT NOT NULL UNIQUE,
    name            TEXT NOT NULL,
    ror_id          TEXT,
    country_code    TEXT,
    type            TEXT,
    -- Lien vers vérité
    structure_id    INT REFERENCES structures(id) ON DELETE SET NULL,
    created_at      TIMESTAMPTZ DEFAULT now(),
    updated_at      TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_oa_inst_struct ON openalex_institutions (structure_id) WHERE structure_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_oa_inst_ror ON openalex_institutions (ror_id) WHERE ror_id IS NOT NULL;


-- =============================================================
-- 6. openalex_authors
-- =============================================================

CREATE TABLE IF NOT EXISTS openalex_authors (
    id              SERIAL PRIMARY KEY,
    openalex_id     TEXT NOT NULL UNIQUE,
    full_name       TEXT NOT NULL,
    last_name       TEXT,
    first_name      TEXT,
    orcid           TEXT,
    -- Lien vers vérité
    person_id       INT REFERENCES persons(id) ON DELETE SET NULL,
    is_reliable     BOOLEAN DEFAULT TRUE,
    notes           TEXT,
    created_at      TIMESTAMPTZ DEFAULT now(),
    updated_at      TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_oa_authors_person ON openalex_authors (person_id) WHERE person_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_oa_authors_orcid ON openalex_authors (orcid) WHERE orcid IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_oa_authors_name ON openalex_authors (last_name, first_name);


-- =============================================================
-- 7. openalex_documents
-- =============================================================

CREATE TABLE IF NOT EXISTS openalex_documents (
    id              SERIAL PRIMARY KEY,
    openalex_id     TEXT NOT NULL UNIQUE,
    doi             TEXT,
    title           TEXT NOT NULL,
    pub_year        SMALLINT,
    doc_type        TEXT,
    -- Lien vers vérité
    publication_id  INT REFERENCES publications(id) ON DELETE SET NULL,
    staging_id      INT REFERENCES staging_openalex(id),
    created_at      TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_oa_docs_doi ON openalex_documents (doi) WHERE doi IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_oa_docs_pub ON openalex_documents (publication_id) WHERE publication_id IS NOT NULL;


-- =============================================================
-- 8. openalex_authorships
-- =============================================================

CREATE TABLE IF NOT EXISTS openalex_authorships (
    id                      SERIAL PRIMARY KEY,
    openalex_document_id    INT NOT NULL REFERENCES openalex_documents(id) ON DELETE CASCADE,
    openalex_author_id      INT NOT NULL REFERENCES openalex_authors(id) ON DELETE CASCADE,
    author_position         SMALLINT,
    raw_affiliation         TEXT,
    openalex_institution_ids TEXT[],
    is_uca                  BOOLEAN DEFAULT FALSE,
    structure_id            INT REFERENCES structures(id) ON DELETE SET NULL,
    excluded                BOOLEAN DEFAULT FALSE,
    UNIQUE (openalex_document_id, openalex_author_id)
);

CREATE INDEX IF NOT EXISTS idx_oa_as_doc ON openalex_authorships (openalex_document_id);
CREATE INDEX IF NOT EXISTS idx_oa_as_author ON openalex_authorships (openalex_author_id);
CREATE INDEX IF NOT EXISTS idx_oa_as_uca ON openalex_authorships (is_uca) WHERE is_uca = TRUE;
CREATE INDEX IF NOT EXISTS idx_oa_as_struct ON openalex_authorships (structure_id) WHERE structure_id IS NOT NULL;


-- =============================================================
-- 9. authorships (table de vérité)
-- =============================================================

CREATE TABLE IF NOT EXISTS authorships (
    id              SERIAL PRIMARY KEY,
    publication_id  INT NOT NULL REFERENCES publications(id) ON DELETE CASCADE,
    person_id       INT REFERENCES persons(id) ON DELETE SET NULL,
    structure_id    INT REFERENCES structures(id) ON DELETE SET NULL,
    author_position SMALLINT,
    is_uca          BOOLEAN DEFAULT FALSE,
    -- Traçabilité sources
    source_hal      BOOLEAN DEFAULT FALSE,
    source_openalex BOOLEAN DEFAULT FALSE,
    source_wos      BOOLEAN DEFAULT FALSE,
    source_manual   BOOLEAN DEFAULT FALSE,
    -- Curation
    excluded        BOOLEAN DEFAULT FALSE,
    notes           TEXT,
    created_at      TIMESTAMPTZ DEFAULT now(),
    updated_at      TIMESTAMPTZ DEFAULT now(),
    UNIQUE (publication_id, person_id, structure_id)
);

CREATE INDEX IF NOT EXISTS idx_authorships_pub ON authorships (publication_id);
CREATE INDEX IF NOT EXISTS idx_authorships_person ON authorships (person_id) WHERE person_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_authorships_struct ON authorships (structure_id) WHERE structure_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_authorships_uca ON authorships (is_uca) WHERE is_uca = TRUE;


-- =============================================================
-- 10. address_structures (remplace address_laboratories)
-- =============================================================

CREATE TABLE IF NOT EXISTS address_structures (
    id              SERIAL PRIMARY KEY,
    address_id      INT NOT NULL REFERENCES addresses(id) ON DELETE CASCADE,
    structure_id    INT NOT NULL REFERENCES structures(id) ON DELETE CASCADE,
    matched_form_id INT REFERENCES name_forms(id) ON DELETE SET NULL,
    is_confirmed    BOOLEAN DEFAULT FALSE,
    UNIQUE (address_id, structure_id)
);

CREATE INDEX IF NOT EXISTS idx_addr_struct_address ON address_structures (address_id);
CREATE INDEX IF NOT EXISTS idx_addr_struct_structure ON address_structures (structure_id);


-- =============================================================
-- 11. openalex_authorship_addresses
-- =============================================================

CREATE TABLE IF NOT EXISTS openalex_authorship_addresses (
    id                      SERIAL PRIMARY KEY,
    openalex_authorship_id  INT NOT NULL REFERENCES openalex_authorships(id) ON DELETE CASCADE,
    address_id              INT NOT NULL REFERENCES addresses(id) ON DELETE CASCADE,
    UNIQUE (openalex_authorship_id, address_id)
);


COMMIT;
