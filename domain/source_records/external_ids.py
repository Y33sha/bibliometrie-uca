"""Clés de la colonne JSONB `source_records.external_ids`, déduite à l'écriture des identifiants de l'enregistrement source."""

from collections.abc import Callable, Iterable
from enum import StrEnum

from domain.source_records.identifiers import (
    SourceIdentifier,
    SourceIdentifierType,
    active,
    by_role,
    identifier_normalizer,
)
from domain.types import JsonValue


class ExternalIdType(StrEnum):
    """Type d'identifiant, clé de `source_records.external_ids`. Le DOI primaire a sa propre colonne `doi`."""

    HAL_ID = "hal_id"
    NNT = "nnt"
    PMID = "pmid"
    PMCID = "pmcid"
    ARXIV_ID = "arxiv_id"
    RELATED_DOIS = "related_dois"
    """Autres DOI du document : preprint, dépôt, dataset, édition, ouvrage hôte d'un chapitre."""
    ISBN = "isbn"
    EISBN = "eisbn"
    """ISBN de l'édition électronique, quand la source distingue les supports (Crossref, WoS)."""


# Types portant une liste de valeurs. Les autres portent une seule valeur.
MULTIVALUED_ID_TYPES = frozenset(
    {
        ExternalIdType.HAL_ID,
        ExternalIdType.RELATED_DOIS,
        ExternalIdType.ISBN,
        ExternalIdType.EISBN,
    }
)


# Type d'identifiant d'enregistrement source de chaque clé.
_IDENTIFIER_TYPES: dict[ExternalIdType, SourceIdentifierType] = {
    ExternalIdType.HAL_ID: SourceIdentifierType.HAL_ID,
    ExternalIdType.NNT: SourceIdentifierType.NNT,
    ExternalIdType.PMID: SourceIdentifierType.PMID,
    ExternalIdType.PMCID: SourceIdentifierType.PMCID,
    ExternalIdType.ARXIV_ID: SourceIdentifierType.ARXIV_ID,
    ExternalIdType.RELATED_DOIS: SourceIdentifierType.DOI,
    ExternalIdType.ISBN: SourceIdentifierType.ISBN,
    ExternalIdType.EISBN: SourceIdentifierType.EISBN,
}

# Normalisation d'une valeur par type ; `None` signale une valeur invalide.
_NORMALIZERS: dict[ExternalIdType, Callable[[str], str | None]] = {
    key: identifier_normalizer(id_type) for key, id_type in _IDENTIFIER_TYPES.items()
}

_KEYS = {id_type: key for key, id_type in _IDENTIFIER_TYPES.items()}


def external_ids_from_identifiers(
    identifiers: Iterable[SourceIdentifier], doi: str | None
) -> dict[str, JsonValue]:
    """`external_ids` des identifiants actifs et normalisés d'un enregistrement source, triés par rôle puis par valeur (`by_role`).

    `related_dois` reçoit les DOI autres que `doi`. Un type à valeur unique reçoit sa première valeur.
    """
    lists: dict[str, list[JsonValue]] = {}
    scalars: dict[str, JsonValue] = {}
    for identifier in by_role(active(identifiers)):
        if identifier.id_type is SourceIdentifierType.DOI and identifier.value == doi:
            continue
        key = _KEYS[identifier.id_type]
        if key in MULTIVALUED_ID_TYPES:
            lists.setdefault(key.value, []).append(identifier.value)
        else:
            scalars.setdefault(key.value, identifier.value)
    return {**scalars, **lists}


def external_id_normalizer(id_type: ExternalIdType) -> Callable[[str], str | None]:
    """Fonction qui rend la forme normalisée d'une valeur de type `id_type`, ou `None` si elle est invalide."""
    return _NORMALIZERS[id_type]
