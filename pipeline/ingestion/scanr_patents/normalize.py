"""Normalisation des familles de brevets ScanR.

Une famille réunit les demandes déposées auprès de plusieurs offices pour une même invention. Sa date de publication est la date de son premier dépôt. Les inventeurs sont des contributions sources de rôle `inventor`, sans adresse.
"""

import re
from collections.abc import Mapping

from domain.contributions.contribution_roles import ContributionRole
from domain.documents.dates import PublicationDate, parse_iso_date
from domain.normalize import normalize_text
from domain.persons.contributor_name import ContributorName
from domain.source_records.identifiers import (
    SourceIdentifier,
    SourceIdentifierRole,
    SourceIdentifierType,
)
from domain.source_records.source_extras import SourceExtra
from domain.types import JsonValue, as_mapping, as_sequence, as_str
from pipeline.ingestion.common.normalizer import Document, SourceNormalizer
from pipeline.ingestion.common.source_contributions import (
    AuthorBlock,
    AuthorRecord,
    contributor_identifiers,
)
from pipeline.ingestion.common.source_records import SourceRecordUpsert
from pipeline.ingestion.common.staging import StagingRow

_KIND_CODE_RE = re.compile(r"(.+?)[A-Z]\d?")
"""Numéro de publication suivi de son code de type : une lettre, parfois un chiffre (`2011107710A1`, `2660236T3`, `102917701A`)."""

_TITLE_LANGUAGES = ("fr", "en")
"""Langues du titre et du résumé, dans l'ordre de préférence."""

_APPLICANT_ID_TYPES = {
    "paysage": "paysage",
    "id_paysage": "paysage",
    "siren": "siren",
    "ror": "ror",
    "idref": "idref",
}
"""Types d'identifiant de déposant gardés, sous leur nom dans `source_extras`. ScanR écrit l'identifiant Paysage sous deux types."""


def _iso_date(value: JsonValue) -> str | None:
    """Renvoie la date ISO d'un horodatage ScanR (`2021-06-09T00:00:00`)."""
    s = as_str(value)
    return s[:10] if s else None


def get_title(family: Mapping[str, JsonValue]) -> tuple[str | None, str | None]:
    """Renvoie le titre de la famille et sa langue : le titre français, à défaut l'anglais, à défaut le titre par défaut, sans langue."""
    titles = as_mapping(family.get("title"))
    for language in _TITLE_LANGUAGES:
        if title := as_str(titles.get(language)):
            return title, language
    return as_str(titles.get("default")), None


def _abstract(family: Mapping[str, JsonValue], language: str | None) -> str | None:
    """Renvoie le résumé dans la langue du titre, à défaut dans une autre langue."""
    summaries = as_mapping(family.get("summary"))
    order = [language] if language else []
    return next(
        (
            s
            for lang in [*order, *_TITLE_LANGUAGES, "default"]
            if (s := as_str(summaries.get(lang)))
        ),
        None,
    )


def get_publication_date(family: Mapping[str, JsonValue]) -> PublicationDate | None:
    """Renvoie la date du premier dépôt de la famille."""
    return parse_iso_date(_iso_date(family.get("applicationDate")))


def _applications(family: Mapping[str, JsonValue]) -> list[Mapping[str, JsonValue]]:
    return [as_mapping(p) for p in as_sequence(family.get("patents"))]


def publication_number(office: str, raw: str | None) -> str | None:
    """Renvoie le numéro de publication préfixé de l'office, sans code de type (`WO` et `2011107710A1` → `WO2011107710`)."""
    number = (raw or "").strip().upper()
    if not number:
        return None
    kind = _KIND_CODE_RE.fullmatch(number)
    return office + (kind.group(1) if kind else number)


def family_identifiers(family: Mapping[str, JsonValue]) -> list[SourceIdentifier]:
    """Renvoie les numéros de publication et de demande de chaque demande de la famille. `normalize_identifiers` retire les doublons."""
    identifiers: list[SourceIdentifier] = []
    for application in _applications(family):
        office = (as_str(application.get("office")) or "").strip().upper()
        if not office:
            continue
        if published := publication_number(office, as_str(application.get("publicationNumber"))):
            identifiers.append(
                SourceIdentifier(
                    SourceIdentifierType.PATENT_PUBLICATION_NUMBER,
                    published,
                    SourceIdentifierRole.SECONDARY,
                )
            )
        if filed := (as_str(application.get("applicationNumber")) or "").strip():
            identifiers.append(
                SourceIdentifier(
                    SourceIdentifierType.PATENT_APPLICATION_NUMBER,
                    office + filed,
                    SourceIdentifierRole.SECONDARY,
                )
            )
    return identifiers


def _application_extra(application: Mapping[str, JsonValue]) -> dict[str, JsonValue]:
    """Renvoie une demande de la famille, pour `source_extras`. Le numéro de publication garde son code de type."""
    return {
        "office": as_str(application.get("office")),
        "application_number": as_str(application.get("applicationNumber")),
        "application_date": _iso_date(application.get("applicationDate")),
        "publication_number": (as_str(application.get("publicationNumber")) or "").strip() or None,
        "publication_date": _iso_date(application.get("publicationDate")),
        "priority": application.get("isPriority") is True,
        "granted": application.get("isGranted") is True,
        "ip_type": as_str(application.get("ipType")),
        "espacenet_url": as_str(application.get("espacenetUrl")),
    }


