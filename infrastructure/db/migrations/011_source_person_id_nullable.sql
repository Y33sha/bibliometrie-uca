-- Migration 011 : rendre `source_authorships.source_person_id` nullable.
--
-- Prérequis du chantier source_persons (cf. docs/chantiers/source-persons.md) :
-- les normalizers des sources sans identité auteur stable (OpenAlex, WoS,
-- CrossRef, et HAL/ScanR/theses sans hal_person_id/idref/PPN) vont cesser
-- d'écrire dans `source_persons`. Pour pouvoir insérer des
-- `source_authorships` orphelines (source_person_id = NULL) côté ces
-- sources, on relâche la contrainte NOT NULL.
--
-- Les identifiants normalisés (orcid, idref, idhal, hal_person_id,
-- researcher_id) vivront alors directement sur
-- `source_authorships.identifiers` (colonne ajoutée par migration 010).

ALTER TABLE source_authorships
    ALTER COLUMN source_person_id DROP NOT NULL;
