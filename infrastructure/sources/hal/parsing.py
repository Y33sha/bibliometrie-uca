"""Pure functions de parsing / aiguillage pour l'extraction HAL.

Vit à côté de `extract_hal.py` (wiring HTTP) et de `fetch_missing_hal_id.py`
(wiring async). Ne fait aucun I/O. Couvert par `tests/unit/infrastructure/sources/hal/test_parsing.py`.

Le wiring (HTTP, pagination, SQL d'écriture, subclass `SourceExtractor`)
reste dans `extract_hal.py` et est exclu de la couverture
(cf. `CODE_couverture-tests.md`).
"""

from __future__ import annotations

from typing import Literal

from infrastructure.sources.common import clean_doi


def build_query(years: list[int] | None, since: str | None = None) -> str:
    """Construit la requête Solr HAL (paramètre `q`).

    Si `since` est fourni (format `YYYY-MM-DD`), filtre sur
    `submittedDate_tdate` au lieu de filtrer par années. Sinon, encadre
    `producedDateY_i` par `[min(years) TO max(years)]`. Au moins un des
    deux doit être fourni.
    """
    if since:
        return f"submittedDate_tdate:[{since}T00:00:00Z TO *]"
    if not years:
        raise ValueError("build_query requires either `since` or a non-empty `years` list")
    year_min = min(years)
    year_max = max(years)
    return f"producedDateY_i:[{year_min} TO {year_max}]"


def build_url(base_url: str) -> str:
    """Construit l'URL de recherche HAL à partir de la base API."""
    return f"{base_url}/"


def extract_hal_id(doc: dict) -> str:
    """Extrait le halId depuis un document HAL (champ `halId_s`)."""
    return doc.get("halId_s", "")


def extract_doi(doc: dict) -> str | None:
    """Extrait le DOI nettoyé depuis un document HAL (champ `doiId_s`)."""
    return clean_doi(doc.get("doiId_s"))


def count_full_fetch_pages(total_count: int, per_page: int) -> int:
    """Nombre de pages nécessaires pour paginer une collection en full-fetch."""
    if total_count <= 0:
        return 0
    return (total_count + per_page - 1) // per_page


def choose_extraction_mode(
    total_count: int,
    n_orphans: int,
    per_page: int,
) -> Literal["full", "incremental", "skip"]:
    """Décide du mode d'extraction d'une collection HAL.

    Trois branches :

    - `"skip"` : collection vide côté API, rien à faire.
    - `"incremental"` : fetch individuel des `n_orphans` documents
      absents du staging + UPDATE SQL pour tagger les connus. Choisi
      quand `n_orphans < full_fetch_pages`.
    - `"full"` : pagination complète de la collection, ré-upsert de
      tous les documents.

    **Intention historique.** Éviter de re-full-fetch une collection
    umbrella (typiquement `PRES_UCA`) qui passe après les collections
    labos : la plupart des documents sont déjà en staging via leur
    collection labo, seuls quelques orphelins restent à récupérer
    individuellement.

    **Limite connue.** La fonction de coût compare des nombres d'appels
    HTTP en ignorant la taille de payload par appel. Une page
    full-fetch (`per_page` docs avec `HAL_FIELDS` incluant `label_xml`)
    peut peser nettement plus qu'un fetch individuel. Cas observé
    (PRES_UCA, dernier import) : 19 orphelins vs 12 pages → branche
    `"full"` choisie alors qu'incrémentale aurait été plus rapide en
    wall time. Fonction de coût à revoir — question ouverte dans
    [CODE_couverture-tests.md](../../../docs/chantiers/CODE_couverture-tests.md).
    """
    if total_count == 0:
        return "skip"
    full_fetch_pages = count_full_fetch_pages(total_count, per_page)
    if n_orphans < full_fetch_pages:
        return "incremental"
    return "full"
