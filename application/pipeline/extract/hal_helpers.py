"""Heuristiques d'orchestration de l'extraction HAL.

Savoir orchestrateur (pas savoir adapter) : étant donné le volume d'une
collection et le nombre d'orphelins absents du staging, décide s'il faut
paginer toute la collection (`full`) ou fetcher les orphelins un par un
(`incremental`). Aucun I/O, aucune connaissance de la syntaxe Solr ni du
format JSON HAL — `per_page` est fourni par l'appelant.
"""

from __future__ import annotations

from typing import Literal


def count_full_fetch_pages(total_count: int, per_page: int) -> int:
    """Nombre de pages nécessaires pour paginer une collection en full-fetch."""
    if total_count <= 0:
        return 0
    return (total_count + per_page - 1) // per_page


_ORPHAN_TO_PAGE_RATIO = 10
"""Coefficient « 1 page full-fetch ≈ N fetchs unitaires » (cost function HAL).

Une page full-fetch tire `per_page` documents avec `HAL_FIELDS` incluant
`label_xml` (TEI verbeux) — payload + parsing typiquement bien plus lourds
qu'un fetch unitaire. À la grosse louche, on dit qu'une page coûte ≈ 10
requêtes unitaires. Calibrable empiriquement après quelques runs réels.
"""


def choose_extraction_mode(
    total_count: int,
    n_orphans: int,
    per_page: int,
) -> Literal["full", "incremental", "skip"]:
    """Décide du mode d'extraction d'une collection HAL.

    Trois branches :

    - `"skip"` : collection vide côté API, rien à faire.
    - `"incremental"` : fetch individuel des `n_orphans` documents absents
      du staging + UPDATE SQL pour tagger les connus. Choisi quand
      `n_orphans < _ORPHAN_TO_PAGE_RATIO * full_fetch_pages` — c'est-à-dire
      tant que le coût des fetchs unitaires reste plus faible que celui des
      pages full-fetch (cf. `_ORPHAN_TO_PAGE_RATIO`).
    - `"full"` : pagination complète de la collection, ré-upsert de tous
      les documents.

    **Intention.** Éviter de re-full-fetch une collection umbrella
    (typiquement `PRES_CLERMONT`) qui passe après les collections labos :
    la plupart des documents sont déjà en staging via leur collection
    labo, seuls quelques orphelins restent à récupérer individuellement.
    """
    if total_count == 0:
        return "skip"
    full_fetch_pages = count_full_fetch_pages(total_count, per_page)
    if n_orphans < _ORPHAN_TO_PAGE_RATIO * full_fetch_pages:
        return "incremental"
    return "full"
