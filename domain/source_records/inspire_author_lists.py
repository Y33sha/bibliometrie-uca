"""Listes d'auteurs d'INSPIRE-HEP, à la place de celles d'OpenAlex.

Un enregistrement source OpenAlex du même document qu'un enregistrement source INSPIRE-HEP est sans contributions sources. Les affiliations d'OpenAlex sont souvent fausses, et INSPIRE-HEP vérifie ses listes d'auteurs. Les deux enregistrements sources désignent le même document quand ils partagent un identifiant de `DOCUMENT_IDENTIFIER_TYPES`, de rôle autre que `related`. Le statut de l'identifiant est sans effet : il se décide après la normalisation.
"""

from collections.abc import Iterable

from domain.source_records.identifiers import (
    SourceIdentifier,
    SourceIdentifierRole,
    SourceIdentifierType,
)
from domain.sources.registry import Source

AUTHOR_LIST_SOURCE = Source.INSPIRE
"""Source dont la liste d'auteurs remplace celle de `WITHHELD_AUTHORS_SOURCE`."""

WITHHELD_AUTHORS_SOURCE = Source.OPENALEX

DOCUMENT_IDENTIFIER_TYPES = frozenset(
    {SourceIdentifierType.DOI, SourceIdentifierType.HAL_ID, SourceIdentifierType.CDS}
)
"""Types d'identifiants qui désignent le même document dans les deux sources. Le DOI d'un dépôt arXiv est un DOI."""

type DocumentKey = tuple[SourceIdentifierType, str]
"""Type et valeur normalisée d'un identifiant."""


def document_keys(identifiers: Iterable[SourceIdentifier]) -> frozenset[DocumentKey]:
    """Renvoie les identifiants de `DOCUMENT_IDENTIFIER_TYPES` de rôle autre que `related`, par type et valeur."""
    return frozenset(
        (i.id_type, i.value)
        for i in identifiers
        if i.id_type in DOCUMENT_IDENTIFIER_TYPES and i.role != SourceIdentifierRole.RELATED
    )
