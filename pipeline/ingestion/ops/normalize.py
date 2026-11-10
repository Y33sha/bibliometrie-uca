"""Normalisation des familles de brevets OPS.

Une famille INPADOC réunit les demandes déposées auprès de plusieurs offices pour une même invention, liées par leurs priorités. Sa date de publication est la date de sa priorité la plus ancienne. Les inventeurs sont des contributions sources de rôle `inventor`, sans adresse ni identifiant.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date

from domain.contributions.contribution_roles import ContributionRole
from domain.documents.dates import PublicationDate, parse_iso_date
from domain.persons.contributor_name import ContributorName
from domain.platforms.registry import espacenet_url
from domain.source_records.identifiers import (
    SourceIdentifier,
    SourceIdentifierRole,
    SourceIdentifierType,
)
from domain.source_records.source_extras import SourceExtra
from domain.types import JsonValue, as_mapping, as_sequence, as_str
from pipeline.ingestion.common.locations import LocationFacts
from pipeline.ingestion.common.normalizer import Document, SourceNormalizer
from pipeline.ingestion.common.source_contributions import AuthorBlock, AuthorRecord
from pipeline.ingestion.common.source_records import SourceRecordUpsert
from pipeline.ingestion.common.staging import StagingRow
from pipeline.ingestion.ops.family import (
    DocId,
    Member,
    Party,
    Text,
    applicant_forms,
    display_names,
    family_members,
    filings,
    first_priority,
    publications,
)

_LANGUAGES = ("fr", "en")
"""Langues du titre et du résumé, dans l'ordre de préférence."""


def members_of(doc: Mapping[str, JsonValue]) -> list[Member]:
    return family_members(as_mapping(doc.get("family")))


def _preferred(texts: list[Text], language: str | None = None) -> tuple[str | None, str | None]:
    """Renvoie le texte dans la langue demandée, à défaut en français, en anglais, puis dans une autre langue."""
    order = [language] if language else []
    for lang in [*order, *_LANGUAGES]:
        if found := next((t.value for t in texts if t.lang == lang), None):
            return found, lang
    return (texts[0].value, texts[0].lang) if texts else (None, None)


def get_title(members: list[Member]) -> tuple[str | None, str | None]:
    """Renvoie le titre de la famille et sa langue."""
    return _preferred([t for m in members for t in m.titles])


def get_publication_date(members: list[Member]) -> PublicationDate | None:
    """Renvoie la date de la priorité la plus ancienne de la famille."""
    priority = first_priority(members)
    return parse_iso_date(priority.date.isoformat()) if priority and priority.date else None


def family_identifiers(members: list[Member]) -> list[SourceIdentifier]:
    """Renvoie les numéros de publication et de demande de la famille, priorités comprises. `normalize_identifiers` retire les doublons."""
    return [
        SourceIdentifier(
            SourceIdentifierType.PATENT_PUBLICATION_NUMBER,
            d.identifier,
            SourceIdentifierRole.SECONDARY,
        )
        for d in publications(members)
    ] + [
        SourceIdentifier(
            SourceIdentifierType.PATENT_APPLICATION_NUMBER,
            d.identifier,
            SourceIdentifierRole.SECONDARY,
        )
        for d in filings(members)
    ]


def _iso(d: DocId | None) -> str | None:
    return d.date.isoformat() if d and d.date else None


def _applications(members: list[Member]) -> list[dict[str, JsonValue]]:
    """Renvoie les demandes de la famille, chacune avec sa première publication, pour `source_extras`. Une priorité jamais publiée figure sans publication."""
    priorities = {p.identifier for m in members for p in m.priorities}
    by_application: dict[str, list[Member]] = {}
    for m in members:
        if m.application:
            by_application.setdefault(m.application.identifier, []).append(m)
    out: list[dict[str, JsonValue]] = []
    for number, group in by_application.items():
        application = group[0].application
        assert application is not None
        published = sorted(
            (m.publication for m in group if m.publication), key=lambda d: (d.date is None, d.date)
        )
        first = next((d for d in published if not d.is_grant), published[0] if published else None)
        out.append(
            {
                "office": first.country if first else application.country,
                "application_number": application.number,
                "application_date": _iso(application),
                "publication_number": f"{first.number}{first.kind or ''}" if first else None,
                "publication_date": _iso(first),
                "priority": number in priorities,
                "granted": any(d.is_grant for d in published),
            }
        )
    unpublished = {p.identifier: p for m in members for p in m.priorities}
    out.extend(
        {
            "office": "WO" if p.is_international_application else p.country,
            "application_number": p.number,
            "application_date": _iso(p),
            "publication_number": None,
            "publication_date": None,
            "priority": True,
            "granted": False,
        }
        for number, p in unpublished.items()
        if number not in by_application
    )
    return out


