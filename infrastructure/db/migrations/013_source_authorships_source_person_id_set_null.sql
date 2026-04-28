-- Migration 013 : passer la FK `source_authorships.source_person_id`
-- de `ON DELETE CASCADE` à `ON DELETE SET NULL`.
--
-- Prérequis pour la phase 4 du chantier source_persons : on va DELETE
-- les `source_persons` synthétiques (OA/WoS/CrossRef + HAL form_id-only/
-- nokey + ScanR scanr-* + theses nokey-*). Avec la FK ON DELETE CASCADE
-- actuelle, le DELETE source_persons supprimerait aussi les
-- `source_authorships` correspondantes — désastreux puisqu'on a besoin
-- de garder les authorships (avec source_person_id=NULL) pour le
-- matching cross-source via `identifiers`.
--
-- ON DELETE SET NULL fait passer `source_person_id` à NULL
-- automatiquement à la suppression du source_persons référencé,
-- préservant la source_authorship.

ALTER TABLE source_authorships
    DROP CONSTRAINT source_authorships_source_person_id_fkey;

ALTER TABLE source_authorships
    ADD CONSTRAINT source_authorships_source_person_id_fkey
    FOREIGN KEY (source_person_id)
    REFERENCES source_persons(id)
    ON DELETE SET NULL;
