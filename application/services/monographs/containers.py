"""Conteneurs d'un document : son entrée de `journals`, et la monographie qui le contient."""

from typing import NamedTuple

from application.ports.pipeline.containers import ContainerFindOrCreateQueries
from application.services.journals.core import find_or_create_journal
from application.services.monographs.core import find_or_create_monograph
from domain.journals.containers import (
    ContainerDescription,
    SeriesDescription,
    determine_container_type,
)


class Containers(NamedTuple):
    """Entrée de `journals` et monographie d'un document."""

    journal_id: int | None
    monograph_id: int | None


def _find_series(
    series: SeriesDescription, publisher_id: int | None, repo: ContainerFindOrCreateQueries
) -> int | None:
    """Entrée de `journals` d'une série. Une série sans titre est seulement cherchée par ses ISSN, rejetés compris."""
    if series.title:
        return find_or_create_journal(
            series.title,
            issn=series.issn,
            eissn=series.eissn,
            issnl=series.issnl,
            publisher_id=publisher_id,
            openalex_id=series.openalex_id,
            oa_model=series.oa_model,
            rejected_issns=series.rejected_issns,
            repo=repo,
        )
    for value in (series.issn, series.eissn, series.issnl, *series.rejected_issns):
        if value and (journal_id := repo.find_journal_by_issn_any(value)):
            return journal_id
    return None


def find_or_create_containers(
    description: ContainerDescription,
    *,
    publisher_id: int | None,
    repo: ContainerFindOrCreateQueries,
) -> Containers:
    """Trouve ou crée les conteneurs d'un document, d'après `determine_container_type`.

    Le document reçoit sa série comme entrée de `journals`, et son volume comme monographie, reliée à cette série. La série d'un volume porte toujours un ISSN. L'étape de rattachement de `publishers_journals` reconnaît les séries sans ISSN.
    """
    series, volume = determine_container_type(description)
    journal_id = _find_series(series, publisher_id, repo) if series else None
    if volume is None:
        return Containers(journal_id, None)
    monograph_id = find_or_create_monograph(
        volume.title,
        isbns=volume.isbns,
        eisbns=volume.eisbns,
        proceedings=volume.proceedings,
        year=volume.year,
        publisher_id=publisher_id,
        journal_id=journal_id,
        repo=repo,
    )
    return Containers(journal_id, monograph_id)
