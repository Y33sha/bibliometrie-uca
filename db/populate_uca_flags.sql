-- =============================================================
-- Peuplement is_uca et structure_ids
-- =============================================================
-- À exécuter APRÈS migration_016.
--
-- Deux périmètres :
--   • uca_perimeter (restreint) : UCA + labos tutellés → sert pour is_uca
--   • uca_perimeter_wide (large) : restreint + partenaires (CHU, INP…)
--     → sert pour structure_ids
--
-- is_uca = TRUE  ↔  au moins une structure du périmètre restreint détectée
-- structure_ids   ↔  toutes les structures du périmètre large détectées
-- =============================================================


-- #############################################################
-- ÉTAPE 1 : HAL — mapper hal_struct_ids → structure_ids (réels)
-- #############################################################
-- hal_authorships.hal_struct_ids contient des identifiants HAL.
-- On les traduit en structures.id via hal_structures.structure_id.
-- Seules les hal_structures ayant un mapping sont conservées.

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

-- Vérification :
-- SELECT COUNT(*) FROM hal_authorships WHERE structure_ids IS NOT NULL;
-- SELECT COUNT(*) FROM hal_authorships WHERE is_uca = TRUE;


-- #############################################################
-- ÉTAPE 2 : HAL — recalculer is_uca à partir du périmètre UCA
-- #############################################################
-- is_uca est actuellement rempli par le script normalize_hal.
-- On le recalcule ici pour être sûr qu'il est cohérent avec
-- le périmètre UCA défini dans structures/structure_relations.
--
-- NB : on ne RESET PAS is_uca à FALSE d'abord, car certains
-- authorships sont UCA via des hal_structures non encore mappées
-- (structure_id NULL). On ne fait qu'AJOUTER le flag.

WITH uca_perimeter AS (
    SELECT s.id FROM structures s WHERE s.code = 'uca'
    UNION
    SELECT sr.child_id FROM structure_relations sr
    JOIN structures s ON s.id = sr.parent_id
    WHERE s.code = 'uca' AND sr.relation_type = 'est_tutelle_de'
)
UPDATE hal_authorships has
SET is_uca = TRUE
WHERE has.structure_ids IS NOT NULL
  AND EXISTS (
    SELECT 1
    FROM unnest(has.structure_ids) AS sid
    WHERE sid IN (SELECT id FROM uca_perimeter)
  );

-- Vérification :
-- SELECT COUNT(*) FROM hal_authorships WHERE is_uca = TRUE;


-- #############################################################
-- ÉTAPE 3 : OpenAlex — calculer is_uca + structure_ids
-- #############################################################
-- Chemin : openalex_authorships
--        → openalex_authorship_addresses
--        → addresses
--        → address_structures
--        → structures dans le périmètre

-- D'abord remettre à zéro
UPDATE openalex_authorships SET is_uca = FALSE, structure_ids = NULL;

-- is_uca via périmètre restreint
WITH uca_perimeter AS (
    SELECT s.id FROM structures s WHERE s.code = 'uca'
    UNION
    SELECT sr.child_id FROM structure_relations sr
    JOIN structures s ON s.id = sr.parent_id
    WHERE s.code = 'uca' AND sr.relation_type = 'est_tutelle_de'
)
UPDATE openalex_authorships oas
SET is_uca = TRUE
WHERE EXISTS (
    SELECT 1
    FROM openalex_authorship_addresses oaa
    JOIN address_structures ast ON ast.address_id = oaa.address_id
    WHERE oaa.openalex_authorship_id = oas.id
      AND ast.structure_id IN (SELECT id FROM uca_perimeter)
);

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

-- Vérification :
-- SELECT COUNT(*) FROM openalex_authorships WHERE is_uca = TRUE;
-- SELECT COUNT(*) FROM openalex_authorships WHERE structure_ids IS NOT NULL;


-- #############################################################
-- ÉTAPE 3b : WoS — calculer is_uca + structure_ids
-- #############################################################
-- Chemin : wos_authorships
--        → wos_authorship_addresses
--        → addresses
--        → address_structures
--        → structures dans le périmètre

-- D'abord remettre à zéro
UPDATE wos_authorships SET is_uca = FALSE, structure_ids = NULL;

-- is_uca via périmètre restreint
WITH uca_perimeter AS (
    SELECT s.id FROM structures s WHERE s.code = 'uca'
    UNION
    SELECT sr.child_id FROM structure_relations sr
    JOIN structures s ON s.id = sr.parent_id
    WHERE s.code = 'uca' AND sr.relation_type = 'est_tutelle_de'
)
UPDATE wos_authorships was
SET is_uca = TRUE
WHERE EXISTS (
    SELECT 1
    FROM wos_authorship_addresses waa
    JOIN address_structures ast ON ast.address_id = waa.address_id
    WHERE waa.wos_authorship_id = was.id
      AND ast.structure_id IN (SELECT id FROM uca_perimeter)
);

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

