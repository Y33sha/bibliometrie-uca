-- =============================================================
-- Peuplement in_perimeter et structure_ids
-- =============================================================
-- À exécuter APRÈS migration_016.
--
-- Deux périmètres :
--   • uca_perimeter (restreint) : UCA + labos tutellés → sert pour in_perimeter
--   • uca_perimeter_wide (large) : restreint + partenaires (CHU, INP…)
--     → sert pour structure_ids
--
-- in_perimeter = TRUE  ↔  au moins une structure du périmètre restreint détectée
-- structure_ids   ↔  toutes les structures du périmètre large détectées
-- =============================================================

DO $$
DECLARE
    cnt INTEGER;
BEGIN

-- #############################################################
-- ÉTAPE 1 : HAL — mapper hal_struct_ids → structure_ids (réels)
-- #############################################################

UPDATE hal_authorships has
SET structure_ids = mapped.struct_ids
FROM (
    SELECT has2.id,
           array_agg(DISTINCT hs.structure_id) AS struct_ids
    FROM hal_authorships has2,
         LATERAL unnest(has2.hal_struct_ids) AS hsid(val)
    JOIN hal_structures hs ON hs.hal_struct_id = hsid.val
    WHERE hs.structure_id IS NOT NULL
    GROUP BY has2.id
) mapped
WHERE has.id = mapped.id;
GET DIAGNOSTICS cnt = ROW_COUNT;
RAISE NOTICE 'Étape 1 — HAL structure_ids mappés : % authorships', cnt;


-- #############################################################
-- ÉTAPE 2 : HAL — recalculer in_perimeter à partir du périmètre UCA
-- #############################################################

UPDATE hal_authorships SET in_perimeter = FALSE;
GET DIAGNOSTICS cnt = ROW_COUNT;
RAISE NOTICE 'Étape 2 — HAL in_perimeter reset : % authorships', cnt;

WITH uca_perimeter AS (
    SELECT s.id FROM structures s WHERE s.code = 'uca'
    UNION
    SELECT sr.child_id FROM structure_relations sr
    JOIN structures s ON s.id = sr.parent_id
    WHERE s.code = 'uca' AND sr.relation_type = 'est_tutelle_de'
)
UPDATE hal_authorships has
SET in_perimeter = TRUE
WHERE has.structure_ids IS NOT NULL
  AND EXISTS (
    SELECT 1
    FROM unnest(has.structure_ids) AS sid
    WHERE sid IN (SELECT id FROM uca_perimeter)
  );
GET DIAGNOSTICS cnt = ROW_COUNT;
RAISE NOTICE 'Étape 2 — HAL in_perimeter = TRUE : % authorships', cnt;


-- #############################################################
-- ÉTAPE 3 : OpenAlex — calculer in_perimeter + structure_ids
-- #############################################################

UPDATE openalex_authorships SET in_perimeter = FALSE, structure_ids = NULL;
GET DIAGNOSTICS cnt = ROW_COUNT;
RAISE NOTICE 'Étape 3 — OA reset : % authorships', cnt;

-- in_perimeter via périmètre restreint
WITH uca_perimeter AS (
    SELECT s.id FROM structures s WHERE s.code = 'uca'
    UNION
    SELECT sr.child_id FROM structure_relations sr
    JOIN structures s ON s.id = sr.parent_id
    WHERE s.code = 'uca' AND sr.relation_type = 'est_tutelle_de'
)
UPDATE openalex_authorships oas
SET in_perimeter = TRUE
WHERE EXISTS (
    SELECT 1
    FROM openalex_authorship_addresses oaa
    JOIN address_structures ast ON ast.address_id = oaa.address_id
    WHERE oaa.openalex_authorship_id = oas.id
      AND ast.structure_id IN (SELECT id FROM uca_perimeter)
);
GET DIAGNOSTICS cnt = ROW_COUNT;
RAISE NOTICE 'Étape 3 — OA in_perimeter = TRUE : % authorships', cnt;

