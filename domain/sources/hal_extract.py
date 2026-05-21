"""Constantes et helpers purs pour l'extraction HAL.

Tout ce qui peut être consommé par l'orchestrateur applicatif sans
toucher à `infrastructure` : timing de rate-limit, taille de page par
collection, construction de requête Solr, parsing de documents.

L'infrastructure (adapter HTTP) importe ces helpers aussi pour rester
cohérente. Les helpers infra-only (build_url, taille de page Solr
preview) restent dans `infrastructure/sources/hal/`.
"""

from __future__ import annotations

from typing import Literal

from domain.publications.identifiers import clean_doi

# ── Rate-limit / pagination ────────────────────────────────────────

HAL_DELAY = 0.5
"""Pause entre deux requêtes consécutives au cluster HAL (s)."""

HAL_PER_PAGE = 500
"""Taille de page par défaut (max autorisé Solr = 10 000)."""

HAL_PER_PAGE_OVERRIDES: dict[str, int] = {
    "LPC-CLERMONT": 50,
}
"""Overrides par collection.

Collections de physique des particules avec méga-authorships (3000+
auteurs, collabs CERN/ATLAS/CMS, etc.) produisent des payloads énormes
côté `label_xml` — le serveur HAL time-out à 500 records/page et
renvoie des 500. Descendre à un per_page plus petit stabilise
l'extraction sur ces collections.
"""


def hal_per_page_for(collection_code: str | None) -> int:
    """Retourne le `per_page` HAL à utiliser pour une collection donnée."""
    if collection_code and collection_code in HAL_PER_PAGE_OVERRIDES:
        return HAL_PER_PAGE_OVERRIDES[collection_code]
    return HAL_PER_PAGE


# ── Requête Solr ────────────────────────────────────────────────────


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


# ── Parsing de documents ───────────────────────────────────────────


def extract_hal_id(doc: dict) -> str:
    """Extrait le halId depuis un document HAL (champ `halId_s`)."""
    return doc.get("halId_s", "")


def extract_doi(doc: dict) -> str | None:
    """Extrait le DOI nettoyé depuis un document HAL (champ `doiId_s`)."""
    return clean_doi(doc.get("doiId_s"))


# ── Aiguillage full vs incremental ─────────────────────────────────


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
    (typiquement `PRES_UCA`/`PRES_CLERMONT`) qui passe après les collections
    labos : la plupart des documents sont déjà en staging via leur
    collection labo, seuls quelques orphelins restent à récupérer
    individuellement.
    """
    if total_count == 0:
        return "skip"
    full_fetch_pages = count_full_fetch_pages(total_count, per_page)
    if n_orphans < _ORPHAN_TO_PAGE_RATIO * full_fetch_pages:
        return "incremental"
    return "full"
