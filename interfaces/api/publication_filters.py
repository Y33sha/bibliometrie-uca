"""Filtres des publications lus dans la query string, injectés par `Depends()`.

La liste des publications, ses facettes, son export et les statistiques lisent ces paramètres.
"""

from dataclasses import dataclass, replace
from typing import Annotated

from fastapi import Depends, Query

from domain.documents.doc_types import DocType
from domain.publications.hal_deposit import HalDepositStatus
from domain.publications.oa_status import ACCESS_LEVELS, OaStatus
from domain.source_records.impact import CitationTop
from infrastructure.read_models.publications.models import (
    AUTHOR_POSITION_FILTER_VALUES,
    DOI_AGENCY_FILTER_VALUES,
    LICENSE_FILTER_VALUES,
    SOURCE_FILTER_VALUES,
    PublicationFilters,
)
from interfaces.api.filters import (
    TOGGLE_VALUES,
    parse_int_csv,
    parse_lab_id,
    parse_ror_csv,
    parse_str_csv,
    parse_vocabulary_csv,
)
from interfaces.api.params import SearchTerm


@dataclass(frozen=True, slots=True)
class PublicationFilterParams:
    """Filtres communs à la liste des publications et aux statistiques.

    Les valeurs multiples se séparent par des virgules. `lab_id` accepte la sentinelle `none`, qui retient les publications sans laboratoire, et se combine aux identifiants.
    """

    search: SearchTerm = ""
    lab_id: Annotated[str, Query()] = ""
    year: Annotated[str, Query()] = ""
    publisher_id: Annotated[int | None, Query()] = None
    serial_id: Annotated[int | None, Query()] = None
    monograph_id: Annotated[int | None, Query()] = None
    person_id: Annotated[int | None, Query()] = None
    author_id: Annotated[int | None, Query()] = None
    subject: Annotated[str, Query(description="Libellés normalisés des sujets")] = ""
    access: Annotated[str, Query()] = ""
    oa_status: Annotated[str, Query()] = ""
    license: Annotated[str, Query()] = ""
    doi_agency: Annotated[str, Query()] = ""
    source_filter: Annotated[str, Query()] = ""
    doc_type: Annotated[str, Query()] = ""
    excluded_doc_type: Annotated[str, Query()] = ""
    has_apc: Annotated[str, Query()] = ""
    citation_top: Annotated[str, Query()] = ""
    country: Annotated[str, Query()] = ""
    language: Annotated[str, Query()] = ""
    partner_ror: Annotated[str, Query()] = ""

    def to_filters(self) -> PublicationFilters:
        """Traduit la query string en filtres de la lecture."""
        lab_ids, lab_none = parse_lab_id(self.lab_id)
        return PublicationFilters(
            search=self.search,
            lab_ids=lab_ids,
            lab_none=lab_none,
            years=parse_int_csv(self.year, param="year"),
            publisher_id=self.publisher_id,
            serial_id=self.serial_id,
            monograph_id=self.monograph_id,
            person_id=self.person_id,
            author_id=self.author_id,
            subject_labels=parse_str_csv(self.subject),
            access=parse_vocabulary_csv(self.access, allowed=ACCESS_LEVELS, param="access"),
            oa_status=parse_vocabulary_csv(self.oa_status, allowed=OaStatus, param="oa_status"),
            license=parse_vocabulary_csv(
                self.license, allowed=LICENSE_FILTER_VALUES, param="license"
            ),
            doi_agency=parse_vocabulary_csv(
                self.doi_agency, allowed=DOI_AGENCY_FILTER_VALUES, param="doi_agency"
            ),
            source_values=parse_vocabulary_csv(
                self.source_filter, allowed=SOURCE_FILTER_VALUES, param="source_filter"
            ),
            doc_types=parse_vocabulary_csv(self.doc_type, allowed=DocType, param="doc_type"),
            excluded_types=parse_vocabulary_csv(
                self.excluded_doc_type, allowed=DocType, param="excluded_doc_type"
            ),
            has_apc=parse_vocabulary_csv(self.has_apc, allowed=TOGGLE_VALUES, param="has_apc"),
            citation_tops=parse_vocabulary_csv(
                self.citation_top, allowed=frozenset(CitationTop), param="citation_top"
            ),
            country_values=parse_str_csv(self.country),
            language_codes=parse_str_csv(self.language),
            partner_rors=parse_ror_csv(self.partner_ror, param="partner_ror"),
        )


@dataclass(frozen=True, slots=True)
class PublicationListFilterParams(PublicationFilterParams):
    """Filtres de la liste des publications : les filtres communs, plus ceux qui supposent un seul laboratoire (statut HAL), une personne (périmètre), ou l'un ou l'autre (position d'auteur)."""

    author_position: Annotated[str, Query()] = ""
    hal_status: Annotated[str, Query()] = ""
    in_perimeter: Annotated[str, Query()] = ""

    def to_filters(self) -> PublicationFilters:
        """Traduit la query string en filtres de la lecture."""
        return replace(
            PublicationFilterParams.to_filters(self),
            author_position=parse_vocabulary_csv(
                self.author_position, allowed=AUTHOR_POSITION_FILTER_VALUES, param="author_position"
            ),
            hal_status_values=parse_vocabulary_csv(
                self.hal_status, allowed=frozenset(HalDepositStatus), param="hal_status"
            ),
            in_perimeter=parse_vocabulary_csv(
                self.in_perimeter, allowed=TOGGLE_VALUES, param="in_perimeter"
            ),
        )


StatsFilters = Annotated[PublicationFilterParams, Depends()]
ListFilters = Annotated[PublicationListFilterParams, Depends()]
