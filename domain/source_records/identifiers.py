"""Types et rôles des identifiants de `source_record_identifiers`, et normalisation des identifiants d'un enregistrement source."""

from collections.abc import Callable, Iterable, Mapping, Set
from dataclasses import dataclass, replace
from enum import StrEnum

from domain.documents.identifiers import DOI, ISBN, NNT, PMID, HALId, PatentNumber
from domain.serials.containers import ContainerRole, container_role


class SourceIdentifierType(StrEnum):
    """Type d'un identifiant d'enregistrement source."""

    DOI = "doi"
    HAL_ID = "hal_id"
    NNT = "nnt"
    PMID = "pmid"
    ISBN = "isbn"
    EISBN = "eisbn"
    PATENT_PUBLICATION_NUMBER = "patent_publication_number"
    PATENT_APPLICATION_NUMBER = "patent_application_number"
    """Numéro de demande de brevet. Pour l'office WO, il recoupe les numéros de publication d'autres familles."""


class SourceIdentifierRole(StrEnum):
    """Rôle d'un identifiant dans un enregistrement source."""

    PRIMARY = "primary"
    DERIVED = "derived"
    SECONDARY = "secondary"
    RELATED = "related"


SOURCE_IDENTIFIER_ROLE_DEFINITIONS: dict[SourceIdentifierRole, str] = {
    SourceIdentifierRole.PRIMARY: (
        "identifiant de l'enregistrement dans la source. "
        "Un enregistrement source a au plus un identifiant primaire."
    ),
    SourceIdentifierRole.DERIVED: (
        "identifiant de l'enregistrement d'une autre source dont l'enregistrement source est "
        "dérivé. Un enregistrement source a au plus un identifiant dérivé."
    ),
    SourceIdentifierRole.SECONDARY: "identifiant que la source attribue au même document.",
    SourceIdentifierRole.RELATED: "identifiant d'un document lié.",
}

STRONG_ROLES: frozenset[SourceIdentifierRole] = frozenset(
    {SourceIdentifierRole.PRIMARY, SourceIdentifierRole.DERIVED}
)
"""Rôles d'un identifiant qui désigne l'enregistrement source lui-même, dans sa source ou dans celle dont il est dérivé."""

_ROLE_RANK = {role: rank for rank, role in enumerate(SourceIdentifierRole)}
"""Rang de chaque rôle, du plus fort au plus faible."""


@dataclass(frozen=True, slots=True)
class SourceIdentifier:
    """Identifiant d'un enregistrement source, avec son rôle."""

    id_type: SourceIdentifierType
    value: str
    role: SourceIdentifierRole
    removed_by: str | None = None
    """Règle de correction qui retire l'identifiant, `None` pour un identifiant actif."""

    @property
    def key(self) -> tuple[SourceIdentifierType, str]:
        """Type et valeur, qui identifient l'identifiant dans son enregistrement source."""
        return self.id_type, self.value


def by_role(identifiers: Iterable[SourceIdentifier]) -> list[SourceIdentifier]:
    """Trie les identifiants par rôle, dans l'ordre de `SourceIdentifierRole`, puis par valeur."""
    return sorted(identifiers, key=lambda i: (_ROLE_RANK[i.role], i.value))


def active(identifiers: Iterable[SourceIdentifier]) -> list[SourceIdentifier]:
    """Renvoie les identifiants retirés par aucune règle de correction."""
    return [i for i in identifiers if i.removed_by is None]


def own_dois(identifiers: Iterable[SourceIdentifier]) -> set[str]:
    """Renvoie les DOI propres d'un enregistrement source parmi `identifiers` : ses DOI de rôle fort (`STRONG_ROLES`), à défaut ses DOI `secondary`."""
    dois = [
        i
        for i in identifiers
        if i.id_type is SourceIdentifierType.DOI and i.role is not SourceIdentifierRole.RELATED
    ]
    strong = {i.value for i in dois if i.role in STRONG_ROLES}
    return strong or {i.value for i in dois}


def with_removals(
    identifiers: Iterable[SourceIdentifier],
    owned_rules: Set[str],
    removals: Mapping[tuple[SourceIdentifierType, str], str],
) -> tuple[SourceIdentifier, ...]:
    """Recalcule les retraits d'identifiants par les règles de `owned_rules`. Un identifiant retiré par une autre règle reste retiré.

    Args:
        removals: règle qui retire chaque identifiant, par type et valeur.
    """
    return tuple(
        i
        if i.removed_by is not None and i.removed_by not in owned_rules
        else replace(i, removed_by=removals.get(i.key))
        for i in identifiers
    )


def isbn_role(
    raw_doc_type: str | None, source: str, *, declares_conference: bool = False
) -> SourceIdentifierRole:
    """Renvoie le rôle d'un ISBN donné sans qualification par une source : secondaire pour un livre, lié pour un autre document. L'ISBN d'un chapitre ou d'un article de congrès désigne l'ouvrage qui le contient."""
    role = container_role(raw_doc_type, source, declares_conference=declares_conference)
    return (
        SourceIdentifierRole.SECONDARY
        if role is ContainerRole.BOOK
        else SourceIdentifierRole.RELATED
    )


_NORMALIZERS: dict[SourceIdentifierType, Callable[[str], str | None]] = {
    SourceIdentifierType.DOI: DOI.normalize,
    SourceIdentifierType.HAL_ID: HALId.normalize,
    SourceIdentifierType.NNT: NNT.normalize,
    SourceIdentifierType.PMID: PMID.normalize,
    SourceIdentifierType.ISBN: ISBN.normalize,
    SourceIdentifierType.EISBN: ISBN.normalize,
    SourceIdentifierType.PATENT_PUBLICATION_NUMBER: PatentNumber.normalize,
    SourceIdentifierType.PATENT_APPLICATION_NUMBER: PatentNumber.normalize,
}
"""Normalisation d'une valeur par type ; une valeur vide ou `None` signale une valeur invalide."""


def normalize_identifiers(
    identifiers: Iterable[SourceIdentifier],
) -> tuple[tuple[SourceIdentifier, ...], tuple[SourceIdentifier, ...]]:
    """Normalise les identifiants. Renvoie les identifiants normalisés, puis les identifiants écartés pour valeur invalide.

    Chaque valeur passe par le value object de son type. Un identifiant présent plusieurs fois garde la place de sa première occurrence et le plus fort de ses rôles, dans l'ordre de `SourceIdentifierRole`.
    """
    kept: dict[tuple[SourceIdentifierType, str], SourceIdentifier] = {}
    rejected: list[SourceIdentifier] = []
    for identifier in identifiers:
        value = _NORMALIZERS[identifier.id_type](identifier.value)
        if not value:
            rejected.append(identifier)
            continue
        key = (identifier.id_type, value)
        role = identifier.role
        if (previous := kept.get(key)) and _ROLE_RANK[previous.role] < _ROLE_RANK[role]:
            role = previous.role
        kept[key] = SourceIdentifier(identifier.id_type, value, role)
    return tuple(kept.values()), tuple(rejected)
