"""Conteneurs d'un document : la revue où il paraît, ou la monographie qui le contient et la collection de cette monographie."""

from dataclasses import dataclass
from typing import NamedTuple

from application.ports.pipeline.containers import ContainerFindOrCreateQueries
from application.services.journals.core import find_or_create_journal
from application.services.monographs.core import find_or_create_monograph
from domain.journals.containers import ContainerRole, container_role, is_conference
from domain.journals.journal import OaModel
from domain.normalize import normalize_text, to_plain_text
from domain.publications.identifiers import ISSN


@dataclass(frozen=True, slots=True, kw_only=True)
class ContainerFacts:
    """Ce qu'une source dit du conteneur d'un document.

    `journal_title` est la revue d'un article. Pour un livre, un chapitre ou un article de congrès, `collection_title` nomme la collection et `book_title` le livre ou le volume d'actes qui contient le document ; un livre porte son propre titre, `document_title`. Les ISSN sont ceux de la revue ou de la collection.
    """

    source: str
    raw_doc_type: str | None
    declares_conference: bool = False
    document_title: str | None = None
    journal_title: str | None = None
    collection_title: str | None = None
    book_title: str | None = None
    issn: str | None = None
    eissn: str | None = None
    issnl: str | None = None
    openalex_id: str | None = None
    oa_model: OaModel | None = None
    isbns: tuple[str, ...] = ()
    eisbns: tuple[str, ...] = ()
    year: int | None = None


class Containers(NamedTuple):
    """Revue ou collection, et monographie, d'un document."""

    journal_id: int | None
    monograph_id: int | None


def _find_collection(
    facts: ContainerFacts, publisher_id: int | None, repo: ContainerFindOrCreateQueries
) -> int | None:
    """Collection désignée par un ISSN. Sans titre de collection, elle est seulement cherchée par ISSN."""
    issns = [facts.issn, facts.eissn, facts.issnl]
    if not any(issns):
        return None
    if facts.collection_title:
        return find_or_create_journal(
            facts.collection_title,
            issn=facts.issn,
            eissn=facts.eissn,
            issnl=facts.issnl,
            publisher_id=publisher_id,
            openalex_id=facts.openalex_id,
            oa_model=facts.oa_model,
            repo=repo,
        )
    for value in issns:
        if (issn := ISSN.try_parse(value)) and (found := repo.find_journal_by_issn_any(str(issn))):
            return found
    return None


def _same_title(first: str | None, second: str | None) -> bool:
    return bool(first and second) and normalize_text(to_plain_text(first or "")) == normalize_text(
        to_plain_text(second or "")
    )


def find_or_create_containers(
    facts: ContainerFacts, *, publisher_id: int | None, repo: ContainerFindOrCreateQueries
) -> Containers:
    """Trouve ou crée les conteneurs d'un document.

    Un article reçoit sa revue. Un livre, un chapitre ou un article de congrès reçoit sa monographie, et la collection de celle-ci quand un ISSN la désigne. Un titre de livre identique à celui de la collection désigne la collection seule : c'est le cas d'un article de congrès paru dans une revue.
    """
    role = container_role(
        facts.raw_doc_type, facts.source, declares_conference=facts.declares_conference
    )
    if role is ContainerRole.JOURNAL:
        journal_id = find_or_create_journal(
            facts.journal_title,
            issn=facts.issn,
            eissn=facts.eissn,
            issnl=facts.issnl,
            publisher_id=publisher_id,
            openalex_id=facts.openalex_id,
            oa_model=facts.oa_model,
            repo=repo,
        )
        return Containers(journal_id, None)

    journal_id = _find_collection(facts, publisher_id, repo)
    title = facts.document_title if role is ContainerRole.BOOK else facts.book_title
    if _same_title(title, facts.collection_title):
        return Containers(journal_id, None)
    monograph_id = find_or_create_monograph(
        title,
        isbns=facts.isbns,
        eisbns=facts.eisbns,
        proceedings=is_conference(
            facts.raw_doc_type, facts.source, declares_conference=facts.declares_conference
        ),
        year=facts.year,
        publisher_id=publisher_id,
        journal_id=journal_id,
        repo=repo,
    )
    return Containers(journal_id, monograph_id)
