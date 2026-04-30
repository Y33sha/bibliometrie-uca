-- Migration 017 : retire les colonnes `level` et `parent_id` de `subjects`.
--
-- Phase 5d (suite) du chantier sujets / mots-clés (cf docs/chantiers/sujets-mots-cles.md).
-- Ces deux colonnes sont ontology-dépendantes : un même sujet fusionné par
-- plusieurs ontologies n'a pas un seul level / parent. On absorbe ces infos
-- dans le JSONB `ontologies` : `ontologies.<ontology>.{level, parent}`.
--
-- Comme pour 016, on tronque puis on relance la phase pipeline qui repeuple.

-- TRUNCATE avant DROP : `parent_id` self-référence empêcherait certains DROP.
TRUNCATE subjects RESTART IDENTITY CASCADE;

ALTER TABLE subjects
    DROP COLUMN level,
    DROP COLUMN parent_id;
