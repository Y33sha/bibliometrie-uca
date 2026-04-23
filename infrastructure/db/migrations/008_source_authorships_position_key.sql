-- Migration 008 : relâcher la clé d'unicité sur `source_authorships`.
--
-- L'ancienne contrainte `UNIQUE (source_publication_id, source_person_id)`
-- forçait une seule row par couple (publi × personne-source), ce qui
-- écrasait les occurrences multiples d'un même auteur dans une publi :
--
--   - HAL : homonymes partageant un `form_id` générique quand HAL n'a
--     pas de `hal_person_id` (ex. 3 « B. Bertrand » sur hal-04723602),
--     ou erreurs de désambiguïsation HAL (2 personnes distinctes avec
--     le même `hal_person_id`).
--   - WoS : auteurs listés avec plusieurs daisng_id, ou 2 entrées `name`
--     au même `seq_no` (bug amont dans les publis consortium).
--   - OpenAlex, ScanR : patterns similaires.
--
-- Effet collatéral : « trous » dans `author_position` après UPSERT
-- (~246 000 positions manquantes sur 4 037 publis au moment de la
-- migration).
--
-- La nouvelle contrainte ajoute `author_position` à la clé. `NULLS NOT
-- DISTINCT` (PG 15+) traite `author_position IS NULL` comme une valeur
-- comparable — évite que 2 rôles non-auteur d'une même personne sur une
-- même thèse (directeur+jury, par exemple) cohabitent silencieusement.
--
-- La table canonique `authorships` conserve `UNIQUE (publication_id,
-- person_id)` : une personne physique ↔ un authorship par publi. Les
-- `source_authorships` sont désormais un miroir fidèle des sources, la
-- dédup vers l'unicité humaine se fait à la construction de la table
-- canonique (phase `build_authorships`).

ALTER TABLE source_authorships
    DROP CONSTRAINT source_authorships_source_publication_id_source_person_id_key;

ALTER TABLE source_authorships
    ADD CONSTRAINT source_authorships_pub_person_pos_key
    UNIQUE NULLS NOT DISTINCT (source_publication_id, source_person_id, author_position);
