-- Migration 012 : passer la contrainte UNIQUE de
-- `source_authorships(source_publication_id, source_person_id, author_position)`
-- de NULLS NOT DISTINCT à NULLS DISTINCT.
--
-- Contexte : depuis le chantier source_persons, certaines sources
-- écrivent `source_person_id=NULL`. Et theses.fr peut avoir plusieurs
-- non-auteurs (jury, rapporteurs) sans PPN sur une même thèse, qui
-- auraient `(pub_id, NULL, NULL)` — bloqués par la contrainte
-- NULLS NOT DISTINCT actuelle (un seul row autorisé par publi).
--
-- En pratique l'idempotence des `source_authorships` est garantie par
-- `clear_source_authorships_for_publication` (DELETE avant INSERT)
-- dans tous les normalizers ; le `ON CONFLICT DO UPDATE` n'est qu'un
-- filet de sécurité jamais déclenché en production. Passer en
-- NULLS DISTINCT n'a donc pas d'impact pratique sur les autres sources
-- (qui posent toujours `author_position` non-null).
--
-- Note : NULLS DISTINCT est le défaut SQL standard ; on peut donc
-- omettre la clause explicite (équivalent à `UNIQUE (...)` sans
-- préciser).

ALTER TABLE source_authorships
    DROP CONSTRAINT source_authorships_pub_person_pos_key;

ALTER TABLE source_authorships
    ADD CONSTRAINT source_authorships_pub_person_pos_key
    UNIQUE (source_publication_id, source_person_id, author_position);
