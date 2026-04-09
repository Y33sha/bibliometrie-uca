-- Migration : fusion des 4 tables *_authorships en source_authorships
-- + renommage is_uca → in_perimeter

BEGIN;

-- ══════════════════════════════════════════════════════════════════
-- 1. Créer la table unifiée
-- ══════════════════════════════════════════════════════════════════

CREATE TABLE source_authorships (
    id                      SERIAL PRIMARY KEY,
    source                  TEXT NOT NULL,
    source_document_id      INTEGER NOT NULL REFERENCES source_documents(id) ON DELETE CASCADE,
    source_author_id        INTEGER NOT NULL REFERENCES source_authors(id) ON DELETE CASCADE,
    author_position         SMALLINT,
    in_perimeter            BOOLEAN DEFAULT FALSE,
    excluded                BOOLEAN DEFAULT FALSE,
    structure_ids           INTEGER[],
    source_struct_ids       INTEGER[],
    countries               TEXT[],
    person_id               INTEGER REFERENCES persons(id) ON DELETE SET NULL,
    author_name_normalized  TEXT,
    is_corresponding        BOOLEAN DEFAULT FALSE,
    roles                   TEXT[],
    raw_affiliations        JSONB,
    source_data             JSONB,
    UNIQUE (source_document_id, source_author_id)
);

-- ══════════════════════════════════════════════════════════════════
-- 2. Migrer les données (table par table, séquentiellement)
-- ══════════════════════════════════════════════════════════════════

-- HAL (~2,4M)
INSERT INTO source_authorships (source, source_document_id, source_author_id,
    author_position, in_perimeter, excluded, structure_ids, source_struct_ids,
    countries, person_id, author_name_normalized, is_corresponding, roles)
SELECT 'hal', source_document_id, source_author_id,
    author_position, is_uca, excluded, structure_ids, source_struct_ids,
    countries, person_id, author_name_normalized, is_corresponding, roles
FROM hal_authorships;

-- OpenAlex (~2,1M)
INSERT INTO source_authorships (source, source_document_id, source_author_id,
    author_position, in_perimeter, excluded, structure_ids, source_struct_ids,
    countries, person_id, author_name_normalized, is_corresponding, roles,
    raw_affiliations, source_data)
SELECT 'openalex', source_document_id, source_author_id,
    author_position, is_uca, excluded, structure_ids, source_struct_ids,
    countries, person_id, author_name_normalized, is_corresponding, roles,
    CASE WHEN raw_affiliation IS NOT NULL
         THEN jsonb_build_array(raw_affiliation)
    END,
    CASE WHEN raw_author_name IS NOT NULL
         THEN jsonb_build_object('raw_author_name', raw_author_name)
    END
FROM openalex_authorships;

-- WoS (~2,4M)
INSERT INTO source_authorships (source, source_document_id, source_author_id,
    author_position, in_perimeter, excluded, structure_ids, source_struct_ids,
    countries, person_id, author_name_normalized, is_corresponding, roles,
    raw_affiliations)
SELECT 'wos', source_document_id, source_author_id,
    author_position, is_uca, excluded, structure_ids, source_struct_ids,
    countries, person_id, author_name_normalized, is_corresponding, roles,
    CASE WHEN raw_affiliation IS NOT NULL
         THEN jsonb_build_array(raw_affiliation)
    END
FROM wos_authorships;

-- ScanR (~290k)
INSERT INTO source_authorships (source, source_document_id, source_author_id,
    author_position, in_perimeter, excluded, structure_ids,
    countries, person_id, author_name_normalized, roles,
    raw_affiliations, source_data)
SELECT 'scanr', source_document_id, source_author_id,
    author_position, is_uca, excluded, structure_ids,
    countries, person_id, author_name_normalized, roles,
    raw_affiliations,
    jsonb_strip_nulls(jsonb_build_object(
        'affiliation_ids', CASE WHEN affiliation_ids IS NOT NULL THEN to_jsonb(affiliation_ids) END,
        'detected_countries', CASE WHEN detected_countries IS NOT NULL THEN to_jsonb(detected_countries) END
    ))
FROM scanr_authorships;

-- ══════════════════════════════════════════════════════════════════
-- 3. Index
-- ══════════════════════════════════════════════════════════════════

CREATE INDEX idx_sa_source ON source_authorships (source);
CREATE INDEX idx_sa_source_doc ON source_authorships (source_document_id);
CREATE INDEX idx_sa_source_author ON source_authorships (source_author_id);
CREATE INDEX idx_sa_person ON source_authorships (person_id) WHERE person_id IS NOT NULL;
CREATE INDEX idx_sa_in_perimeter ON source_authorships (in_perimeter) WHERE in_perimeter = TRUE;
CREATE INDEX idx_sa_doc_perimeter ON source_authorships (source_document_id) INCLUDE (structure_ids) WHERE in_perimeter = TRUE;
CREATE INDEX idx_sa_doc_pos_affil ON source_authorships (source_document_id, author_position) WHERE in_perimeter = FALSE AND raw_affiliations IS NOT NULL;
CREATE INDEX idx_sa_excluded ON source_authorships (excluded) WHERE excluded = TRUE;

-- ══════════════════════════════════════════════════════════════════
-- 4. Supprimer les anciennes tables
-- ══════════════════════════════════════════════════════════════════

DROP TABLE hal_authorships CASCADE;
DROP TABLE openalex_authorships CASCADE;
DROP TABLE wos_authorships CASCADE;
DROP TABLE scanr_authorships CASCADE;

COMMIT;
