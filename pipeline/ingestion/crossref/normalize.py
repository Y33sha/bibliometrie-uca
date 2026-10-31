"""Normalisation des enregistrements sources Crossref.

- Le type brut est le `type` Crossref, suivi du sous-type quand Crossref en donne un (`crossref_raw_doc_type`). `arbitrate_doc_type_with_article_subtype` arbitre ensuite un `journal-article` contre les sous-types plus précis des autres sources (`ARTICLE_SUBTYPES`).
- Le statut open access de Crossref est peu fiable : il reste vide, et le statut vient des autres sources (`refresh_from_sources`).
"""

from __future__ import annotations

from collections.abc import Mapping

from domain.dates import today
from domain.normalize import drop_flattened_mathml
from domain.persons.contributor_name import ContributorName
from domain.publications.contribution_roles import ContributionRole
from domain.publications.identifiers import clean_doi
from domain.publications.licenses import crossref_license
from domain.serials.containers import ContainerDescription, ContainerRole, container_role
from domain.serials.series import split_collection_and_volume
from domain.source_records.biblio import PageRange, compact_biblio, parse_pages
from domain.source_records.identifiers import (
    SourceIdentifier,
    SourceIdentifierRole,
    SourceIdentifierType,
    isbn_role,
)
from domain.source_records.impact import Impact
from domain.structures.identifiers import RorId, parse_ror_ids
from domain.types import JsonValue, as_mapping, as_sequence, as_str, as_text
from pipeline.ingestion.common.locations import LocationFacts
from pipeline.ingestion.common.normalizer import Document, PublisherFacts, SourceNormalizer
from pipeline.ingestion.common.source_contributions import (
    AddressRecord,
    AuthorBlock,
    AuthorRecord,
    contributor_identifiers,
)
from pipeline.ingestion.common.source_records import (
    SourceRecordUpsert,
)
from pipeline.ingestion.common.staging import StagingRow
from pipeline.ingestion.crossref.payload import (
    crossref_issns,
    crossref_raw_doc_type,
    extract_crossref_conference,
    extract_crossref_publication_year,
    extract_crossref_source_extras,
    parse_crossref_issns,
    strip_jats_tags,
)
from pipeline.transformation.publishing.find_or_create import (
    Containers,
)


def get_doi(msg: Mapping[str, JsonValue]) -> str | None:
    """Renvoie le DOI normalisé ; Crossref le donne tel que déposé."""
    return clean_doi(as_str(msg.get("DOI")))


def get_title(msg: Mapping[str, JsonValue]) -> str | None:
    """Renvoie le premier titre du payload, nettoyé par `drop_flattened_mathml`."""
    titles = msg.get("title") or []
    first = titles[0] if isinstance(titles, list) and titles else titles
    if isinstance(first, str) and (title := drop_flattened_mathml(first)):
        return title
    return None


def get_publication_year(msg: Mapping[str, JsonValue]) -> int | None:
    return extract_crossref_publication_year(msg, max_year=today().year + 1)


def get_container_title(msg: Mapping[str, JsonValue]) -> str | None:
    cts = msg.get("container-title") or []
    if isinstance(cts, list) and cts:
        first = cts[0]
        if isinstance(first, str) and first.strip():
            return first.strip()
    if isinstance(cts, str) and cts.strip():
        return cts.strip()
    return None


def get_issns(msg: Mapping[str, JsonValue]) -> tuple[str | None, str | None]:
    return parse_crossref_issns(msg)


def get_publisher_name(msg: Mapping[str, JsonValue]) -> str | None:
    p = msg.get("publisher")
    if isinstance(p, str) and p.strip():
        return p.strip()
    return None


def get_keywords(msg: Mapping[str, JsonValue]) -> list[str] | None:
    subjects = msg.get("subject") or []
    if not isinstance(subjects, list):
        return None
    cleaned = [s.strip() for s in subjects if isinstance(s, str) and s.strip()]
    return cleaned or None


def get_abstract(msg: Mapping[str, JsonValue]) -> str | None:
    abstract = msg.get("abstract")
    if not isinstance(abstract, str) or not abstract.strip():
        return None
    cleaned = strip_jats_tags(abstract).strip()
    return cleaned or None


def get_cited_by_count(msg: Mapping[str, JsonValue]) -> int | None:
    val = msg.get("is-referenced-by-count")
    return val if isinstance(val, int) else None


def get_language(msg: Mapping[str, JsonValue]) -> str | None:
    lang = msg.get("language")
    if isinstance(lang, str) and lang.strip():
        return lang.strip().lower()
    return None


def get_isbns(msg: Mapping[str, JsonValue]) -> tuple[list[str], list[str]]:
    """Renvoie les ISBN imprimés ou sans support déclaré, puis les ISBN électroniques. `isbn-type` donne le support de chaque ISBN."""
    electronic = {
        value
        for entry in as_sequence(msg.get("isbn-type"))
        if (value := as_str(as_mapping(entry).get("value")))
        and as_str(as_mapping(entry).get("type")) == "electronic"
    }
    isbns = [s for s in as_sequence(msg.get("ISBN")) if isinstance(s, str)]
    return [s for s in isbns if s not in electronic], [s for s in isbns if s in electronic]


