-- =============================================================
-- Migration 016 : authorships.structure_id → structure_ids[]
-- =============================================================
--
-- Problème : la table authorships n'a qu'un seul structure_id,
-- or un auteur peut être affilié à plusieurs structures UCA sur
-- une même publication (ex : un labo + une école doctorale).
--
-- Changements :
--   1. Remplacer structure_id (INT FK) par structure_ids (INT[])
--   2. Contrainte unique sur (publication_id, person_id) au lieu
--      de (publication_id, person_id, structure_id)
--   3. Index GIN sur structure_ids
--
-- Pré-requis : migration 014a/014b terminées, table authorships existante.
-- =============================================================

BEGIN;

-- 1. Supprimer la contrainte unique qui inclut structure_id
ALTER TABLE authorships
    DROP CONSTRAINT IF EXISTS authorships_publication_id_person_id_structure_id_key;

-- 2. Supprimer l'index sur l'ancien champ scalaire
DROP INDEX IF EXISTS idx_authorships_struct;

-- 3. Ajouter la colonne array (avant dédup, pour y stocker les valeurs fusionnées)
ALTER TABLE authorships ADD COLUMN structure_ids INT[];

-- 4. Fusionner les doublons (publication_id, person_id) :
--    on garde la ligne avec le plus petit id, on agrège les structure_id
--    et on fusionne les flags source_*
WITH dupes AS (
    SELECT publication_id, person_id,
           min(id) AS keep_id,
           array_agg(DISTINCT structure_id) FILTER (WHERE structure_id IS NOT NULL) AS merged_struct_ids,
           bool_or(source_hal) AS any_hal,
           bool_or(source_openalex) AS any_openalex,
           bool_or(source_wos) AS any_wos,
           bool_or(source_manual) AS any_manual,
           bool_or(is_uca) AS any_uca
    FROM authorships
    WHERE person_id IS NOT NULL
    GROUP BY publication_id, person_id
    HAVING count(*) > 1
)
UPDATE authorships a
SET structure_ids = d.merged_struct_ids,
    source_hal = d.any_hal,
    source_openalex = d.any_openalex,
    source_wos = d.any_wos,
    source_manual = d.any_manual,
    is_uca = d.any_uca
FROM dupes d
WHERE a.id = d.keep_id;

-- Supprimer les lignes dupliquées (garder seulement keep_id)
DELETE FROM authorships a
USING (
    SELECT id, publication_id, person_id,
           row_number() OVER (PARTITION BY publication_id, person_id ORDER BY id) AS rn
    FROM authorships
    WHERE person_id IS NOT NULL
) ranked
WHERE a.id = ranked.id AND ranked.rn > 1;

-- 5. Supprimer la colonne scalaire
ALTER TABLE authorships DROP COLUMN structure_id;

-- 6. Nouvelle contrainte unique
ALTER TABLE authorships
    ADD CONSTRAINT authorships_publication_person_uq
    UNIQUE (publication_id, person_id);

-- 7. Index GIN pour les requêtes ANY(structure_ids)
CREATE INDEX idx_authorships_structs
    ON authorships USING GIN (structure_ids)
    WHERE structure_ids IS NOT NULL;

COMMIT;
