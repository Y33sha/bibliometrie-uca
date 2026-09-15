"""Clés de la colonne JSONB `source_publications.external_ids` et normalisation de ses valeurs à l'écriture."""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum

from domain.publications.identifiers import DOI, ISBN, ISSN, NNT, PMCID, PMID, ArxivId, HALId
from domain.types import JsonValue


class ExternalIdType(StrEnum):
    """Type d'identifiant, clé de `source_publications.external_ids`. Le DOI primaire a sa propre colonne `doi`."""

    HAL_ID = "hal_id"
    NNT = "nnt"
    PMID = "pmid"
    PMCID = "pmcid"
    ARXIV_ID = "arxiv_id"
    RELATED_DOIS = "related_dois"
    """Autres DOI du document : preprint, dépôt, dataset, édition, ouvrage hôte d'un chapitre."""
    ISSN = "issn"
    ISBN = "isbn"


# Types portant une liste de valeurs. Les autres portent une seule valeur.
MULTIVALUED_ID_TYPES = frozenset(
    {ExternalIdType.HAL_ID, ExternalIdType.RELATED_DOIS, ExternalIdType.ISSN, ExternalIdType.ISBN}
)


def _via[VO](try_parse: Callable[[str], VO | None]) -> Callable[[str], str | None]:
    def normalize(raw: str) -> str | None:
        vo = try_parse(raw)
        return str(vo) if vo is not None else None

    return normalize


# Normalisation d'une valeur par type ; `None` signale une valeur invalide.
_NORMALIZERS: dict[ExternalIdType, Callable[[str], str | None]] = {
    ExternalIdType.HAL_ID: _via(HALId.try_parse),
    ExternalIdType.NNT: _via(NNT.try_parse),
    ExternalIdType.PMID: _via(PMID.try_parse),
    ExternalIdType.PMCID: _via(PMCID.try_parse),
    ExternalIdType.ARXIV_ID: _via(ArxivId.try_parse),
    ExternalIdType.RELATED_DOIS: _via(DOI.try_parse),
    ExternalIdType.ISSN: _via(ISSN.try_parse),
    ExternalIdType.ISBN: _via(ISBN.try_parse),
}


@dataclass(frozen=True, slots=True)
class RejectedExternalId:
    """Entrée écartée d'un `external_ids` : clé hors de `ExternalIdType`, ou valeur invalide pour son type."""

    key: str
    value: JsonValue


def normalize_external_ids(
    raw: Mapping[str, JsonValue],
) -> tuple[dict[str, JsonValue], tuple[RejectedExternalId, ...]]:
    """Normalise un `external_ids` et retourne les entrées écartées.

    Chaque valeur passe par le value object de son type. Une valeur invalide est écartée, de même qu'une clé hors de `ExternalIdType`. Un type multivalué accepte une valeur isolée et devient une liste dédoublonnée. Un type sans valeur valide est absent du résultat. Idempotent.
    """
    clean: dict[str, JsonValue] = {}
    rejected: list[RejectedExternalId] = []
    for key, value in raw.items():
        try:
            id_type = ExternalIdType(key)
        except ValueError:
            rejected.append(RejectedExternalId(key, value))
            continue
        normalize = _NORMALIZERS[id_type]
        values = value if isinstance(value, list) else [value]
        kept: list[str] = []
        for v in values:
            normalized = normalize(v) if isinstance(v, str) else None
            if normalized is None:
                if v is not None:
                    rejected.append(RejectedExternalId(key, v))
            elif normalized not in kept:
                kept.append(normalized)
        if not kept:
            continue
        if id_type in MULTIVALUED_ID_TYPES:
            clean[id_type.value] = list(kept)
        else:
            clean[id_type.value] = kept[0]
            rejected.extend(RejectedExternalId(key, v) for v in kept[1:])
    return clean, tuple(rejected)
