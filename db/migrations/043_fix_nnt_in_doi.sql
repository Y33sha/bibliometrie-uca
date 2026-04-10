-- Migration 043 : NNT comme identifiant de premier ordre
--
-- Le NNT (Numéro National de Thèse) ne doit pas être stocké dans publications.doi.
-- Il est stocké dans source_documents.external_ids sous la clé "nnt".
--
-- Cette migration :
-- 1. Peuple external_ids.nnt sur les source_documents theses.fr
-- 2. Peuple external_ids.nnt sur les source_documents ScanR (source_id format nnt...)
-- 3. Peuple external_ids.nnt sur les source_documents OA (primary_location.id format pmh:...)
-- 4. Nettoie publications.doi quand c'est un NNT (pas un vrai DOI)

-- Step 1 : theses.fr → external_ids.nnt depuis staging.raw_data->>'nnt'
UPDATE source_documents sd
SET external_ids = COALESCE(sd.external_ids, '{}') || jsonb_build_object('nnt', upper(s.raw_data->>'nnt'))
FROM staging s
WHERE sd.staging_id = s.id
  AND sd.source = 'theses'
  AND s.raw_data->>'nnt' IS NOT NULL
  AND (sd.external_ids->>'nnt') IS NULL;

-- Step 2 : ScanR → external_ids.nnt depuis source_id (format nnt{NNT})
UPDATE source_documents
SET external_ids = COALESCE(external_ids, '{}') || jsonb_build_object('nnt', upper(substring(source_id FROM 4)))
WHERE source = 'scanr'
  AND source_id LIKE 'nnt%'
  AND (external_ids->>'nnt') IS NULL;

-- Step 3 : OpenAlex → external_ids.nnt depuis staging primary_location.id (format pmh:{NNT})
UPDATE source_documents sd
SET external_ids = COALESCE(sd.external_ids, '{}') ||
    jsonb_build_object('nnt', upper(replace(s.raw_data->'primary_location'->>'id', 'pmh:', '')))
FROM staging s
WHERE sd.staging_id = s.id
  AND sd.source = 'openalex'
  AND s.raw_data->'primary_location'->'source'->>'display_name' LIKE '%theses.fr%'
  AND s.raw_data->'primary_location'->>'id' LIKE 'pmh:%'
  AND (sd.external_ids->>'nnt') IS NULL;

-- Step 4 : Nettoyer publications.doi quand c'est un NNT
-- Un vrai DOI commence par '10.' ; un NNT ne commence jamais par '10.'
-- On ne touche que les publications liées à une source theses.fr (sécurité)
UPDATE publications p
SET doi = NULL, updated_at = now()
WHERE p.doi IS NOT NULL
  AND p.doi !~ '^10\.'
  AND EXISTS (
      SELECT 1 FROM source_documents sd
      WHERE sd.publication_id = p.id AND sd.source = 'theses'
  );