-- Vérification :
-- SELECT COUNT(*) FROM wos_authorships WHERE is_uca = TRUE;
-- SELECT COUNT(*) FROM wos_authorships WHERE structure_ids IS NOT NULL;


-- #############################################################
-- ÉTAPE 4 : Propager vers authorships (table de vérité)
-- #############################################################
-- Le matching se fait par (publication_id, person_id).
-- Seuls les authorships avec person_id résolu sont traités.
--
-- structure_ids = périmètre large (toutes structures pertinentes)
-- is_uca = TRUE si au moins une structure du périmètre restreint

-- D'abord reset
UPDATE authorships SET is_uca = FALSE, structure_ids = NULL;

-- 4a. Depuis HAL
WITH uca_perimeter AS (
    SELECT s.id FROM structures s WHERE s.code = 'uca'
    UNION
    SELECT sr.child_id FROM structure_relations sr
    JOIN structures s ON s.id = sr.parent_id
    WHERE s.code = 'uca' AND sr.relation_type = 'est_tutelle_de'
),
hal_data AS (
    SELECT hd.publication_id,
           has.person_id,
           array_agg(DISTINCT sid) AS all_struct_ids,
           bool_or(sid IN (SELECT id FROM uca_perimeter)) AS has_uca
    FROM hal_authorships has
    JOIN hal_documents hd ON hd.id = has.hal_document_id,
    LATERAL unnest(has.structure_ids) AS sid
    WHERE has.structure_ids IS NOT NULL
      AND hd.publication_id IS NOT NULL
      AND has.person_id IS NOT NULL
    GROUP BY hd.publication_id, has.person_id
)
UPDATE authorships a
SET structure_ids = hd.all_struct_ids,
    is_uca = hd.has_uca,
    updated_at = now()
FROM hal_data hd
WHERE a.publication_id = hd.publication_id
  AND a.person_id = hd.person_id
  AND a.person_id IS NOT NULL;

-- 4b. Depuis OpenAlex
-- Merge les structure_ids OpenAlex avec ceux déjà présents (HAL)
WITH uca_perimeter AS (
    SELECT s.id FROM structures s WHERE s.code = 'uca'
    UNION
    SELECT sr.child_id FROM structure_relations sr
    JOIN structures s ON s.id = sr.parent_id
    WHERE s.code = 'uca' AND sr.relation_type = 'est_tutelle_de'
),
oa_data AS (
    SELECT od.publication_id,
           oas.person_id,
           oas.structure_ids AS struct_ids,
           oas.is_uca AS src_is_uca
    FROM openalex_authorships oas
    JOIN openalex_documents od ON od.id = oas.openalex_document_id
    WHERE oas.structure_ids IS NOT NULL
      AND od.publication_id IS NOT NULL
      AND oas.person_id IS NOT NULL
)
UPDATE authorships a
SET structure_ids = (
        SELECT array_agg(DISTINCT x)
        FROM unnest(COALESCE(a.structure_ids, '{}') || od.struct_ids) AS x
    ),
    is_uca = a.is_uca OR od.src_is_uca,
    updated_at = now()
FROM oa_data od
WHERE a.publication_id = od.publication_id
  AND a.person_id = od.person_id
  AND a.person_id IS NOT NULL;

-- 4c. Depuis WoS
-- Merge les structure_ids WoS avec ceux déjà présents (HAL + OpenAlex)
WITH wos_data AS (
    SELECT wd.publication_id,
           was.person_id,
           was.structure_ids AS struct_ids,
           was.is_uca AS src_is_uca
    FROM wos_authorships was
    JOIN wos_documents wd ON wd.id = was.wos_document_id
    WHERE was.structure_ids IS NOT NULL
      AND wd.publication_id IS NOT NULL
      AND was.person_id IS NOT NULL
)
UPDATE authorships a
SET structure_ids = (
        SELECT array_agg(DISTINCT x)
        FROM unnest(COALESCE(a.structure_ids, '{}') || wd.struct_ids) AS x
    ),
    is_uca = a.is_uca OR wd.src_is_uca,
    updated_at = now()
FROM wos_data wd
WHERE a.publication_id = wd.publication_id
  AND a.person_id = wd.person_id
  AND a.person_id IS NOT NULL;

-- Vérification finale :
-- SELECT COUNT(*) FROM authorships WHERE is_uca = TRUE;
-- SELECT COUNT(*) FROM authorships WHERE structure_ids IS NOT NULL;
