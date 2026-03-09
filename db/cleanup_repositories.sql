-- =============================================================
-- Nettoyage des repositories dans la table journals
--
-- Problème : des entrées OpenAlex comme SPIRE, Zenodo, arXiv,
-- etc. ont été insérées comme "journals" alors qu'ils sont des
-- repositories. Cela pollue les stats éditeurs/revues.
--
-- Ce script :
-- 1. Identifie les journals qui sont des repositories
-- 2. Détache les publications de ces journals (journal_id → NULL)
-- 3. Marque les repositories pour référence
-- =============================================================

BEGIN;

-- 1. Marquer tous les repositories (par oa_model existant + détection par nom)
UPDATE journals SET oa_model = 'repository'
WHERE oa_model IS DISTINCT FROM 'repository'
  AND (
    title_normalized ILIKE '%repository%'
    OR title_normalized ILIKE '%arxiv%'
    OR title_normalized ILIKE '%zenodo%'
    OR title_normalized ILIKE '%figshare%'
    OR title_normalized ILIKE '%dspace%'
    OR title_normalized ILIKE '%hal %'
    OR title_normalized ILIKE 'hal-%'
    OR title_normalized ILIKE '%preprint%server%'
    OR title_normalized ILIKE '%open archive%'
  );

-- Rapport : combien de repositories identifiés
DO $$
DECLARE
    repo_count INT;
    pub_count INT;
BEGIN
    SELECT COUNT(*) INTO repo_count FROM journals WHERE oa_model = 'repository';
    SELECT COUNT(*) INTO pub_count
    FROM publications WHERE journal_id IN (SELECT id FROM journals WHERE oa_model = 'repository');
    RAISE NOTICE 'Repositories identifiés : % journals, % publications concernées', repo_count, pub_count;
END $$;

-- 2. Détacher les publications des repositories
-- (le journal HAL correct sera rattaché par normalize_hal.py)
UPDATE publications
SET journal_id = NULL, updated_at = now()
WHERE journal_id IN (
    SELECT id FROM journals WHERE oa_model = 'repository'
);

-- 3. Rapport final
DO $$
DECLARE
    orphan_count INT;
BEGIN
    SELECT COUNT(*) INTO orphan_count
    FROM journals j
    WHERE j.oa_model = 'repository'
      AND NOT EXISTS (SELECT 1 FROM publications p WHERE p.journal_id = j.id);
    RAISE NOTICE 'Journals repository orphelins (plus aucune publication) : %', orphan_count;
END $$;

COMMIT;