def crossref_identifiers(msg: Mapping[str, JsonValue], doi: str) -> tuple[SourceIdentifier, ...]:
    """Renvoie les identifiants d'une œuvre Crossref. Le DOI est primaire, le rôle des ISBN suit le type de l'œuvre (`isbn_role`)."""
    role = isbn_role(
        crossref_raw_doc_type(msg),
        "crossref",
        declares_conference=extract_crossref_conference(msg) is not None,
    )
    isbns, eisbns = get_isbns(msg)
    return (
        SourceIdentifier(SourceIdentifierType.DOI, doi, SourceIdentifierRole.PRIMARY),
        *(SourceIdentifier(SourceIdentifierType.ISBN, isbn, role) for isbn in isbns),
        *(SourceIdentifier(SourceIdentifierType.EISBN, isbn, role) for isbn in eisbns),
    )


def page_range(page: str | None, article_number: str | None) -> PageRange:
    """Renvoie la pagination Crossref (`page`). Une page seule égale au numéro d'article est écartée."""
    pages = parse_pages(page)
    if pages.last_page is None and pages.first_page == article_number:
        return PageRange()
    return pages


def get_biblio(msg: Mapping[str, JsonValue]) -> dict[str, JsonValue] | None:
    """Renvoie volume, numéro, pages et numéro d'article, avec l'éditeur et la revue nommés par Crossref."""
    issn_val, eissn_val = get_issns(msg)
    article_number = as_text(msg.get("article-number"))
    return compact_biblio(
        volume=as_text(msg.get("volume")),
        issue=as_text(msg.get("issue")),
        **page_range(as_text(msg.get("page")), article_number)._asdict(),
        article_number=article_number,
        publisher=get_publisher_name(msg),
        journal_title=get_container_title(msg),
        journal_issn=issn_val,
        journal_eissn=eissn_val,
    )


def _container_titles(msg: Mapping[str, JsonValue]) -> list[str]:
    cts = msg.get("container-title")
    values = cts if isinstance(cts, list) else [cts]
    return [v.strip() for v in values if isinstance(v, str) and v.strip()]


def get_container_facts(msg: Mapping[str, JsonValue]) -> ContainerDescription:
    """Décrit le conteneur d'un document d'après Crossref.

    Un livre donne sa collection dans `container-title`. Pour un chapitre ou un article de congrès, `container-title` donne la collection et le livre ou le volume d'actes (`split_collection_and_volume`), ou le seul livre, ou la seule collection quand un ISSN la désigne. Sous une collection seule, le volume d'actes prend le nom du congrès.
    """
    raw_type = crossref_raw_doc_type(msg)
    conference = extract_crossref_conference(msg)
    titles = _container_titles(msg)
    issns = crossref_issns(msg)
    isbns, eisbns = get_isbns(msg)
    role = container_role(raw_type, "crossref", declares_conference=conference is not None)
    collection_title = book_title = None
    if role is ContainerRole.BOOK:
        collection_title = titles[0] if titles else None
    elif role is ContainerRole.PART:
        if len(titles) >= 2:
            collection_title, book_title = split_collection_and_volume(titles[0], titles[-1])
        elif titles and issns:
            collection_title = titles[0]
            book_title = as_str(conference.get("name")) if conference else None
        elif titles:
            book_title = titles[0]
    return ContainerDescription(
        source="crossref",
        raw_doc_type=raw_type,
        declares_conference=conference is not None,
        document_title=get_title(msg),
        journal_title=titles[0] if titles else None,
        collection_title=collection_title,
        book_title=book_title,
        issns=issns,
        isbns=tuple(isbns),
        eisbns=tuple(eisbns),
        year=get_publication_year(msg),
    )


def _author_name(author: Mapping[str, JsonValue]) -> ContributorName | None:
    return ContributorName.from_parts(as_str(author.get("family")), as_str(author.get("given")))


def _author_affiliations(
    author: Mapping[str, JsonValue],
) -> tuple[list[AddressRecord], frozenset[RorId]]:
    """Renvoie les adresses des affiliations à nom, chacune avec ses ROR (`id` de type `ROR`), et ROR des affiliations sans nom."""
    addresses: list[AddressRecord] = []
    without_name: set[RorId] = set()
    for aff in (as_mapping(a) for a in as_sequence(author.get("affiliation"))):
        rors = parse_ror_ids(
            as_str(ident.get("id"))
            for ident in (as_mapping(i) for i in as_sequence(aff.get("id")))
            if ident.get("id-type") == "ROR"
        )
        if (name := as_str(aff.get("name"))) and name.strip():
            addresses.append(AddressRecord(text=name.strip(), ror_ids=rors))
        else:
            without_name |= rors
    return addresses, frozenset(without_name)


