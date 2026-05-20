"""Constantes et helpers purs pour l'extraction OpenAlex.

Tout ce qui peut être consommé par l'orchestrateur applicatif sans
toucher à `infrastructure` : timing de rate-limit, parsing de documents.

L'adapter HTTP (`PgOpenalexExtractAdapter`) importe ces helpers ; les
helpers infra-only (`build_params` qui dépend de `SELECT_FIELDS` et
`auth_params`) restent dans `infrastructure/sources/openalex/`.
"""

from __future__ import annotations

from domain.publications.identifiers import clean_doi

# ── Rate-limit ─────────────────────────────────────────────────────

OPENALEX_DELAY = 0.2
"""Pause entre deux requêtes consécutives à OpenAlex (s).

Polite pool (~5 req/s, 10 req/s toléré).
"""


# ── Parsing de documents ───────────────────────────────────────────


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
