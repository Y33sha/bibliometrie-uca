-- Migration 010 : ajouter `source_authorships.identifiers` JSONB.
--
-- Colonne dédiée aux identifiants normalisés cross-source (orcid, idref,
-- idhal, hal_person_id, researcher_id…). Distincte de `source_data` qui
-- héberge des extras spécifiques par source (affiliations brutes ScanR/
-- CrossRef, sequence, detected_countries…).
--
-- Le backfill depuis `source_persons` n'est PAS fait ici (table de
-- plusieurs millions de lignes → script dédié avec batching et logs :
-- `interfaces/cli/backfill_source_authorships_identifiers.py`).
--
-- Cette colonne va remplacer la dépendance à `source_persons` pour les
-- sources sans identité auteur stable (cf. docs/chantiers/source-persons.md).

ALTER TABLE source_authorships
    ADD COLUMN identifiers jsonb;
