"""Types et rôles des identifiants de `source_record_identifiers`, et normalisation des identifiants d'un enregistrement source."""

from collections.abc import Callable, Iterable, Mapping, Set
from dataclasses import dataclass, replace
from enum import StrEnum

from domain.publications.identifiers import DOI, ISBN, NNT, PMCID, PMID, ArxivId, HALId
from domain.serials.containers import ContainerRole, container_role


class SourceIdentifierType(StrEnum):
    """Type d'un identifiant d'enregistrement source."""

    DOI = "doi"
    HAL_ID = "hal_id"
    NNT = "nnt"
    PMID = "pmid"
    PMCID = "pmcid"
    ARXIV_ID = "arxiv_id"
    ISBN = "isbn"
    EISBN = "eisbn"


class SourceIdentifierRole(StrEnum):
    """Rôle d'un identifiant dans un enregistrement source."""

    PRIMARY = "primary"
    DERIVED = "derived"
    SECONDARY = "secondary"
    RELATED = "related"


SOURCE_IDENTIFIER_ROLE_DEFINITIONS: dict[SourceIdentifierRole, str] = {
    SourceIdentifierRole.PRIMARY: "identifiant de l'enregistrement dans la source.",
    SourceIdentifierRole.DERIVED: (
        "identifiant de l'enregistrement d'une autre source dont l'enregistrement source est "
        "dérivé. Un enregistrement source a au plus un identifiant dérivé."
    ),
    SourceIdentifierRole.SECONDARY: "identifiant que la source attribue au même document.",
    SourceIdentifierRole.RELATED: "identifiant d'un document lié.",
}

# Rang de chaque rôle, du plus fort au plus faible.
_ROLE_RANK = {role: rank for rank, role in enumerate(SourceIdentifierRole)}


@dataclass(frozen=True, slots=True)
class SourceIdentifier:
    """Identifiant d'un enregistrement source, avec son rôle. `removed_by` : règle de correction qui le retire, `None` pour un identifiant actif."""

    id_type: SourceIdentifierType
    value: str
    role: SourceIdentifierRole
    removed_by: str | None = None

    @property
    def key(self) -> tuple[SourceIdentifierType, str]:
        """Type et valeur, qui identifient l'identifiant dans son enregistrement source."""
        return self.id_type, self.value


def by_role(identifiers: Iterable[SourceIdentifier]) -> list[SourceIdentifier]:
    """Identifiants triés par rôle, dans l'ordre de `SourceIdentifierRole`, puis par valeur."""
    return sorted(identifiers, key=lambda i: (_ROLE_RANK[i.role], i.value))


def active(identifiers: Iterable[SourceIdentifier]) -> list[SourceIdentifier]:
    """Identifiants qu'aucune règle de correction ne retire."""
    return [i for i in identifiers if i.removed_by is None]


def own_dois(identifiers: Iterable[SourceIdentifier]) -> set[str]:
    """DOI propres d'un enregistrement source parmi `identifiers` : ses DOI `primary` ou `derived`, à défaut ses DOI `secondary`."""
    dois = [
        i
        for i in identifiers
        if i.id_type is SourceIdentifierType.DOI and i.role is not SourceIdentifierRole.RELATED
    ]
    strong = {
        i.value
        for i in dois
        if i.role in (SourceIdentifierRole.PRIMARY, SourceIdentifierRole.DERIVED)
    }
    return strong or {i.value for i in dois}


def with_removals(
    identifiers: Iterable[SourceIdentifier],
    owned_rules: Set[str],
    removals: Mapping[tuple[SourceIdentifierType, str], str],
) -> tuple[SourceIdentifier, ...]:
    """Identifiants dont les retraits par les règles de `owned_rules` sont recalculés : `removals` donne la règle qui retire chaque identifiant, par type et valeur. Un identifiant retiré par une autre règle reste retiré."""
    return tuple(
        i
        if i.removed_by is not None and i.removed_by not in owned_rules
        else replace(i, removed_by=removals.get(i.key))
        for i in identifiers
    )


def isbn_role(
    raw_doc_type: str | None, source: str, *, declares_conference: bool = False
) -> SourceIdentifierRole:
    """Rôle d'un ISBN qu'une source donne sans le qualifier : secondaire pour un livre, lié pour un autre document. L'ISBN d'un chapitre ou d'un article de congrès désigne l'ouvrage qui le contient."""
    role = container_role(raw_doc_type, source, declares_conference=declares_conference)
    return (
        SourceIdentifierRole.SECONDARY
        if role is ContainerRole.BOOK
        else SourceIdentifierRole.RELATED
    )


def _via[VO](try_parse: Callable[[str], VO | None]) -> Callable[[str], str | None]:
    def normalize(raw: str) -> str | None:
        vo = try_parse(raw)
        return str(vo) if vo is not None else None

    return normalize


# Normalisation d'une valeur par type ; `None` signale une valeur invalide.
_NORMALIZERS: dict[SourceIdentifierType, Callable[[str], str | None]] = {
    SourceIdentifierType.DOI: _via(DOI.try_parse),
    SourceIdentifierType.HAL_ID: _via(HALId.try_parse),
    SourceIdentifierType.NNT: _via(NNT.try_parse),
    SourceIdentifierType.PMID: _via(PMID.try_parse),
    SourceIdentifierType.PMCID: _via(PMCID.try_parse),
    SourceIdentifierType.ARXIV_ID: _via(ArxivId.try_parse),
    SourceIdentifierType.ISBN: _via(ISBN.try_parse),
    SourceIdentifierType.EISBN: _via(ISBN.try_parse),
}


def normalize_identifiers(
    identifiers: Iterable[SourceIdentifier],
) -> tuple[tuple[SourceIdentifier, ...], tuple[SourceIdentifier, ...]]:
    """Identifiants normalisés, puis identifiants écartés pour valeur invalide.

    Chaque valeur passe par le value object de son type. Un identifiant présent plusieurs fois garde la place de sa première occurrence et le plus fort de ses rôles, dans l'ordre de `SourceIdentifierRole`.
    """
    kept: dict[tuple[SourceIdentifierType, str], SourceIdentifier] = {}
    rejected: list[SourceIdentifier] = []
    for identifier in identifiers:
        value = _NORMALIZERS[identifier.id_type](identifier.value)
        if value is None:
            rejected.append(identifier)
            continue
        key = (identifier.id_type, value)
        role = identifier.role
        if (previous := kept.get(key)) and _ROLE_RANK[previous.role] < _ROLE_RANK[role]:
            role = previous.role
        kept[key] = SourceIdentifier(identifier.id_type, value, role)
    return tuple(kept.values()), tuple(rejected)