def espacenet_locations(members: list[Member]) -> list[LocationFacts]:
    """Renvoie la copie Espacenet de la famille : la première publication de la demande prioritaire, à défaut la première publication de la famille."""
    priorities = {p.identifier for m in members for p in m.priorities}
    candidates = [
        m.publication
        for m in members
        if m.publication and m.application and m.application.identifier in priorities
    ]
    candidates = candidates or publications(members)
    if not candidates:
        return []
    first = min(candidates, key=lambda d: (d.date is None, d.date, d.is_grant))
    return [
        LocationFacts(
            url=espacenet_url(first.country, f"{first.number}{first.kind or ''}"),
            version="publishedVersion",
            is_oa=True,
        )
    ]


def _source_extras(members: list[Member]) -> dict[str, JsonValue] | None:
    applicants = [p for m in members for p in m.applicants]
    published = sorted(
        (d for d in publications(members) if d.date), key=lambda d: d.date or date.min
    )
    granted = [d for d in published if d.is_grant]
    extras: dict[str, JsonValue] = {
        SourceExtra.PATENT_APPLICATIONS: _applications(members),
        SourceExtra.PATENT_APPLICANTS: [{"name": name} for name in display_names(applicants)],
        SourceExtra.PATENT_APPLICANT_FORMS: applicant_forms(members),
        SourceExtra.PATENT_FIRST_PUBLICATION_DATE: _iso(published[0]) if published else None,
        SourceExtra.PATENT_GRANT_DATE: _iso(granted[0]) if granted else None,
        SourceExtra.CPC: [{"code": c} for c in dict.fromkeys(c for m in members for c in m.cpc)],
    }
    return {k: v for k, v in extras.items() if v} or None


def ops_source_record(
    doc: Mapping[str, JsonValue], staging_id: int, source_id: str
) -> SourceRecordUpsert:
    """Construit l'enregistrement source d'une famille de brevets, sans conteneur."""
    members = members_of(doc)
    title, language = get_title(members)
    abstract, _ = _preferred([t for m in members for t in m.abstracts], language)
    return SourceRecordUpsert(
        source="ops",
        source_id=source_id,
        staging_id=staging_id,
        identifiers=tuple(family_identifiers(members)),
        title=title or "",
        raw_doc_type="patent",
        container_title=None,
        raw_language=language,
        abstract=abstract,
        source_extras=_source_extras(members),
    )


def build_inventor_records(block: AuthorBlock) -> list[AuthorRecord]:
    """Lit une contribution source par inventeur, dans l'ordre de première apparition. OPS répète un inventeur à chaque membre de la famille et sous deux formats : les noms de même forme de comparaison n'en font qu'un."""
    parties = [
        Party(as_str(p.get("name")) or "", p.get("original") is True)
        for raw in as_sequence(block.get("inventors"))
        if (p := as_mapping(raw))
    ]
    records: list[AuthorRecord] = []
    for name in display_names(parties):
        if (contributor_name := ContributorName.from_raw(name)) is not None:
            records.append(
                AuthorRecord(
                    position=len(records) + 1,
                    name=contributor_name,
                    roles=[ContributionRole.INVENTOR],
                )
            )
    return records


class OpsNormalizer(SourceNormalizer):
    SOURCE = "ops"

    def minimal_metadata(self, doc: Document) -> tuple[str | None, int | None]:
        members = members_of(doc)
        publication_date = get_publication_date(members)
        return get_title(members)[0], publication_date.year if publication_date else None

    def source_record(
        self, row: StagingRow, doc: Document, *, has_series: bool
    ) -> SourceRecordUpsert:
        """Construit l'enregistrement source de la famille, sans éditeur ni conteneur."""
        return ops_source_record(doc, row.id, row.source_id)

    def publication_date(self, doc: Document) -> PublicationDate | None:
        return get_publication_date(members_of(doc))

    def locations(self, doc: Document) -> list[LocationFacts]:
        return espacenet_locations(members_of(doc))

    def author_block(self, doc: Document) -> AuthorBlock:
        return {
            "inventors": [
                {"name": p.name, "original": p.original}
                for m in members_of(doc)
                for p in m.inventors
            ]
        }

    def author_records(self, block: AuthorBlock) -> list[AuthorRecord]:
        return build_inventor_records(block)
