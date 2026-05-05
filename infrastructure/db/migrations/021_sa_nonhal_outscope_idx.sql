-- Migration 021 : index partial sur source_authorships (positions hors-UCA non-HAL).
--
-- La page `/api/hal-problems/affiliation-conflicts` cherche les positions
-- d'auteur où HAL atteste l'UCA mais une autre source (non-HAL) a examiné
-- la même position et conclu hors-UCA. La requête doit donc trouver les
-- source_authorships avec `source <> 'hal' AND in_perimeter = FALSE`,
-- soit ~6,3M lignes sur 10M dans source_authorships.
--
-- Sans cet index, le planner faisait un seq scan complet (5M+ lignes
-- filtrées) suivi d'un hash join avec source_authorship_addresses (9M).
-- Le COUNT du CTE prenait ~7,2 s sur 3 302 conflits réels.
--
-- L'index partial sur (source_publication_id, author_position) permet
-- au planner de driver depuis les ~17K positions UCA-HAL et de probe
-- ce set en nested loop ciblé. Mesure locale : 7,2s → ~0,6s (×12).
--
-- À éviter : lancer cette migration pendant un run du pipeline. La
-- création d'index sans CONCURRENTLY prend un verrou qui bloque les
-- écritures sur source_authorships le temps du build.

CREATE INDEX idx_sa_nonhal_outscope
    ON source_authorships (source_publication_id, author_position)
    WHERE source <> 'hal' AND in_perimeter = FALSE;
