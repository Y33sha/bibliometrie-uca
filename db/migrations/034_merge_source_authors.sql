-- Migration : fusion des 4 tables *_authors en source_authors
-- + remapping des FK *_author_id dans les 4 tables *_authorships

BEGIN;

-- ══════════════════════════════════════════════════════════════════
-- 1. Créer la table unifiée source_authors
-- ══════════════════════════════════════════════════════════════════

CREATE TABLE source_authors (
    id              SERIAL PRIMARY KEY,
    source          TEXT NOT NULL,           -- 'hal', 'openalex', 'wos', 'scanr', 'theses', ...
    source_id       TEXT NOT NULL,           -- clé de dédup opaque par source
    full_name       TEXT NOT NULL,
    last_name       TEXT,
    first_name      TEXT,
    orcid           TEXT,
    idref           TEXT,
    person_id       INTEGER REFERENCES persons(id) ON DELETE SET NULL,
    source_ids      JSONB,                   -- identifiants source-spécifiques
    created_at      TIMESTAMPTZ DEFAULT now(),
    UNIQUE (source, source_id)
);

-- ══════════════════════════════════════════════════════════════════
-- 2. Supprimer les anciennes FK des authorships → authors
-- ══════════════════════════════════════════════════════════════════

ALTER TABLE hal_authorships DROP CONSTRAINT hal_authorships_hal_author_id_fkey;
ALTER TABLE openalex_authorships DROP CONSTRAINT openalex_authorships_openalex_author_id_fkey;
ALTER TABLE wos_authorships DROP CONSTRAINT wos_authorships_wos_author_id_fkey;
ALTER TABLE scanr_authorships DROP CONSTRAINT scanr_authorships_scanr_author_id_fkey;

-- ══════════════════════════════════════════════════════════════════
-- 3. Ajouter source_author_id aux authorships (temporairement nullable)
-- ══════════════════════════════════════════════════════════════════

ALTER TABLE hal_authorships ADD COLUMN source_author_id INTEGER;
ALTER TABLE openalex_authorships ADD COLUMN source_author_id INTEGER;
ALTER TABLE wos_authorships ADD COLUMN source_author_id INTEGER;
ALTER TABLE scanr_authorships ADD COLUMN source_author_id INTEGER;

-- ══════════════════════════════════════════════════════════════════
-- 4. Migrer les données et remapper les FK
-- ══════════════════════════════════════════════════════════════════

-- HAL : source_id = "{hal_person_id}_{hal_form_id}" (fallback "nokey-{id}" si aucun)
WITH inserted AS (
    INSERT INTO source_authors (source, source_id, full_name, last_name, first_name,
                                orcid, idref, person_id, source_ids, created_at)
    SELECT 'hal',
           CASE
               WHEN hal_person_id IS NOT NULL OR hal_form_id IS NOT NULL
               THEN COALESCE(hal_person_id::text, '') || '_' || COALESCE(hal_form_id::text, '')
               ELSE 'nokey-' || id::text
           END,
           full_name, last_name, first_name,
           orcid, idref, person_id,
           jsonb_strip_nulls(jsonb_build_object(
               'hal_person_id', hal_person_id,
               'idhal', idhal,
               'hal_form_id', hal_form_id
           )),
           created_at
    FROM hal_authors
    RETURNING id, source_id
)
UPDATE hal_authorships ha
SET source_author_id = ins.id
FROM inserted ins
JOIN hal_authors old ON (
    CASE
        WHEN old.hal_person_id IS NOT NULL OR old.hal_form_id IS NOT NULL
        THEN COALESCE(old.hal_person_id::text, '') || '_' || COALESCE(old.hal_form_id::text, '')
        ELSE 'nokey-' || old.id::text
    END
) = ins.source_id
WHERE ha.hal_author_id = old.id;

-- OpenAlex : source_id = openalex_id (fallback "nokey-{id}" si NULL)
WITH inserted AS (
    INSERT INTO source_authors (source, source_id, full_name, last_name, first_name,
                                orcid, person_id, created_at)
    SELECT 'openalex', COALESCE(openalex_id, 'nokey-' || id::text),
           full_name, last_name, first_name,
           orcid, NULL, created_at
    FROM openalex_authors
    RETURNING id, source_id
)
UPDATE openalex_authorships oa
SET source_author_id = ins.id
FROM inserted ins
JOIN openalex_authors old ON COALESCE(old.openalex_id, 'nokey-' || old.id::text) = ins.source_id
WHERE oa.openalex_author_id = old.id;

-- WoS : source_id = daisng_id (peut être NULL → fallback sur id)
WITH inserted AS (
    INSERT INTO source_authors (source, source_id, full_name, last_name, first_name,
                                orcid, source_ids, created_at)
    SELECT 'wos',
           COALESCE(daisng_id, 'wos-' || id::text),
           full_name, last_name, first_name,
           orcid,
           jsonb_strip_nulls(jsonb_build_object(
               'daisng_id', daisng_id,
               'researcher_id', researcher_id
           )),
           created_at
    FROM wos_authors
    RETURNING id, source_id
)
UPDATE wos_authorships wa
SET source_author_id = ins.id
FROM inserted ins
JOIN wos_authors old ON COALESCE(old.daisng_id, 'wos-' || old.id::text) = ins.source_id
WHERE wa.wos_author_id = old.id;

