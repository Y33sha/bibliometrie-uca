"""Champs d'une fiche de la littérature INSPIRE-HEP (`metadata` d'une réponse de l'API)."""

from __future__ import annotations

from collections.abc import Mapping

from domain.documents.dates import PublicationDate, parse_iso_date
from domain.documents.identifiers import DOI, CdsId, HALId, arxiv_doi
from domain.source_records.identifiers import (
    SourceIdentifier,
    SourceIdentifierRole,
    SourceIdentifierType,
)
from domain.types import JsonValue, as_int, as_mapping, as_sequence, as_str, as_text

_RELATED_DOI_MATERIALS = frozenset(
    {"erratum", "addendum", "reprint", "translation", "editorial note", "data"}
)
"""Natures (`material`) d'un DOI ou d'une publication qui désignent un autre document que la fiche."""


def record_id(record: Mapping[str, JsonValue]) -> str | None:
    """Renvoie le numéro de la fiche (`control_number`)."""
    number = record.get("control_number")
    if isinstance(number, int):
        return str(number)
    return as_str(number)


def _publication_infos(record: Mapping[str, JsonValue]) -> list[Mapping[str, JsonValue]]:
    """Renvoie les publications de la fiche (`publication_info`), sauf celles d'un erratum, d'un addendum ou d'une traduction."""
    return [
        info
        for entry in as_sequence(record.get("publication_info"))
        if (info := as_mapping(entry))
        and as_str(info.get("material")) not in _RELATED_DOI_MATERIALS
    ]


def _doi_entries(record: Mapping[str, JsonValue]) -> dict[str, bool]:
    """Renvoie les DOI de la fiche, nettoyés, dans leur ordre, chacun avec vrai s'il désigne un autre document (erratum, jeu de données). Une seule mention de cette nature suffit."""
    entries: dict[str, bool] = {}
    for entry in as_sequence(record.get("dois")):
        item = as_mapping(entry)
        if doi := DOI.normalize(as_str(item.get("value"))):
            related = as_str(item.get("material")) in _RELATED_DOI_MATERIALS
            entries[doi] = entries.get(doi, False) or related
    return entries


def record_dois(record: Mapping[str, JsonValue]) -> list[str]:
    """Renvoie les DOI de la fiche elle-même, dans leur ordre."""
    return [doi for doi, related in _doi_entries(record).items() if not related]


def _external_ids(record: Mapping[str, JsonValue], schema: str) -> list[str]:
    """Renvoie les identifiants de la fiche dans un système externe (`external_system_identifiers`), pour le schéma `schema`."""
    return [
        value
        for entry in as_sequence(record.get("external_system_identifiers"))
        if (item := as_mapping(entry)).get("schema") == schema
        and (value := as_str(item.get("value")))
    ]


def record_identifiers(record: Mapping[str, JsonValue]) -> tuple[SourceIdentifier, ...]:
    """Renvoie les identifiants de la fiche, secondaires : DOI, DOI arXiv, hal-id et identifiant CDS. Le DOI d'un autre document (erratum, jeu de données) est lié."""
    secondary, related = SourceIdentifierRole.SECONDARY, SourceIdentifierRole.RELATED
    identifiers = [
        SourceIdentifier(SourceIdentifierType.DOI, doi, related if is_related else secondary)
        for doi, is_related in _doi_entries(record).items()
    ]
    identifiers += [
        SourceIdentifier(SourceIdentifierType.DOI, doi, secondary)
        for entry in as_sequence(record.get("arxiv_eprints"))
        if (doi := arxiv_doi(as_str(as_mapping(entry).get("value"))))
    ]
    identifiers += [
        SourceIdentifier(SourceIdentifierType.HAL_ID, hal_id, secondary)
        for value in _external_ids(record, "HAL")
        if (hal_id := HALId.normalize(value))
    ]
    identifiers += [
        SourceIdentifier(SourceIdentifierType.CDS, cds_id, secondary)
        for value in _external_ids(record, "CDS")
        if (cds_id := CdsId.normalize(value))
    ]
    return tuple(identifiers)


def title(record: Mapping[str, JsonValue]) -> str | None:
    """Renvoie le premier titre de la fiche."""
    for entry in as_sequence(record.get("titles")):
        if (text := as_str(as_mapping(entry).get("title"))) and text.strip():
            return text
    return None


def journal_title(record: Mapping[str, JsonValue]) -> str | None:
    """Renvoie le titre abrégé de la revue de la première publication (`Phys.Rev.D`)."""
    for info in _publication_infos(record):
        if (name := as_str(info.get("journal_title"))) and name.strip():
            return name
    return None


def doc_type_token(record: Mapping[str, JsonValue]) -> str | None:
    """Renvoie le premier type de document de la fiche. Un article sans revue (`journal_title`) a le type `article_preprint`."""
    types = [t for entry in as_sequence(record.get("document_type")) if (t := as_str(entry))]
    if not types:
        return None
    if types[0] == "article" and journal_title(record) is None:
        return "article_preprint"
    return types[0]


def publication_date(record: Mapping[str, JsonValue]) -> PublicationDate | None:
    """Renvoie la date de publication de la fiche.

    L'année est celle de la première publication (`publication_info.year`). La date d'impression (`imprints.date`) la précise quand elle a la même année. Sans publication, la date est celle de l'impression, à défaut celle de la prépublication (`preprint_date`), puis la plus ancienne date connue (`earliest_date`).
    """
    year = next((y for info in _publication_infos(record) if (y := as_int(info.get("year")))), None)
    imprint = next(
        (
            d
            for entry in as_sequence(record.get("imprints"))
            if (d := parse_iso_date(as_str(as_mapping(entry).get("date"))))
        ),
        None,
    )
    if year is not None:
        return (
            imprint
            if imprint is not None and imprint.year == year
            else PublicationDate.of_year(year)
        )
    return (
        imprint
        or parse_iso_date(as_str(record.get("preprint_date")))
        or parse_iso_date(as_str(record.get("earliest_date")))
    )


def abstract(record: Mapping[str, JsonValue]) -> str | None:
    """Renvoie le premier résumé de la fiche."""
    for entry in as_sequence(record.get("abstracts")):
        if (text := as_str(as_mapping(entry).get("value"))) and text.strip():
            return text
    return None


def biblio_parts(record: Mapping[str, JsonValue]) -> dict[str, str | None]:
    """Renvoie volume, numéro, pages et numéro d'article de la première publication."""
    infos = _publication_infos(record)
    info = infos[0] if infos else {}
    return {
        "volume": as_text(info.get("journal_volume")),
        "issue": as_text(info.get("journal_issue")),
        "first_page": as_text(info.get("page_start")),
        "last_page": as_text(info.get("page_end")),
        "article_number": as_text(info.get("artid")),
    }
