-- Tables normalisées pour la source ScanR.
-- Architecture identique aux autres sources : documents, authors, authorships.

-- ── Documents ──
CREATE TABLE IF NOT EXISTS scanr_documents (
    id             SERIAL PRIMARY KEY,
    scanr_id       TEXT NOT NULL UNIQUE,       -- ex: "doi10.1234/abc" ou "halhal-01234567"
    doi            TEXT,
    title          TEXT NOT NULL,
    pub_year       SMALLINT,
    doc_type       TEXT,                        -- type natif ScanR (journal-article, book-chapter, etc.)
    publication_id INTEGER REFERENCES publications(id) ON DELETE SET NULL,
    staging_id     INTEGER REFERENCES staging_scanr(id),
    created_at     TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_scanr_docs_doi ON scanr_documents (doi) WHERE doi IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_scanr_docs_pub ON scanr_documents (publication_id) WHERE publication_id IS NOT NULL;

-- ── Authors ──
CREATE TABLE IF NOT EXISTS scanr_authors (
    id         SERIAL PRIMARY KEY,
    idref      TEXT UNIQUE,                    -- clé de déduplication (identifiant IdRef)
    full_name  TEXT NOT NULL,
    last_name  TEXT,
    first_name TEXT,
    orcid      TEXT,
    person_id  INTEGER REFERENCES persons(id) ON DELETE SET NULL,
    is_reliable BOOLEAN DEFAULT true,
    notes      TEXT,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_scanr_authors_orcid ON scanr_authors (orcid) WHERE orcid IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_scanr_authors_name ON scanr_authors (last_name, first_name);

-- ── Authorships ──
CREATE TABLE IF NOT EXISTS scanr_authorships (
    id                     SERIAL PRIMARY KEY,
    scanr_document_id      INTEGER NOT NULL REFERENCES scanr_documents(id) ON DELETE CASCADE,
    scanr_author_id        INTEGER NOT NULL REFERENCES scanr_authors(id) ON DELETE CASCADE,
    author_position        SMALLINT,
    role                   TEXT,                -- "author", "directeur de thèse", etc.
    raw_affiliations       JSONB,              -- affiliations brutes par auteur (noms, ids, pays)
    affiliation_ids        TEXT[],             -- IDs structures résolues (SIREN, RNSR, GRID)
    detected_countries     TEXT[],             -- pays détectés par ScanR
    is_uca                 BOOLEAN DEFAULT false,
    excluded               BOOLEAN DEFAULT false,
    structure_ids          INTEGER[],          -- IDs structures internes (résolution UCA)
    countries              TEXT[],
    person_id              INTEGER REFERENCES persons(id) ON DELETE SET NULL,
    author_name_normalized TEXT,
    UNIQUE (scanr_document_id, scanr_author_id)
);

CREATE INDEX IF NOT EXISTS idx_scanr_as_author ON scanr_authorships (scanr_author_id);
CREATE INDEX IF NOT EXISTS idx_scanr_as_doc ON scanr_authorships (scanr_document_id);
CREATE INDEX IF NOT EXISTS idx_scanr_as_person ON scanr_authorships (person_id) WHERE person_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_scanr_as_name_norm ON scanr_authorships (author_name_normalized) WHERE author_name_normalized IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_scanr_as_structs ON scanr_authorships USING gin (structure_ids) WHERE structure_ids IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_scanr_as_uca ON scanr_authorships (is_uca) WHERE is_uca = true;
