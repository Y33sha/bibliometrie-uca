-- Migration 019 : index partial sur authorships(publication_id) WHERE in_perimeter.
--
-- `PUB_IS_UCA` (filtres.py) interroge fréquemment :
--   EXISTS (SELECT 1 FROM authorships a
--           WHERE a.publication_id = p.id AND a.in_perimeter = TRUE)
-- pour résoudre les facettes et listes de la page publications. Sans index
-- partial, le planner utilise `idx_authorships_pub` (complet) puis filtre
-- `in_perimeter` ligne à ligne — 7 lignes sur 8 sont rejetées en moyenne.
-- Le partial n'indexe que les authorships UCA, supprime ce filtre, et divise
-- par ~3 le nombre de buffers lus pour cette branche.
--
-- Mesure locale (page publications, _facet_labs) : 601ms → 479ms (~20 %),
-- shared buffers : 1.32M → 826k.
--
-- Les index existants `idx_authorships_pub` (complet) et `idx_authorships_uca`
-- (sur in_perimeter seul) restent utiles pour d'autres patterns d'accès.

CREATE INDEX idx_authorships_pub_uca
    ON authorships (publication_id)
    WHERE in_perimeter = TRUE;