-- structure_ids via périmètre large (restreint + partenaires)
WITH uca_perimeter AS (
    SELECT s.id FROM structures s WHERE s.code = 'uca'
    UNION
    SELECT sr.child_id FROM structure_relations sr
    JOIN structures s ON s.id = sr.parent_id
    WHERE s.code = 'uca' AND sr.relation_type = 'est_tutelle_de'
),
uca_perimeter_wide AS (
    SELECT id FROM uca_perimeter
    UNION
    SELECT sr.parent_id FROM structure_relations sr
    JOIN structures s ON s.id = sr.child_id
    WHERE s.code = 'uca' AND sr.relation_type = 'est_partenaire_de'
),
oas_structs AS (
    SELECT oaa.openalex_authorship_id,
           array_agg(DISTINCT ast.structure_id) AS struct_ids
    FROM openalex_authorship_addresses oaa
    JOIN address_structures ast ON ast.address_id = oaa.address_id
    WHERE ast.structure_id IN (SELECT id FROM uca_perimeter_wide)
    GROUP BY oaa.openalex_authorship_id
)
UPDATE openalex_authorships oas
SET structure_ids = os.struct_ids
FROM oas_structs os
WHERE oas.id = os.openalex_authorship_id;
GET DIAGNOSTICS cnt = ROW_COUNT;
RAISE NOTICE 'Étape 3 — OA structure_ids : % authorships', cnt;


-- #############################################################
-- ÉTAPE 3b : WoS — calculer in_perimeter + structure_ids
-- #############################################################

UPDATE wos_authorships SET in_perimeter = FALSE, structure_ids = NULL;
GET DIAGNOSTICS cnt = ROW_COUNT;
RAISE NOTICE 'Étape 3b — WoS reset : % authorships', cnt;

-- in_perimeter via périmètre restreint
WITH uca_perimeter AS (
    SELECT s.id FROM structures s WHERE s.code = 'uca'
    UNION
    SELECT sr.child_id FROM structure_relations sr
    JOIN structures s ON s.id = sr.parent_id
    WHERE s.code = 'uca' AND sr.relation_type = 'est_tutelle_de'
)
UPDATE wos_authorships was
SET in_perimeter = TRUE
WHERE EXISTS (
    SELECT 1
    FROM wos_authorship_addresses waa
    JOIN address_structures ast ON ast.address_id = waa.address_id
    WHERE waa.wos_authorship_id = was.id
      AND ast.structure_id IN (SELECT id FROM uca_perimeter)
);
GET DIAGNOSTICS cnt = ROW_COUNT;
RAISE NOTICE 'Étape 3b — WoS in_perimeter = TRUE : % authorships', cnt;

-- structure_ids via périmètre large
WITH uca_perimeter AS (
    SELECT s.id FROM structures s WHERE s.code = 'uca'
    UNION
    SELECT sr.child_id FROM structure_relations sr
    JOIN structures s ON s.id = sr.parent_id
    WHERE s.code = 'uca' AND sr.relation_type = 'est_tutelle_de'
),
uca_perimeter_wide AS (
    SELECT id FROM uca_perimeter
    UNION
    SELECT sr.parent_id FROM structure_relations sr
    JOIN structures s ON s.id = sr.child_id
    WHERE s.code = 'uca' AND sr.relation_type = 'est_partenaire_de'
),
was_structs AS (
    SELECT waa.wos_authorship_id,
           array_agg(DISTINCT ast.structure_id) AS struct_ids
    FROM wos_authorship_addresses waa
    JOIN address_structures ast ON ast.address_id = waa.address_id
    WHERE ast.structure_id IN (SELECT id FROM uca_perimeter_wide)
    GROUP BY waa.wos_authorship_id
)
UPDATE wos_authorships was
SET structure_ids = ws.struct_ids
FROM was_structs ws
WHERE was.id = ws.wos_authorship_id;
GET DIAGNOSTICS cnt = ROW_COUNT;
RAISE NOTICE 'Étape 3b — WoS structure_ids : % authorships', cnt;

END $$;
