"""Conteneurs d'un document : son entrée de `journals`, et la monographie qui le contient."""

from typing import NamedTuple

from application.ports.pipeline.containers import ContainerFindOrCreateQueries
from application.services.journals.core import find_or_create_journal
from application.services.monographs.core import find_or_create_monograph
from domain.journals.containers import (
    ContainerDescription,
    container_is_journal,
    determine_container_type,
)
from domain.normalize import normalize_text, to_plain_text


class Containers(NamedTuple):
    """Entrée de `journals` et monographie d'un document."""

    journal_id: int | None
    monograph_id: int | None


def _find_journal(
    facts: ContainerDescription, publisher_id: int | None, repo: ContainerFindOrCreateQueries
) -> int | None:
    """Entrée de `journals` du document : revue, collection, ou recueil d'actes. Un livre ou un chapitre sans ISSN, qui ne déclare pas de congrès, rejoint seulement un recueil d'actes existant de même titre."""
    has_issn = bool(facts.issn or facts.eissn or facts.issnl)
    if container_is_journal(
        facts.raw_doc_type,
        facts.source,
        has_issn=has_issn,
        declares_conference=facts.declares_conference,
    ):
        return find_or_create_journal(
            facts.journal_title,
            issn=facts.issn,
            eissn=facts.eissn,
            issnl=facts.issnl,
            publisher_id=publisher_id,
            openalex_id=facts.openalex_id,
            oa_model=facts.oa_model,
            repo=repo,
        )
    title_normalized = (
        normalize_text(to_plain_text(facts.journal_title)) if facts.journal_title else ""
    )
    if not title_normalized:
        return None
    return repo.find_proceedings_by_name_form(title_normalized, publisher_id)


def find_or_create_containers(
    description: ContainerDescription,
    *,
    publisher_id: int | None,
    repo: ContainerFindOrCreateQueries,
) -> Containers:
    """Trouve ou crée les conteneurs d'un document.

    Le document reçoit son entrée de `journals` : revue, collection, ou recueil d'actes. Son volume (`determine_container_type`) devient sa monographie, que son `journal_id` relie à cette même entrée.
    """
    journal_id = _find_journal(description, publisher_id, repo)
    _, volume = determine_container_type(description)
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
