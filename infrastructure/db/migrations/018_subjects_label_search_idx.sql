-- Migration 018 : index trigram pour accélérer la recherche par label de sujet.
--
-- Phase 7 du chantier sujets / mots-clés.
--
-- `list_publications` (filtre `search`) match désormais aussi `subjects.label`
-- via ILIKE. Sans index, c'est un seq scan sur la table subjects.
--
-- L'index s'appuie sur `normalize_name_form` (déjà présente côté schéma,
-- IMMUTABLE, équivalent SQL de `normalize_text` côté Python — c'est la
-- normalisation utilisée pour `publications.title_normalized` et son index
-- trigram `idx_pub_title_trgm`). On garde donc un seul pipeline de
-- normalisation pour la recherche, indexée des deux côtés.
--
-- Note Postgres : `normalize_name_form` appelle `unaccent` sans qualifier
-- le schéma, ce qui plante au moment de l'inlining lors de la création
-- de l'index (search_path indéterminé). On fige le search_path de la
-- fonction sur `public, pg_temp` (= valeur par défaut, juste explicite),
-- ce qui ne change pas le comportement des appels existants mais rend
-- l'inlining résolvable.
--
-- Les DROP IF EXISTS couvrent une première itération qui passait par une
-- fonction dédiée `subject_search_form` ; ils rendent la migration
-- idempotente.

DROP INDEX IF EXISTS subjects_label_search_trgm_idx;
DROP FUNCTION IF EXISTS public.subject_search_form(text);

ALTER FUNCTION public.normalize_name_form(text)
    SET search_path = public, pg_temp;

CREATE INDEX subjects_label_norm_trgm_idx
    ON subjects USING gin (public.normalize_name_form(label) public.gin_trgm_ops);
