"""Pure functions de parsing pour l'extraction OpenAlex.

Vit à côté de `extract_openalex.py`, `fetch_missing_doi.py` et
`refetch_truncated.py` (wiring HTTP). Ne fait aucun I/O. Couvert par
`tests/unit/infrastructure/sources/openalex/test_parsing.py`.

L'auth (`init_auth`, `auth_params`) et la constante `SELECT_FIELDS`
restent dans `__init__.py` : ce ne sont pas des pure functions
testables au sens où on entend ici.
"""

from __future__ import annotations

from infrastructure.sources.common import clean_doi, compute_hash
from infrastructure.sources.openalex import SELECT_FIELDS, auth_params


def extract_openalex_id(work: dict) -> str:
    """Extrait l'ID OpenAlex court (ex: `W2741809807`).

    L'API retourne l'ID sous forme d'URL complète
    (`https://openalex.org/W...`) ; on garde uniquement le préfixe court
    pour servir de `source_id` en staging.
    """
    return work["id"].replace("https://openalex.org/", "")


def extract_doi(work: dict) -> str | None:
    """Extrait le DOI nettoyé d'un work OpenAlex (sans préfixe URL)."""
    return clean_doi(work.get("doi"))


def compute_meta_hash(raw_data: dict) -> str:
    """Hash des métadonnées hors `authorships`.

    Permet de détecter les changements de métadonnées (titre, OA status,
    etc.) sans être perturbé par la troncature à 100 auteurs de l'API
    bulk. Utilisé par `extract_openalex.insert_batch` pour décider
    s'il faut écraser `raw_data` ou préserver une version plus complète
    (cf. `refetch_truncated`).
    """
    filtered = {k: v for k, v in raw_data.items() if k != "authorships"}
    return compute_hash(filtered)


def build_params(
    year: int | None = None,
    cursor: str = "*",
    institution_ids: list[str] | None = None,
    since: str | None = None,
) -> dict:
    """Construit les paramètres de requête pour l'API OpenAlex `/works`.

    Si `since` est fourni (format `YYYY-MM-DD`), filtre sur
    `from_updated_date`. Sinon filtre sur `publication_year`. Le
    `lineage:` agrège les institutions par `|` (OR).

    Les paramètres d'auth (`api_key` ou `mailto`) sont ajoutés via
    `auth_params()` qui lit l'état initialisé par `init_auth()`.
    """
    from infrastructure.sources.api_limits import OPENALEX_PER_PAGE

    lineage_filter = "|".join(institution_ids or [])
    if since:
        filter_str = f"authorships.institutions.lineage:{lineage_filter},from_updated_date:{since}"
    else:
        filter_str = f"authorships.institutions.lineage:{lineage_filter},publication_year:{year}"
    return {
        "filter": filter_str,
        "select": SELECT_FIELDS,
        "per_page": OPENALEX_PER_PAGE,
        "cursor": cursor,
        **auth_params(),
    }
