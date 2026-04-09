-- Migration : fusion de hal_structures, openalex_institutions, wos_organizations
-- en une seule table source_structures

BEGIN;

-- ══════════════════════════════════════════════════════════════════
-- 1. Créer la table unifiée
-- ══════════════════════════════════════════════════════════════════

CREATE TABLE source_structures (
    id              SERIAL PRIMARY KEY,
    source          TEXT NOT NULL,           -- 'hal', 'openalex', 'wos', ...
    source_id       TEXT NOT NULL,           -- hal_struct_id / openalex_id / name (WoS)
    name            TEXT NOT NULL,
    acronym         TEXT,
    country         TEXT,
    ror_id          TEXT,
    structure_id    INTEGER REFERENCES structures(id) ON DELETE SET NULL,
    enriched_at     TIMESTAMPTZ,            -- date d'enrichissement (HAL)
    source_data     JSONB,                  -- données source-spécifiques
    created_at      TIMESTAMPTZ DEFAULT now(),
    UNIQUE (source, source_id)
);

-- ══════════════════════════════════════════════════════════════════
-- 2. Migrer les données
-- ══════════════════════════════════════════════════════════════════

-- HAL
INSERT INTO source_structures (source, source_id, name, acronym, country, structure_id,
                               enriched_at, source_data, created_at)
SELECT 'hal', hal_struct_id::text, name,
       acronym, country, structure_id, enriched_at,
       jsonb_strip_nulls(jsonb_build_object(
           'type', type,
           'valid', valid,
           'code', code,
           'doc_count', doc_count,
           'parent_ids', CASE WHEN parent_ids IS NOT NULL THEN to_jsonb(parent_ids) END,
           'start_date', start_date,
           'end_date', end_date
       )),
       created_at
FROM hal_structures;

-- OpenAlex
INSERT INTO source_structures (source, source_id, name, country, ror_id, structure_id,
                               source_data, created_at)
SELECT 'openalex', openalex_id, name,
       country_code, ror_id, structure_id,
       jsonb_strip_nulls(jsonb_build_object(
           'type', type
       )),
       created_at
FROM openalex_institutions;

-- WoS
INSERT INTO source_structures (source, source_id, name, country, ror_id, created_at)
SELECT 'wos', name, name,
       country, ror_id, created_at
FROM wos_organizations;

-- ══════════════════════════════════════════════════════════════════
-- 3. Remapper les FK dans les authorships
-- ══════════════════════════════════════════════════════════════════

-- hal_authorships.hal_struct_ids (integer[]) → référence hal_structures.hal_struct_id
-- Ces IDs doivent maintenant pointer vers source_structures.id
-- On ajoute une colonne source_struct_ids (integer[]) et on remplit

ALTER TABLE hal_authorships ADD COLUMN source_struct_ids INTEGER[];

UPDATE hal_authorships ha
SET source_struct_ids = (
    SELECT array_agg(ss.id ORDER BY ss.id)
    FROM unnest(ha.hal_struct_ids) AS hsid(val)
    JOIN source_structures ss ON ss.source = 'hal' AND ss.source_id = hsid.val::text
)
WHERE ha.hal_struct_ids IS NOT NULL;

ALTER TABLE hal_authorships DROP COLUMN hal_struct_ids;

-- openalex_authorships.openalex_institution_ids (text[]) → référence openalex_institutions.openalex_id
-- Remap vers source_structures.id

ALTER TABLE openalex_authorships ADD COLUMN source_struct_ids INTEGER[];

UPDATE openalex_authorships oa
SET source_struct_ids = (
    SELECT array_agg(ss.id ORDER BY ss.id)
    FROM unnest(oa.openalex_institution_ids) AS oaid(val)
    JOIN source_structures ss ON ss.source = 'openalex' AND ss.source_id = oaid.val
)
WHERE oa.openalex_institution_ids IS NOT NULL;

ALTER TABLE openalex_authorships DROP COLUMN openalex_institution_ids;

-- wos_authorships.wos_institution_ids (integer[]) → référence wos_organizations.id
-- Remap vers source_structures.id

ALTER TABLE wos_authorships ADD COLUMN source_struct_ids INTEGER[];

UPDATE wos_authorships wa
SET source_struct_ids = (
    SELECT array_agg(ss.id ORDER BY ss.id)
    FROM unnest(wa.wos_institution_ids) AS woid(val)
    JOIN wos_organizations wo ON wo.id = woid.val
    JOIN source_structures ss ON ss.source = 'wos' AND ss.source_id = wo.name
)
WHERE wa.wos_institution_ids IS NOT NULL;

ALTER TABLE wos_authorships DROP COLUMN wos_institution_ids;

-- ══════════════════════════════════════════════════════════════════
-- 4. Index
-- ══════════════════════════════════════════════════════════════════

CREATE INDEX idx_source_structs_source ON source_structures (source);
CREATE INDEX idx_source_structs_structure ON source_structures (structure_id) WHERE structure_id IS NOT NULL;
CREATE INDEX idx_source_structs_ror ON source_structures (ror_id) WHERE ror_id IS NOT NULL;
CREATE INDEX idx_source_structs_enriched ON source_structures (enriched_at) WHERE enriched_at IS NULL;
CREATE INDEX idx_source_structs_name ON source_structures USING gin (name gin_trgm_ops);

-- ══════════════════════════════════════════════════════════════════
-- 5. Supprimer les anciennes tables
-- ══════════════════════════════════════════════════════════════════

DROP TABLE hal_structures CASCADE;
DROP TABLE openalex_institutions CASCADE;
DROP TABLE wos_organizations CASCADE;

COMMIT;
