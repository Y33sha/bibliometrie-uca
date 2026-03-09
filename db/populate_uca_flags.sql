-- =============================================================
-- Peuplement is_uca et structure_ids
-- =============================================================
-- À exécuter APRÈS migration_016.
-- Ces requêtes seront intégrées dans les scripts de traitement
-- (normalize_hal.py, resolve_addresses.py, etc.) pour être
-- reproductibles à chaque nouvelle extraction.
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
-- → structure_ids devrait couvrir une bonne partie des is_uca = TRUE


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
-- ÉTAPE 3 : OpenAlex — calculer is_uca via la chaîne d'adresses
-- #############################################################
-- Chemin : openalex_authorships
--        → openalex_authorship_addresses
--        → addresses
--        → address_structures
--        → structures dans le périmètre UCA

-- D'abord remettre à FALSE
UPDATE openalex_authorships SET is_uca = FALSE;

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

-- Optionnel : remplir aussi structure_ids pour OpenAlex
WITH uca_perimeter AS (
    SELECT s.id FROM structures s WHERE s.code = 'uca'
    UNION
    SELECT sr.child_id FROM structure_relations sr
    JOIN structures s ON s.id = sr.parent_id
    WHERE s.code = 'uca' AND sr.relation_type = 'est_tutelle_de'
),
oas_structs AS (
    SELECT oaa.openalex_authorship_id,
           array_agg(DISTINCT ast.structure_id) AS struct_ids
    FROM openalex_authorship_addresses oaa
    JOIN address_structures ast ON ast.address_id = oaa.address_id
    WHERE ast.structure_id IN (SELECT id FROM uca_perimeter)
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
-- ÉTAPE 4 : Propager vers authorships (table de vérité)
-- #############################################################
-- Le matching se fait par (publication_id, person_id).
-- Seuls les authorships avec person_id résolu sont traités.

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
hal_uca AS (
    SELECT hd.publication_id,
           ha.person_id,
           array_agg(DISTINCT sid) FILTER (
               WHERE sid IN (SELECT id FROM uca_perimeter)
           ) AS uca_struct_ids
    FROM hal_authorships has
    JOIN hal_documents hd ON hd.id = has.hal_document_id
    JOIN hal_authors ha ON ha.id = has.hal_author_id,
    LATERAL unnest(has.structure_ids) AS sid
    WHERE has.is_uca = TRUE
      AND has.structure_ids IS NOT NULL
      AND hd.publication_id IS NOT NULL
      AND ha.person_id IS NOT NULL
    GROUP BY hd.publication_id, ha.person_id
)
UPDATE authorships a
SET structure_ids = hu.uca_struct_ids,
    is_uca = TRUE,
    updated_at = now()
FROM hal_uca hu
WHERE a.publication_id = hu.publication_id
  AND a.person_id = hu.person_id
  AND a.person_id IS NOT NULL;

-- 4b. Depuis OpenAlex
-- Merge les structure_ids OpenAlex avec ceux déjà présents (HAL)
WITH oa_uca AS (
    SELECT od.publication_id,
           oa.person_id,
           oas.structure_ids AS uca_struct_ids
    FROM openalex_authorships oas
    JOIN openalex_documents od ON od.id = oas.openalex_document_id
    JOIN openalex_authors oa ON oa.id = oas.openalex_author_id
    WHERE oas.is_uca = TRUE
      AND oas.structure_ids IS NOT NULL
      AND od.publication_id IS NOT NULL
      AND oa.person_id IS NOT NULL
)
UPDATE authorships a
SET structure_ids = (
        SELECT array_agg(DISTINCT x)
        FROM unnest(COALESCE(a.structure_ids, '{}') || ou.uca_struct_ids) AS x
    ),
    is_uca = TRUE,
    updated_at = now()
FROM oa_uca ou
WHERE a.publication_id = ou.publication_id
  AND a.person_id = ou.person_id
  AND a.person_id IS NOT NULL;

-- Vérification finale :
-- SELECT COUNT(*) FROM authorships WHERE is_uca = TRUE;
-- SELECT COUNT(*) FROM authorships WHERE structure_ids IS NOT NULL;
