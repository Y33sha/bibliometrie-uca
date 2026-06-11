"""Règles pures de déduplication des publications — référentiel métier.

Deux familles de règles, toutes pures (le caller — les passes de fusion
applicatives — prefetch les lookups via le repo et applique les effets) :

- `DeduplicationKey` : les identifiants cross-source par lesquels deux
  publications sont la même œuvre. Chacun donne une passe `merge_pubs_by_<clé>` :
  le partage de l'identifiant suffit à fusionner, sous réserve des gardes de
  distinction.
- `MetadataDeduplicationCase` + `detect_metadata_merge_case` : fusion par
  métadonnées (titre normalisé + année identiques) quand aucun identifiant n'est
  partagé.

Les cas où l'on **ne fusionne pas** (ouvrage/chapitre, etc.) sont à part, dans
`distinct_publications.py`.
"""

from enum import StrEnum

from domain.normalize import normalize_name
from domain.sources.theses import thesis_authors_compatible

_THESIS_DOC_TYPES: frozenset[str] = frozenset({"thesis", "ongoing_thesis"})
_PROCEEDINGS_MIN_TITLE_LEN = 30


class DeduplicationKey(StrEnum):
    """Identifiants cross-source par lesquels deux publications sont la même œuvre.

    Chacun donne une passe de fusion dédiée (`merge_pubs_by_doi`, `_by_nnt`,
    `_by_hal_id`, `_by_pmid`) : le partage de l'identifiant suffit à fusionner,
    sous réserve des gardes de distinction (`distinct_publications`, DOI non-nuls
    différents).
    """

    DOI = "doi"
    NNT = "nnt"
    HAL_ID = "hal_id"
    PMID = "pmid"


class MetadataDeduplicationCase(StrEnum):
    """Fusion par métadonnées : deux publications au même `title_normalized` +
    `pub_year` considérées comme la même œuvre, sans identifiant partagé."""

    # Thèse : doc_types dans la famille thèse (`thesis`/`ongoing_thesis`) et
    # auteur primary compatible. Si l'auteur de l'un est inconnu, accepté (le
    # titre + l'année font foi).
    THESIS_TITLE_YEAR = "thesis_title_year"

    # Proceedings : `doc_type = 'proceedings'`, titre normalisé long (> 30 car.,
    # pour exclure les titres pauvres type « Foreword »), et même nombre
    # d'auteurs (`MAX` par source de chaque côté). Le cas « deux DOI non-nuls
    # différents » est écarté en amont par la garde de fusion (œuvres
    # distinctes), pas ici.
    PROCEEDINGS_TITLE_YEAR_AUTHORCOUNT = "proceedings_title_year_authorcount"


def _thesis_authors_compatible(
    primary_a: tuple[str, str] | None, primary_b: tuple[str, str] | None
) -> bool:
    if primary_a is None or primary_b is None:
        return True
    # `thesis_authors_compatible` normalise `primary` mais attend le `claimed`
    # déjà normalisé ; les deux viennent ici de la BDD, on normalise le second.
    claimed = (normalize_name(primary_b[0]), normalize_name(primary_b[1]))
    return thesis_authors_compatible(primary_a, claimed)


def detect_metadata_merge_case(
    *,
    doc_type_a: str,
    doc_type_b: str,
    title_normalized: str,
    thesis_primary_author_a: tuple[str, str] | None = None,
    thesis_primary_author_b: tuple[str, str] | None = None,
    author_count_a: int | None = None,
    author_count_b: int | None = None,
) -> MetadataDeduplicationCase | None:
    """Cas de fusion par métadonnées pour deux publications au même titre + année.

    Pure. Seuls les critères du doc_type concerné sont évalués : auteur primary
    pour la famille thèse, nombre d'auteurs pour les proceedings ; les autres
    entrées sont ignorées.
    """
    types = {doc_type_a, doc_type_b}
    if types <= _THESIS_DOC_TYPES:
        if _thesis_authors_compatible(thesis_primary_author_a, thesis_primary_author_b):
            return MetadataDeduplicationCase.THESIS_TITLE_YEAR
        return None
    if types == {"proceedings"}:
        if len(title_normalized) > _PROCEEDINGS_MIN_TITLE_LEN and author_count_a == author_count_b:
            return MetadataDeduplicationCase.PROCEEDINGS_TITLE_YEAR_AUTHORCOUNT
        return None
    return None