def _applicant_extra(applicant: Mapping[str, JsonValue]) -> dict[str, JsonValue]:
    """Renvoie un déposant, avec ses identifiants par type, pour `source_extras`."""
    ids: dict[str, list[str]] = {}
    for raw in as_sequence(applicant.get("ids")):
        entry = as_mapping(raw)
        id_type = _APPLICANT_ID_TYPES.get(as_str(entry.get("type")) or "")
        value = as_str(entry.get("id"))
        if id_type and value and value not in ids.setdefault(id_type, []):
            ids[id_type].append(value)
    return {
        "name": as_str(applicant.get("name")),
        "type": as_str(applicant.get("type")),
        "country": as_str(applicant.get("country")),
        "ids": {k: v for k, v in ids.items() if v},
    }


def _cpc(family: Mapping[str, JsonValue]) -> list[dict[str, JsonValue]]:
    """Renvoie les codes CPC de la famille au niveau du groupe, avec leur libellé."""
    groups = [as_mapping(g) for g in as_sequence(as_mapping(family.get("cpc")).get("groupe"))]
    return [
        {"code": code, "label": as_str(g.get("label"))}
        for g in groups
        if (code := as_str(g.get("code")))
    ]


def _source_extras(family: Mapping[str, JsonValue]) -> dict[str, JsonValue] | None:
    extras: dict[str, JsonValue] = {
        SourceExtra.PATENT_APPLICATIONS: [_application_extra(a) for a in _applications(family)],
        SourceExtra.PATENT_APPLICANTS: [
            _applicant_extra(as_mapping(a)) for a in as_sequence(family.get("applicants"))
        ],
        SourceExtra.PATENT_FIRST_PUBLICATION_DATE: _iso_date(family.get("publicationDate")),
        SourceExtra.PATENT_GRANT_DATE: _iso_date(family.get("grantedDate")),
        SourceExtra.CPC: _cpc(family),
    }
    return {k: v for k, v in extras.items() if v} or None


def scanr_patents_source_record(
    family: Mapping[str, JsonValue], staging_id: int, source_id: str
) -> SourceRecordUpsert:
    """Construit l'enregistrement source d'une famille de brevets, sans conteneur."""
    title, language = get_title(family)
    return SourceRecordUpsert(
        source="scanr_patents",
        source_id=source_id,
        staging_id=staging_id,
        identifiers=tuple(family_identifiers(family)),
        title=title or "",
        raw_doc_type=as_str(family.get("productionType")),
        container_title=None,
        raw_language=language,
        abstract=_abstract(family, language),
        source_extras=_source_extras(family),
    )


def _idref(inventor: Mapping[str, JsonValue]) -> str | None:
    """Renvoie l'IdRef d'un inventeur, sans le préfixe `idref` de ScanR."""
    for raw in as_sequence(inventor.get("ids")):
        entry = as_mapping(raw)
        value = as_str(entry.get("id")) or ""
        if as_str(entry.get("type")) == "idref" and value:
            return value.removeprefix("idref")
    return None


def build_inventor_records(block: AuthorBlock) -> list[AuthorRecord]:
    """Lit une contribution source par inventeur, dans l'ordre de première apparition.

    ScanR répète un inventeur à chaque demande de la famille. Les entrées de même nom normalisé n'en font qu'une, avec l'IdRef de l'une d'elles. Deux IdRef distincts sous un même nom font deux inventeurs.
    """
    by_name: dict[str, list[tuple[str, str | None]]] = {}
    for raw in as_sequence(block.get("inventors")):
        inventor = as_mapping(raw)
        if name := as_str(inventor.get("name")):
            by_name.setdefault(normalize_text(name), []).append((name, _idref(inventor)))
    records: list[AuthorRecord] = []
    for entries in by_name.values():
        idrefs = list(dict.fromkeys(idref for _, idref in entries if idref))
        if len(idrefs) > 1:
            inventors = [(next(n for n, i in entries if i == idref), idref) for idref in idrefs]
        else:
            inventors = [(entries[0][0], idrefs[0] if idrefs else None)]
        for name, idref in inventors:
            contributor_name = ContributorName.from_raw(name)
            if contributor_name is None:
                continue
            records.append(
                AuthorRecord(
                    position=len(records) + 1,
                    name=contributor_name,
                    roles=[ContributionRole.INVENTOR],
                    identifiers=contributor_identifiers(idref=idref),
                )
            )
    return records


class ScanrPatentsNormalizer(SourceNormalizer):
    SOURCE = "scanr_patents"

    def minimal_metadata(self, doc: Document) -> tuple[str | None, int | None]:
        publication_date = get_publication_date(doc)
        return get_title(doc)[0], publication_date.year if publication_date else None

    def source_record(
        self, row: StagingRow, doc: Document, *, has_series: bool
    ) -> SourceRecordUpsert:
        """Construit l'enregistrement source de la famille, sans éditeur ni conteneur."""
        return scanr_patents_source_record(doc, row.id, row.source_id)

    def publication_date(self, doc: Document) -> PublicationDate | None:
        return get_publication_date(doc)

    def author_block(self, doc: Document) -> AuthorBlock:
        return {"inventors": doc.get("inventors")}

    def author_records(self, block: AuthorBlock) -> list[AuthorRecord]:
        return build_inventor_records(block)