-- ScanR : source_id = idref (ou 'scanr-' || id si pas d'idref)
WITH inserted AS (
    INSERT INTO source_authors (source, source_id, full_name, last_name, first_name,
                                orcid, idref, person_id, created_at)
    SELECT 'scanr',
           COALESCE(idref, 'scanr-' || id::text),
           full_name, last_name, first_name,
           orcid, idref, person_id, created_at
    FROM scanr_authors
    RETURNING id, source_id
)
UPDATE scanr_authorships sa
SET source_author_id = ins.id
FROM inserted ins
JOIN scanr_authors old ON COALESCE(old.idref, 'scanr-' || old.id::text) = ins.source_id
WHERE sa.scanr_author_id = old.id;

-- ══════════════════════════════════════════════════════════════════
-- 5. Contraintes sur source_author_id
-- ══════════════════════════════════════════════════════════════════

ALTER TABLE hal_authorships ALTER COLUMN source_author_id SET NOT NULL;
ALTER TABLE openalex_authorships ALTER COLUMN source_author_id SET NOT NULL;
ALTER TABLE wos_authorships ALTER COLUMN source_author_id SET NOT NULL;
ALTER TABLE scanr_authorships ALTER COLUMN source_author_id SET NOT NULL;

ALTER TABLE hal_authorships
    ADD CONSTRAINT hal_authorships_source_author_id_fkey
    FOREIGN KEY (source_author_id) REFERENCES source_authors(id) ON DELETE CASCADE;
ALTER TABLE openalex_authorships
    ADD CONSTRAINT openalex_authorships_source_author_id_fkey
    FOREIGN KEY (source_author_id) REFERENCES source_authors(id) ON DELETE CASCADE;
ALTER TABLE wos_authorships
    ADD CONSTRAINT wos_authorships_source_author_id_fkey
    FOREIGN KEY (source_author_id) REFERENCES source_authors(id) ON DELETE CASCADE;
ALTER TABLE scanr_authorships
    ADD CONSTRAINT scanr_authorships_source_author_id_fkey
    FOREIGN KEY (source_author_id) REFERENCES source_authors(id) ON DELETE CASCADE;

-- ══════════════════════════════════════════════════════════════════
-- 6. Supprimer les anciennes colonnes et recréer les UNIQUE
-- ══════════════════════════════════════════════════════════════════

-- Supprimer anciennes colonnes *_author_id (supprime aussi les UNIQUE et index associés)
ALTER TABLE hal_authorships DROP COLUMN hal_author_id;
ALTER TABLE openalex_authorships DROP COLUMN openalex_author_id;
ALTER TABLE wos_authorships DROP COLUMN wos_author_id;
ALTER TABLE scanr_authorships DROP COLUMN scanr_author_id;

-- Recréer UNIQUE (source_document_id, source_author_id)
ALTER TABLE hal_authorships
    ADD CONSTRAINT hal_authorships_doc_author_key UNIQUE (source_document_id, source_author_id);
ALTER TABLE openalex_authorships
    ADD CONSTRAINT openalex_authorships_doc_author_key UNIQUE (source_document_id, source_author_id);
ALTER TABLE wos_authorships
    ADD CONSTRAINT wos_authorships_doc_author_key UNIQUE (source_document_id, source_author_id);
ALTER TABLE scanr_authorships
    ADD CONSTRAINT scanr_authorships_doc_author_key UNIQUE (source_document_id, source_author_id);

-- ══════════════════════════════════════════════════════════════════
-- 7. Index
-- ══════════════════════════════════════════════════════════════════

CREATE INDEX idx_source_authors_source ON source_authors (source);
CREATE INDEX idx_source_authors_person ON source_authors (person_id) WHERE person_id IS NOT NULL;
CREATE INDEX idx_source_authors_orcid ON source_authors (orcid) WHERE orcid IS NOT NULL;
CREATE INDEX idx_source_authors_idref ON source_authors (idref) WHERE idref IS NOT NULL;

CREATE INDEX idx_hal_as_source_author ON hal_authorships (source_author_id);
CREATE INDEX idx_oa_as_source_author ON openalex_authorships (source_author_id);
CREATE INDEX idx_wos_as_source_author ON wos_authorships (source_author_id);
CREATE INDEX idx_scanr_as_source_author ON scanr_authorships (source_author_id);

-- ══════════════════════════════════════════════════════════════════
-- 8. Supprimer les anciennes tables
-- ══════════════════════════════════════════════════════════════════

DROP TABLE hal_authors CASCADE;
DROP TABLE openalex_authors CASCADE;
DROP TABLE wos_authors CASCADE;
DROP TABLE scanr_authors CASCADE;

COMMIT;