def build_crossref_author_records(msg: Mapping[str, JsonValue]) -> list[AuthorRecord]:
    """Lit les contributions sources d'un message Crossref.

    - Le nom et le prénom sont séparés (`family`, `given`) ; une entrée au seul `name` est collective.
    - L'ORCID est le seul identifiant exploitable.
    - Les affiliations deviennent des adresses sans pays, rattachées aux structures par la phase `affiliations`.
    - Les ROR d'une affiliation vont sur son adresse, ou sur la contribution source pour une affiliation sans nom.
    - Le rôle est toujours `author` : Crossref ne distingue pas les rôles.
    """
    authors = msg.get("author") or []
    if not isinstance(authors, list):
        return []

    ids_by_position = [
        contributor_identifiers(orcid=as_str(a.get("ORCID"))) if isinstance(a, dict) else None
        for a in authors
    ]

    records: list[AuthorRecord] = []
    for position, author in enumerate(authors):
        if not isinstance(author, dict):
            continue

        name = _author_name(author)
        collective = name is None
        if name is None:
            name = ContributorName.from_raw(as_str(author.get("name")))
        if name is None:
            continue

        ids = ids_by_position[position]
        addresses, source_contribution_rors = _author_affiliations(author)
        records.append(
            AuthorRecord(
                position=position,
                name=name,
                collective=collective,
                roles=[ContributionRole.AUTHOR],
                identifiers=ids if ids else None,
                addresses=addresses,
                ror_ids=source_contribution_rors,
            )
        )
    return records


def extract_crossref_author_block(msg: Mapping[str, JsonValue]) -> AuthorBlock:
    """Renvoie le bloc auteurs d'un message Crossref : `author`."""
    return {"author": msg.get("author")}


def get_locations(msg: Mapping[str, JsonValue]) -> list[LocationFacts]:
    """Renvoie la page de résolution du DOI (`resource.primary.URL`), avec la licence de la version éditeur.

    Les URL de `link` mènent à des points d'accès pour la fouille de texte : elles restent hors des localisations.
    """
    url = as_str(as_mapping(as_mapping(msg.get("resource")).get("primary")).get("URL"))
    return [LocationFacts(url=url, license=crossref_license(msg.get("license")))] if url else []


def crossref_source_record(
    msg: Mapping[str, JsonValue], staging_id: int, containers: Containers
) -> SourceRecordUpsert:
    """Construit l'enregistrement source Crossref d'une œuvre, identifiée par son DOI."""
    doi = get_doi(msg)
    title = get_title(msg)
    publication_year = get_publication_year(msg)
    # Garanti par `SourceNormalizer` : l'œuvre a un DOI, un titre et une année.
    assert doi and isinstance(title, str) and isinstance(publication_year, int)
    return SourceRecordUpsert(
        source="crossref",
        source_id=doi,
        staging_id=staging_id,
        identifiers=crossref_identifiers(msg, doi),
        title=title,
        publication_year=publication_year,
        raw_doc_type=crossref_raw_doc_type(msg),
        serial_id=containers.serial_id,
        monograph_id=containers.monograph_id,
        container_title=get_container_title(msg) if not containers.serial_id else None,
        raw_language=get_language(msg),
        biblio=get_biblio(msg),
        abstract=get_abstract(msg),
        keywords=get_keywords(msg),
        license=crossref_license(msg.get("license")),
        impact=Impact(cited_by_count=get_cited_by_count(msg)).to_json(),
        source_extras=extract_crossref_source_extras(msg),
    )


class CrossrefNormalizer(SourceNormalizer):
    SOURCE = "crossref"
    DEFAULT_BATCH_SIZE = 100

    def minimal_metadata(self, row: StagingRow) -> tuple[str | None, int | None]:
        return get_title(row.raw_data), get_publication_year(row.raw_data)

    def parse(self, row: StagingRow) -> Document | None:
        """Renvoie le `message` de l'œuvre, ou `None` sans DOI."""
        return row.raw_data if get_doi(row.raw_data) else None

    def publisher(self, doc: Document) -> PublisherFacts | None:
        name = get_publisher_name(doc)
        return PublisherFacts(name) if name else None

    def container_facts(self, doc: Document) -> ContainerDescription:
        return get_container_facts(doc)

    def locations(self, doc: Document) -> list[LocationFacts]:
        return get_locations(doc)

    def source_record(
        self, row: StagingRow, doc: Document, containers: Containers
    ) -> SourceRecordUpsert:
        return crossref_source_record(doc, row.id, containers)

    def author_block(self, doc: Document) -> AuthorBlock:
        return extract_crossref_author_block(doc)

    def author_records(self, block: AuthorBlock) -> list[AuthorRecord]:
        return build_crossref_author_records(block)
