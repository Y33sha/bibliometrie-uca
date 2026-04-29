-- Migration 016 : refonte du schéma `subjects` pour la fusion par label.
--
-- Phase 5d du chantier sujets / mots-clés (cf docs/chantiers/sujets-mots-cles.md).
-- Constat : un même libellé apparaît jusqu'à 7 fois en base (ex "neurosciences"
-- présent en hal_domain, theses_discipline, wos_subject et libre). La distinction
-- `kind` (free/concept) + `(ontology, ontology_id)` créait des doublons UI.
-- Décision : un seul subject par label (insensible à la casse), avec un JSONB
-- `ontologies` qui agrège les annotations source par source.
--
-- Stratégie : on ne migre pas la donnée existante (publication_subjects vidée
-- + recalcul via la phase pipeline `subjects` qui repeuple depuis
-- `source_publications` qui est intacte). Tronque + repasse pipeline.

-- 1. Drop des contraintes / index liés à `kind` / `ontology` / `ontology_id`.
ALTER TABLE subjects DROP CONSTRAINT subjects_concept_has_ontology;
DROP INDEX subjects_concept_key;
DROP INDEX subjects_free_key;
DROP INDEX IF EXISTS subjects_label_lower_idx;

-- 2. Tronque la table AVANT de modifier le schéma. La phase pipeline
--    `subjects` repeuplera depuis `source_publications` (intacte).
--    CASCADE : vide aussi `publication_subjects` et `subject_cooccurrences`.
TRUNCATE subjects RESTART IDENTITY CASCADE;

-- 3. Refonte du schéma : on remplace les anciennes colonnes par `ontologies`.
ALTER TABLE subjects
    DROP COLUMN kind,
    DROP COLUMN ontology,
    DROP COLUMN ontology_id,
    ADD COLUMN ontologies JSONB NOT NULL DEFAULT '{}'::jsonb;

-- 4. Identité = lower(label). Plus de partial index, plus de discrimination
--    par kind : un libre est juste un sujet avec `ontologies = {}`.
CREATE UNIQUE INDEX subjects_label_key ON subjects (lower(label));
