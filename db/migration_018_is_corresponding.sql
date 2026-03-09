-- =============================================================
-- Migration 018 : Ajout de is_corresponding aux authorships
-- =============================================================
--
-- Ajoute le champ is_corresponding (BOOLEAN) à la table authorships,
-- puis le peuple depuis les données brutes OpenAlex (staging_openalex).
--
-- Le matching se fait via :
--   staging_openalex.doi → publications.doi → authorships.publication_id
--   + author_position = index dans le tableau JSON authorships[]
-- =============================================================

BEGIN;

-- 1. Ajout de la colonne
ALTER TABLE authorships ADD COLUMN IF NOT EXISTS is_corresponding BOOLEAN;

-- 2. Peuplement depuis staging_openalex
UPDATE authorships a
SET is_corresponding = (
    oa_auth.value ->> 'is_corresponding'
)::boolean
FROM publications p
JOIN staging_openalex s ON LOWER(s.doi) = LOWER(p.doi)
CROSS JOIN LATERAL jsonb_array_elements(s.raw_data -> 'authorships')
    WITH ORDINALITY AS oa_auth(value, idx)
WHERE a.publication_id = p.id
  AND a.author_position = (oa_auth.idx - 1)::int;

-- 3. Index partiel pour les requêtes APC (auteur correspondant UCA)
CREATE INDEX IF NOT EXISTS idx_authorships_corresponding_uca
    ON authorships (publication_id)
    WHERE is_corresponding = TRUE AND is_uca = TRUE;

COMMIT;
