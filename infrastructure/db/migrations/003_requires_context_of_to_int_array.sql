-- Migration 003 : convertir requires_context_of de JSONB en integer[]
-- Remplace la string "tutelles" par les IDs réels des tutelles.

-- 1. Backfill : remplacer "tutelles" par les IDs des parents (est_tutelle_de)
UPDATE structure_name_forms snf
SET requires_context_of = (
    SELECT jsonb_agg(DISTINCT val)
    FROM (
        SELECT val FROM jsonb_array_elements(snf.requires_context_of) AS val
        WHERE jsonb_typeof(val) = 'number'
        UNION
        SELECT to_jsonb(sr.parent_id)
        FROM structure_relations sr
        WHERE sr.child_id = snf.structure_id
          AND sr.relation_type = 'est_tutelle_de'
          AND EXISTS (SELECT 1 FROM jsonb_array_elements_text(snf.requires_context_of) e WHERE e = 'tutelles')
    ) sub
)
WHERE requires_context_of::text LIKE '%tutelles%';

-- 2. Ajouter la nouvelle colonne integer[]
ALTER TABLE structure_name_forms ADD COLUMN context_structure_ids integer[];

-- 3. Copier les valeurs converties
UPDATE structure_name_forms
SET context_structure_ids = (
    SELECT array_agg(val::int)
    FROM jsonb_array_elements_text(requires_context_of) AS val
)
WHERE requires_context_of IS NOT NULL;

-- 4. Supprimer l'ancienne colonne et renommer
ALTER TABLE structure_name_forms DROP COLUMN requires_context_of;
ALTER TABLE structure_name_forms RENAME COLUMN context_structure_ids TO requires_context_of;
