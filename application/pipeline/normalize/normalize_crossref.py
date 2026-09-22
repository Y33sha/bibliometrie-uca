"""Normalisation des données CrossRef : staging → tables structurées.

Particularités CrossRef :
- `doc_type` stocké tel quel depuis `msg["type"]` ; le mapping taxonomie CrossRef → enum canonique vit dans `domain.source_publications.doc_types._SOURCE_MAPS["crossref"]` et est appliqué par `arbitrate_doc_type_with_article_subtype` au moment du refresh. Le cas `journal-article` indistinct est arbitré contre les sous-types plus précis exposés par HAL/OA (review, conference_paper, etc.) — cf. `ARTICLE_SUBTYPES`.
- `oa_status` non dérivé de CrossRef (pas fiable) ; laissé à NULL pour que les autres sources arbitrent via `refresh_from_sources`.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping

from sqlalchemy import Connection

from application.pipeline.normalize._authorships_batch import (
    AddressRecord,
    AuthorRecord,
    write_source_authorships,
)
from application.pipeline.normalize.bibliographic import BibliographicNormalizer
from application.ports.pipeline.containers import ContainerFindOrCreateQueries
from application.ports.pipeline.normalize.authorships import AuthorshipsBatchQueries
from application.ports.pipeline.normalize.source_publications import (
    SourcePublicationQueries,
    SourcePublicationUpsert,
)
from application.ports.pipeline.normalize.staging import StagingQueries, StagingRow
from application.ports.pipeline.publishers import PublisherFindOrCreateQueries
from application.ports.repositories.publication_repository import PublicationRepository
from application.services.monographs.containers import Containers, find_or_create_containers
from application.services.publishers.core import find_or_create_publisher
from domain.dates import today
from domain.journals.containers import ContainerDescription, ContainerRole, container_role
from domain.journals.series import split_collection_and_volume
from domain.persons.identifiers import (
    compact_identifiers,
    normalize_orcid,
)
from domain.publications.identifiers import clean_doi
from domain.publications.metadata import has_minimal_publication_metadata
from domain.source_publications.external_ids import ExternalIdType
from domain.sources.crossref import (
    extract_crossref_conference,
    extract_crossref_meta,
    extract_crossref_pub_year,
    parse_crossref_issns,
    strip_jats_tags,
)
from domain.types import JsonValue, as_mapping, as_sequence, as_str, as_strs

# =============================================================
# EXTRACTEURS DE CHAMPS
# =============================================================


def get_doi(msg: Mapping[str, JsonValue]) -> str | None:
    """DOI normalisé en lowercase. CrossRef expose le DOI tel que déposé."""
    return clean_doi(as_str(msg.get("DOI")))


def get_title(msg: Mapping[str, JsonValue]) -> str | None:
    titles = msg.get("title") or []
    if isinstance(titles, list) and titles:
        first = titles[0]
        if isinstance(first, str) and first.strip():
            return first.strip()
    if isinstance(titles, str) and titles.strip():
        return titles.strip()
    return None


def get_pub_year(msg: Mapping[str, JsonValue]) -> int | None:
    return extract_crossref_pub_year(msg, max_year=today().year + 1)


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


def get_external_ids(msg: Mapping[str, JsonValue]) -> dict[str, JsonValue] | None:
    """Identifiants secondaires (ISBN). DOI vit dans la colonne dédiée.

    `isbn-type` donne le support de chaque ISBN : celui de l'édition électronique va sous `eisbn`. Un ISBN sans support déclaré reste sous `isbn`.
    """
    ext: dict[str, JsonValue] = {}
    electroniques = {
        value
        for entry in as_sequence(msg.get("isbn-type"))
        if (value := as_str(as_mapping(entry).get("value")))
        and as_str(as_mapping(entry).get("type")) == "electronic"
    }
    isbns = [s for s in as_sequence(msg.get("ISBN")) if isinstance(s, str)]
    if papier := [s for s in isbns if s not in electroniques]:
        ext[ExternalIdType.ISBN] = papier
    if en_ligne := [s for s in isbns if s in electroniques]:
        ext[ExternalIdType.EISBN] = en_ligne
    return ext or None


def get_biblio(msg: Mapping[str, JsonValue]) -> dict[str, JsonValue] | None:
    """Volume, issue, page, article-number + publisher/journal bruts.

    `publisher` et `journal` (object) tracent le nom tel que vu par CrossRef en parallèle des publishers/journals créés via `find_or_create_*`.
    """
    biblio: dict[str, JsonValue] = {}
    for src_key, dest_key in (
        ("volume", "volume"),
        ("issue", "issue"),
        ("page", "page"),
        ("article-number", "article_number"),
    ):
        val = msg.get(src_key)
        if isinstance(val, str) and val.strip():
            biblio[dest_key] = val.strip()
    if publisher_raw := get_publisher_name(msg):
        biblio["publisher"] = publisher_raw
    journal_obj: dict[str, str] = {}
    if jt := get_container_title(msg):
        journal_obj["title"] = jt
    issn_val, eissn_val = get_issns(msg)
    if issn_val:
        journal_obj["issn"] = issn_val
    if eissn_val:
        journal_obj["eissn"] = eissn_val
    if journal_obj:
        biblio["journal"] = journal_obj
    return biblio or None


def get_meta(msg: Mapping[str, JsonValue]) -> Mapping[str, JsonValue] | None:
    return extract_crossref_meta(msg)


# =============================================================
# PUBLISHER + JOURNAL
# =============================================================


def upsert_publisher(
    msg: Mapping[str, JsonValue], *, publisher_repo: PublisherFindOrCreateQueries
) -> int | None:
    name = get_publisher_name(msg)
    if not name:
        return None
    return find_or_create_publisher(name, repo=publisher_repo)


def _container_titles(msg: Mapping[str, JsonValue]) -> list[str]:
    cts = msg.get("container-title")
    values = cts if isinstance(cts, list) else [cts]
    return [v.strip() for v in values if isinstance(v, str) and v.strip()]


def get_container_facts(msg: Mapping[str, JsonValue]) -> ContainerDescription:
    """Ce que Crossref dit du conteneur d'un document.

    Un livre porte sa collection dans `container-title`. Un chapitre ou un article de congrès y porte la collection et le livre ou le volume d'actes (`split_collection_and_volume`), ou le seul livre, ou la seule collection quand un ISSN la désigne. Sous une collection seule, le volume d'actes prend le nom du congrès.
    """
    raw_type = as_str(msg.get("type"))
    conference = extract_crossref_conference(msg)
    titles = _container_titles(msg)
    issn, eissn = get_issns(msg)
    external_ids = get_external_ids(msg) or {}
    role = container_role(raw_type, "crossref", declares_conference=conference is not None)
    collection_title = book_title = None
    if role is ContainerRole.BOOK:
        collection_title = titles[0] if titles else None
    elif role is ContainerRole.PART:
        if len(titles) >= 2:
            collection_title, book_title = split_collection_and_volume(titles[0], titles[-1])
        elif titles and (issn or eissn):
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
        issn=issn,
        eissn=eissn,
        isbns=tuple(as_strs(external_ids.get(ExternalIdType.ISBN))),
        eisbns=tuple(as_strs(external_ids.get(ExternalIdType.EISBN))),
        year=get_pub_year(msg),
    )


def upsert_containers(
    msg: Mapping[str, JsonValue],
    publisher_id: int | None,
    *,
    container_repo: ContainerFindOrCreateQueries,
) -> Containers:
    """Trouve ou crée la revue, ou la monographie et sa collection, qui contiennent le document."""
    return find_or_create_containers(
        get_container_facts(msg), publisher_id=publisher_id, repo=container_repo
    )


# =============================================================
# AUTEURS
# =============================================================


def _author_full_name(author: Mapping[str, JsonValue]) -> str:
    given = (as_str(author.get("given")) or "").strip()
    family = (as_str(author.get("family")) or "").strip()
    if given and family:
        return f"{given} {family}"
    return family or given or ""


def _author_affiliation_strings(author: Mapping[str, JsonValue]) -> list[str]:
    out: list[str] = []
    for aff in as_sequence(author.get("affiliation")):
        name = as_str(as_mapping(aff).get("name"))
        if name and name.strip():
            out.append(name.strip())
    return out


def build_crossref_author_records(msg: Mapping[str, JsonValue]) -> list[AuthorRecord]:
    """Parse les auteurs d'un message Crossref en `AuthorRecord` (sans I/O).

    - nom reconstruit via `_author_full_name` ;
    - ORCID (seul identifiant exploitable côté CrossRef) sur `person_identifiers` ;
    - affiliations brutes → adresses (sans pays) — c'est ce qui permet à la phase `affiliations` de poser `in_perimeter` sur les source_authorships crossref ;
    - `roles=['author']` explicite (Crossref ne distingue pas les rôles).
    """
    authors = msg.get("author") or []
    if not isinstance(authors, list):
        return []

    ids_by_position = [
        compact_identifiers(orcid=normalize_orcid(as_str(a.get("ORCID"))))
        if isinstance(a, dict)
        else None
        for a in authors
    ]

    records: list[AuthorRecord] = []
    for position, author in enumerate(authors):
        if not isinstance(author, dict):
            continue

        full_name = _author_full_name(author)
        if not full_name:
            continue

        ids = ids_by_position[position]
        records.append(
            AuthorRecord(
                position=position,
                raw_name=full_name,
                roles=["author"],
                person_identifiers=ids if ids else None,
                addresses=[AddressRecord(text=aff) for aff in _author_affiliation_strings(author)],
            )
        )
    return records


def process_authorships(
    conn: Connection,
    authorship_queries: AuthorshipsBatchQueries,
    msg: Mapping[str, JsonValue],
    source_publication_id: int,
) -> None:
    """Parse les auteurs Crossref puis écrit les authorships en batch."""
    records = build_crossref_author_records(msg)
    write_source_authorships(conn, authorship_queries, "crossref", source_publication_id, records)


# =============================================================
# BOUCLE PRINCIPALE
# =============================================================


def process_work(
    conn: Connection,
    queries: SourcePublicationQueries,
    logger: logging.Logger,
    staging_row: StagingRow,
    *,
    container_repo: ContainerFindOrCreateQueries,
    publisher_repo: PublisherFindOrCreateQueries,
    publication_repo: PublicationRepository,
    staging_queries: StagingQueries,
    authorship_queries: AuthorshipsBatchQueries,
) -> bool | None:
    staging_id = staging_row.id
    raw = staging_row.raw_data
    if not raw:
        # Stub not_found ou payload vide — devrait déjà être processed=TRUE, par sécurité on marque processed et on passe.
        staging_queries.mark_done(conn, staging_id)
        return None

    msg = raw  # CrossRef stocke directement le 'message'
    doi = get_doi(msg)
    if not doi:
        staging_queries.mark_done(conn, staging_id)
        return False

    title = get_title(msg)
    pub_year = get_pub_year(msg)
    if not has_minimal_publication_metadata(title, pub_year):
        staging_queries.mark_done(conn, staging_id)
        return False
    assert isinstance(title, str) and isinstance(pub_year, int)  # narrowing

    publisher_id = upsert_publisher(msg, publisher_repo=publisher_repo)
    containers = upsert_containers(msg, publisher_id, container_repo=container_repo)

    external_ids = get_external_ids(msg)
    biblio = get_biblio(msg)
    meta = get_meta(msg)

    source_publication_id = queries.upsert_source_publication(
        conn,
        SourcePublicationUpsert(
            source="crossref",
            source_id=doi,
            staging_id=staging_id,
            doi=doi,
            external_ids=external_ids,
            title=title,
            pub_year=pub_year,
            doc_type=as_str(msg.get("type")),
            journal_id=containers.journal_id,
            monograph_id=containers.monograph_id,
            container_title=get_container_title(msg) if not containers.journal_id else None,
            language=get_language(msg),
            biblio=biblio,
            abstract=get_abstract(msg),
            keywords=get_keywords(msg),
            oa_status=None,
            cited_by_count=get_cited_by_count(msg),
            meta=meta,
        ),
    )
    process_authorships(conn, authorship_queries, msg, source_publication_id)
    staging_queries.mark_done(conn, staging_id)
    return True


class CrossrefNormalizer(BibliographicNormalizer):
    SOURCE = "crossref"
    DEFAULT_BATCH_SIZE = 100

    def process_work(self, conn: Connection, row: StagingRow) -> bool | None:
        container_repo, publisher_repo, publication_repo = self._require_repos()
        return process_work(
            conn,
            self._queries,
            self.logger,
            row,
            container_repo=container_repo,
            publisher_repo=publisher_repo,
            publication_repo=publication_repo,
            staging_queries=self._staging,
            authorship_queries=self._authorship_queries,
        )
